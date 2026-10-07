"""kg.sqlite — 질의용 그래프(노드·엣지)와 실행 기록 테이블.

진실은 md 레코드와 온톨로지 YAML이고, 이 파일은 언제든 다시 만들 수 있는 파생물이다.
레코드 동기화는 frontmatter를 코드로 엣지화한다(LLM 재추출 없음). 연결 못 한 문자열은 임시 노드(tmp:)가 된다.
"""
from __future__ import annotations

import json
import math
import sqlite3
from array import array
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .records import ExperimentRecord, list_records, load_record
from .vocab import Vocabulary, canon, load_vocabulary

SCHEMA_VERSION = "2"
# 스키마가 바뀌어도 지우지 않는 테이블(접두사가 같은 FTS 보조 테이블 포함). 문서·청크·초안·질문은 진실에서
# 다시 만들려면 LLM 재추출이 필요하므로 남긴다. ponytail: 재구축이 llm_cache로 초안·질문을 다시 계산하게 하면 뺀다
KEEP_TABLES = ("llm_cache", "trace_run", "trace_event", "doc", "chunk", "vec", "item", "question")
SYMPTOM_LABEL = {"low_value": "값이 낮음", "unstable": "불안정·재현성", "abnormal": "비정상 거동", "none": "문제 없음"}
VOCAB_FILES = ("common.yaml", "overlay.yaml", "claims.yaml")
LABEL_MAX = 40
_DDL = """
create table if not exists meta(key text primary key, value text);
create table if not exists node(node_id text primary key, kind text, label text, label_ko text,
                                status text, props text);
create table if not exists edge(src text, rel text, dst text, props text, source_kind text, source_id text);
create index if not exists edge_src on edge(src);
create index if not exists edge_dst on edge(dst);
create index if not exists edge_source on edge(source_kind, source_id);
create table if not exists doc(doc_id text primary key, kind text, title text, source text, sha256 text,
                               pages integer, page_range text, status text, error text, created_at real);
create table if not exists chunk(chunk_id text primary key, doc_id text, page integer, seq integer, text text,
                                 status text, rounds integer default 0, error text);
create virtual table if not exists chunk_fts using fts5(chunk_id unindexed, doc_id unindexed, text);
create table if not exists vec(id text, kind text, model text, dims integer, v blob, primary key (id, kind));
create table if not exists item(item_id text primary key, kind text, source_kind text, source_id text, payload text,
                                status text, origin text, gate text, model text, prompt_sha text, reviewer text,
                                reviewed_at real, reason_code text, created_at real);
create table if not exists question(qid text primary key, kind text, tab text, group_key text, item_ids text,
                                    text text, recommended text, options text, context text, priority integer,
                                    count integer default 1, status text, answer text, answered_at real,
                                    created_at real);
create table if not exists llm_cache(key text primary key, output text, model text, prompt_ver text, created_at real);
create table if not exists trace_run(run_id text primary key, kind text, title text, status text,
                                     started_at real, ended_at real);
create table if not exists trace_event(run_id text, seq integer, ts real, stage text, status text,
                                       summary text, data text, ms integer, primary key (run_id, seq));
"""


def kg_path(vault: Path) -> Path:
    return Path(vault) / "kg.sqlite"


def _open(vault: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(kg_path(vault), timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode=wal")
        try:
            row = conn.execute("select value from meta where key='schema_version'").fetchone()
            ver = json.loads(row[0]) if row else None
        except sqlite3.OperationalError:
            ver = None
        if ver != SCHEMA_VERSION:
            # 파생물이므로 스키마가 바뀌면 지우고 다시 만든다. LLM 캐시와 실행 기록만 남긴다
            names = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
            for name in names:
                keep = any(name == k or name.startswith(k + "_") for k in KEEP_TABLES)
                if not keep and not name.startswith("sqlite_"):
                    conn.execute(f'drop table "{name}"')
            conn.executescript(_DDL)
            conn.execute("insert or replace into meta values('schema_version', ?)", (json.dumps(SCHEMA_VERSION),))
            conn.commit()
        return conn
    except Exception:
        conn.close()   # Windows는 열린 파일을 지우지 못한다
        raise


def _connect(vault: Path) -> sqlite3.Connection:
    Path(vault).mkdir(parents=True, exist_ok=True)
    try:
        return _open(vault)
    except sqlite3.OperationalError:
        raise   # 잠김 같은 일시적 오류 — 파일을 지우면 안 된다
    except sqlite3.DatabaseError as e:
        # 파생물 파일이 깨졌다(동기화 폴더 충돌, 중단된 쓰기). 지우고 다시 만든다 — 잃는 것은 실행 기록·캐시뿐
        print(f"(kg.sqlite가 손상돼 다시 만듭니다: {e})")
        for suffix in ("", "-wal", "-shm"):
            Path(f"{kg_path(vault)}{suffix}").unlink(missing_ok=True)
        return _open(vault)


@contextmanager
def db(vault: Path):
    conn = _connect(vault)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("select value from meta where key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute("insert or replace into meta values(?,?)", (key, json.dumps(value, ensure_ascii=False)))


def exp_id(record_id: str) -> str:
    return f"exp:{record_id}"


def _short(text: str) -> str:
    t = text.strip()
    return t if len(t) <= LABEL_MAX else t[:LABEL_MAX] + "…"


def _upsert_node(conn, nid: str, kind: str, label: str, label_ko: str = "", status: str = "verified",
                 props: dict | None = None) -> bool:
    new = conn.execute("select 1 from node where node_id=?", (nid,)).fetchone() is None
    conn.execute(
        "insert into node values(?,?,?,?,?,?) on conflict(node_id) do update set kind=excluded.kind, "
        "label=excluded.label, label_ko=excluded.label_ko, status=excluded.status, props=excluded.props",
        (nid, kind, label, label_ko, status, json.dumps(props or {}, ensure_ascii=False)))
    return new


def _term_node(conn, vocab: Vocabulary, tid: str) -> str:
    t = vocab.terms[tid]
    _upsert_node(conn, tid, t["kind"], vocab.label(tid), t.get("label_ko", ""))
    return tid


def param_delta(base: ExperimentRecord, rec: ExperimentRecord) -> dict:
    """후속 실험의 파라미터 차이 {이름: [기준 값, 후속 값]} — 관찰이지 인과가 아니다."""
    b = {p.name: p.value for p in base.parameters}
    n = {p.name: p.value for p in rec.parameters}
    return {k: [b.get(k), n.get(k)] for k in sorted(set(b) | set(n)) if b.get(k) != n.get(k)}


def sync_record(conn, vocab: Vocabulary, rec: ExperimentRecord, body: str,
                base: ExperimentRecord | None = None) -> dict:
    """레코드 하나를 그래프에 반영한다(멱등). LLM을 부르지 않는다."""
    conn.execute("delete from edge where source_kind='record' and source_id=?", (rec.id,))
    src = exp_id(rec.id)
    _upsert_node(conn, src, "experiment", _short(rec.title or rec.objective or rec.experiment_type or rec.id),
                 props={"record_id": rec.id, "date": rec.date, "experiment_type": rec.experiment_type,
                        "symptom": rec.symptom.category})
    counts = {"edges": 0, "temp": 0, "mentions": 0}

    def edge(rel: str, dst: str, props: dict | None = None) -> None:
        conn.execute("insert into edge values(?,?,?,?,?,?)",
                     (src, rel, dst, json.dumps(props or {}, ensure_ascii=False), "record", rec.id))
        counts["edges"] += 1

    def target(kind: str, text: str) -> str:
        status, ids = vocab.link(kind, text)
        if status == "linked":
            return _term_node(conn, vocab, ids[0])
        nid = f"tmp:{kind}:{canon(text)}"
        if _upsert_node(conn, nid, kind, _short(text), status="temp", props={"full": text.strip()}):
            counts["temp"] += 1
        return nid

    for e in rec.equipment:
        if e.strip():
            edge("USES_EQUIPMENT", target("equipment", e))
    for m in rec.materials:
        if m.strip():
            edge("USES_MATERIAL", target("material", m))
    if rec.experiment_type.strip():
        edge("OF_TECHNIQUE", target("technique", rec.experiment_type))
    for p in rec.parameters:
        if p.name.strip():
            q = vocab.parse_value(p.value) or {}
            edge("HAS_PARAMETER", target("parameter", p.name),
                 {"name": p.name, "value": p.value, "controllable": p.controllable, **q})
    sym = f"sym:{rec.symptom.category}"
    _upsert_node(conn, sym, "symptom", SYMPTOM_LABEL[rec.symptom.category])
    edge("EXHIBITS", sym, {"description": rec.symptom.description})
    for c in rec.suspected_causes:
        if c.cause.strip():
            edge("SUSPECTS", target("cause", c.cause), {"status": c.status})
    if rec.resolution.resolved and (rec.resolution.actual_cause or "").strip():
        edge("CONFIRMED_CAUSE", target("cause", rec.resolution.actual_cause))
    for i, a in enumerate(rec.actions_taken):
        if a.strip():
            aid = f"act:{rec.id}:{i}"
            _upsert_node(conn, aid, "action", _short(a), props={"full": a.strip()})
            edge("TOOK_ACTION", aid)
    if rec.followup_of and base is not None:
        edge("FOLLOWUP_OF", exp_id(rec.followup_of), {"delta": param_delta(base, rec)})
    for ref in rec.references:
        if ref.type == "record" and ref.record_id and ref.record_id != rec.id:
            edge("REFERENCES", exp_id(ref.record_id))
    seen: set[str] = set()
    for *_, tid in vocab.find_mentions("\n".join([body, rec.results, rec.symptom.description, rec.notes])):
        if tid not in seen:
            seen.add(tid)
            edge("MENTIONS", _term_node(conn, vocab, tid))
            counts["mentions"] += 1
    return counts


def sync_claims(conn, vocab: Vocabulary) -> int:
    """승인 클레임(공통 + 볼트 claims.yaml)을 엣지로 만든다. 용어·술어를 모르는 클레임은 건너뛴다."""
    conn.execute("delete from edge where source_kind='claim'")
    n = 0
    for c in vocab.claims:
        pred = vocab.predicate(str(c.get("predicate", "")))
        s, o = c.get("subject"), c.get("object")
        if pred is None or s not in vocab.terms or o not in vocab.terms:
            continue
        _term_node(conn, vocab, s)
        _term_node(conn, vocab, o)
        props = {"claim_id": c["id"], "conditions": c.get("conditions") or {},
                 "claim_status": c.get("claim_status", "reported"), "spec_kind": c.get("spec_kind")}
        conn.execute("insert into edge values(?,?,?,?,?,?)",
                     (s, pred["name"], o, json.dumps(props, ensure_ascii=False), "claim", c["id"]))
        n += 1
    return n


def _prune(conn) -> None:
    conn.execute("delete from node where kind not in ('experiment', 'passage') and node_id not in (select src from edge) "
                  "and node_id not in (select dst from edge)")


def sync_passages(conn, vocab: Vocabulary, doc_id: str | None = None) -> int:
    """매뉴얼·웹 청크를 passage 노드로 두고 승인 용어 정규식 스캔으로 MENTIONS 엣지를 잇는다(LLM 0회)."""
    titles = {r[0]: r[1] for r in conn.execute("select doc_id, title from doc")}
    rows = conn.execute("select chunk_id, doc_id, page, text from chunk" + (" where doc_id=?" if doc_id else ""),
                        (doc_id,) if doc_id else ()).fetchall()
    for cid, did, page, text in rows:
        conn.execute("delete from edge where source_kind='mention' and source_id=?", (cid,))
        nid = f"psg:{cid}"
        _upsert_node(conn, nid, "passage", _short(f"{titles.get(did, did)} p.{page}"),
                     props={"chunk_id": cid, "doc_id": did, "page": page})
        seen: set[str] = set()
        for *_, tid in vocab.find_mentions(text or ""):
            if tid not in seen:
                seen.add(tid)
                conn.execute("insert into edge values(?,?,?,?,?,?)",
                             (nid, "MENTIONS", _term_node(conn, vocab, tid), "{}", "mention", cid))
    return len(rows)


def store_vecs(conn, kind: str, ids: list[str], vectors: list[list[float]], model: str, dims: int) -> None:
    conn.executemany("insert or replace into vec values(?,?,?,?,?)",
                     [(i, kind, model, dims, array("f", v).tobytes()) for i, v in zip(ids, vectors)])


def load_vecs(conn, kind: str, model: str, dims: int) -> dict[str, list[float]]:
    """모델·차원이 지금 임베더와 같은 벡터만 읽는다 — 다르면 다시 계산할 대상이다."""
    out = {}
    for i, blob in conn.execute("select id, v from vec where kind=? and model=? and dims=?", (kind, model, dims)):
        a = array("f")
        a.frombytes(blob)
        out[i] = list(a)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    """ponytail: 순수 파이썬 전수 비교. 벡터가 수만 개를 넘으면 numpy나 ANN 색인을 검토한다"""
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _vocab_mtimes(vault: Path) -> dict:
    d = Path(vault) / "ontology"
    return {n: (d / n).stat().st_mtime for n in VOCAB_FILES if (d / n).exists()}


def _drop_record(conn, rid: str) -> None:
    conn.execute("delete from edge where source_kind='record' and source_id=?", (rid,))
    conn.execute("delete from node where node_id=?", (exp_id(rid),))


def sync_records(vault: Path, record_ids: list[str] | None = None, vocab: Vocabulary | None = None) -> dict:
    """레코드를 그래프에 반영한다. record_ids가 None이면 전부. 깨진 md·needs_review는 건너뛴다."""
    vault = Path(vault)
    vocab = vocab or load_vocabulary(vault)
    paths = {p.stem: p for p in list_records(vault)}
    ids = sorted(paths) if record_ids is None else [r for r in record_ids if r in paths]
    totals = {"records": 0, "edges": 0, "temp": 0, "mentions": 0, "skipped": 0}
    with db(vault) as conn:
        mtimes = {} if record_ids is None else get_meta(conn, "record_mtimes", {})
        for rid in ids:
            mtimes[rid] = paths[rid].stat().st_mtime
            try:
                rec, body = load_record(paths[rid])
            except Exception:
                print(f"(무시: 레코드 파싱 불가 — {paths[rid].name})")
                _drop_record(conn, rid)
                totals["skipped"] += 1
                continue
            if rec.needs_review:
                _drop_record(conn, rid)   # 파싱 실패 원문 — absorb와 같이 건너뛴다
                totals["skipped"] += 1
                continue
            base = None
            if rec.followup_of and rec.followup_of in paths:
                try:
                    base = load_record(paths[rec.followup_of])[0]
                except Exception:
                    base = None
            c = sync_record(conn, vocab, rec, body, base)
            totals["records"] += 1
            for k in ("edges", "temp", "mentions"):
                totals[k] += c[k]
        _prune(conn)
        set_meta(conn, "record_mtimes", mtimes)
        set_meta(conn, "vocab_mtimes", _vocab_mtimes(vault))
        set_meta(conn, "synced_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    return totals


def rebuild(vault: Path) -> dict:
    """노드·엣지를 진실(md·YAML)에서 처음부터 다시 만든다. LLM을 부르지 않는다."""
    vault = Path(vault)
    vocab = load_vocabulary(vault)
    with db(vault) as conn:
        conn.execute("delete from edge")
        conn.execute("delete from node")
        claims = sync_claims(conn, vocab)
        passages = sync_passages(conn, vocab)
    return {**sync_records(vault, None, vocab), "claims": claims, "passages": passages}


def refresh(vault: Path) -> dict:
    """질의 직전 최신화 — mtime이 바뀐 레코드만 다시 동기화하고, 온톨로지 YAML이 바뀌었으면 전부 다시 만든다.

    옵시디언 손편집이 서버를 거치지 않아도 질의에 반영된다. LLM 0회."""
    vault = Path(vault)
    with db(vault) as conn:
        mtimes = get_meta(conn, "record_mtimes")
        vm = get_meta(conn, "vocab_mtimes")
    if mtimes is None or vm != _vocab_mtimes(vault):
        return {"mode": "rebuild", **rebuild(vault)}
    paths = {p.stem: p for p in list_records(vault)}
    changed = sorted(rid for rid, p in paths.items() if mtimes.get(rid) != p.stat().st_mtime)
    removed = sorted(rid for rid in mtimes if rid not in paths)
    if removed:
        with db(vault) as conn:
            for rid in removed:
                _drop_record(conn, rid)
                mtimes.pop(rid, None)
            _prune(conn)
            set_meta(conn, "record_mtimes", mtimes)
    out = sync_records(vault, changed) if changed else {"records": 0}
    return {"mode": "incremental", "changed": len(changed), "removed": len(removed), **out}


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    out: dict[str, list[tuple[str, str, dict]]] = field(default_factory=dict)   # src -> [(rel, dst, props)]
    inn: dict[str, list[tuple[str, str, dict]]] = field(default_factory=dict)   # dst -> [(rel, src, props)]


def load_graph(vault: Path) -> Graph:
    """질의용 메모리 인접 리스트. ponytail: 질의마다 전부 읽는다 — 수만 엣지를 넘으면 버전별 캐시"""
    g = Graph()
    with db(vault) as conn:
        for r in conn.execute("select node_id, kind, label, label_ko, status, props from node"):
            g.nodes[r["node_id"]] = {"kind": r["kind"], "label": r["label"], "label_ko": r["label_ko"],
                                     "status": r["status"], "props": json.loads(r["props"] or "{}")}
        for r in conn.execute("select src, rel, dst, props from edge"):
            p = json.loads(r["props"] or "{}")
            g.out.setdefault(r["src"], []).append((r["rel"], r["dst"], p))
            g.inn.setdefault(r["dst"], []).append((r["rel"], r["src"], p))
    return g


def graph_data(vault: Path) -> dict:
    """그래프 화면용 노드·링크. action 노드는 뺀다. rec_ids는 그 노드와 이어진 실험 레코드다."""
    refresh(vault)
    with db(vault) as conn:
        nodes = [dict(r) for r in conn.execute("select * from node where kind!='action'")]
        edges = [dict(r) for r in conn.execute("select * from edge where rel!='TOOK_ACTION'")]
    rec_of: dict[str, set[str]] = {}
    for e in edges:
        if e["source_kind"] == "record":
            rec_of.setdefault(e["src"], set()).add(e["source_id"])
            if not e["dst"].startswith("exp:"):
                rec_of.setdefault(e["dst"], set()).add(e["source_id"])
    ids = {n["node_id"] for n in nodes}
    return {
        "nodes": [{"id": n["node_id"], "kind": n["kind"], "label": n["label"], "label_ko": n["label_ko"],
                   "status": n["status"], "full": json.loads(n["props"] or "{}").get("full") or n["label"],
                   "rec_ids": sorted(rec_of.get(n["node_id"], ()))} for n in nodes],
        "links": [{"source": e["src"], "target": e["dst"], "rel": e["rel"], "kind": e["source_kind"]}
                  for e in edges if e["src"] in ids and e["dst"] in ids],
    }


def status(vault: Path) -> dict:
    with db(vault) as conn:
        nodes = conn.execute("select count(*) from node").fetchone()[0]
        temp = conn.execute("select count(*) from node where status='temp'").fetchone()[0]
        edges = conn.execute("select count(*) from edge").fetchone()[0]
        synced = get_meta(conn, "synced_at")
    return {"nodes": nodes, "temp": temp, "edges": edges, "synced_at": synced}
