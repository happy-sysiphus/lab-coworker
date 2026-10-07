"""승인 큐 — 초안(item)·질문(question) 저장, 질문 문장 템플릿(LLM 없음), 승인 처리와 YAML 기록 (스펙 6.5–6.7, 9).

승인 결과의 진실은 ontology/overlay.yaml(용어·별칭)과 ontology/claims.yaml(클레임)이다. 쓰기는 모두 원자적이고,
쓴 뒤에는 kg.sqlite를 다시 계산해 임시 노드를 용어 노드로 합치고 클레임 엣지를 잇는다.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import yaml

from . import kg, trace
from .vocab import TERM_KINDS, Vocabulary, canon, load_vocabulary, write_atomic

TABS = ("relation", "spec", "identity", "new_term", "conflict", "held", "auto")
TAB_OF = {"identity": "identity", "cause_label": "identity", "new_term": "new_term", "relation": "relation",
          "spec": "spec", "conflict": "conflict", "held": "held"}
PRIORITY = {"identity": 0, "new_term": 0, "cause_label": 0, "relation": 1, "spec": 2, "conflict": 3, "held": 4}
KIND_KO = {"equipment": "장비", "material": "물질", "technique": "기법", "parameter": "파라미터", "metric": "지표",
           "cause": "원인"}
REASONS = ("direction", "condition", "quote", "target", "other")
OPTIONS = {
    "identity": ["같음", "다름", "다른 용어 고르기", "보류"],
    "new_term": ["등록", "기존 용어에 연결", "아님", "보류"],
    "relation": ["권장대로", "아니오", "수정", "보류"],
    "spec": ["권장대로", "아니오", "수정", "보류"],
    "conflict": ["A", "B", "둘 다(조건이 다름)", "보류"],
    "held": ["수정 후 승인", "거절", "보류"],
}


# ---------------------------------------------------------------- 저장
def new_item(conn, kind: str, source_kind: str, source_id: str, payload: dict, status: str,
             origin: str = "llm", gate: dict | None = None, model: str | None = None) -> str:
    iid = "it-" + uuid.uuid4().hex[:12]
    conn.execute("insert into item values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (iid, kind, source_kind, source_id, json.dumps(payload, ensure_ascii=False), status, origin,
                  json.dumps(gate or {}, ensure_ascii=False), model, None, None, None, None, time.time()))
    return iid


def upsert_question(conn, kind: str, group_key: str, item_ids: list[str], text: str, recommended: dict,
                    context: dict, count: int = 1) -> str:
    """같은 (종류, 묶음 키)는 질문 하나로 묶고 등장 횟수를 더한다. 이미 답한 질문은 다시 묻지 않는다."""
    row = conn.execute("select qid, item_ids, count, status from question where kind=? and group_key=?",
                       (kind, group_key)).fetchone()
    if row:
        if row["status"] == "open":
            ids = list(dict.fromkeys(json.loads(row["item_ids"] or "[]") + item_ids))
            conn.execute("update question set item_ids=?, count=? where qid=?",
                         (json.dumps(ids), (row["count"] or 1) + count, row["qid"]))
        return row["qid"]
    qid = "q-" + uuid.uuid4().hex[:12]
    conn.execute("insert into question values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (qid, kind, TAB_OF[kind], group_key, json.dumps(item_ids), text,
                  json.dumps(recommended, ensure_ascii=False), json.dumps(OPTIONS.get(kind, []), ensure_ascii=False),
                  json.dumps(context, ensure_ascii=False), PRIORITY.get(kind, 5), count, "open", None, None, time.time()))
    return qid


def _row(r) -> dict:
    out = dict(r)
    for k in ("item_ids", "recommended", "options", "context", "answer", "payload", "gate"):
        if k in out and isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except ValueError:
                pass
    return out


def list_questions(vault: Path, tab: str | None = None, status: str = "open") -> list[dict]:
    q = "select * from question where status=?"
    args: list = [status]
    if tab:
        q += " and tab=?"
        args.append(tab)
    with kg.db(vault) as conn:
        rows = conn.execute(q + " order by priority, count desc, created_at", args).fetchall()
    return [_row(r) for r in rows]


def get_question(vault: Path, qid: str) -> dict | None:
    with kg.db(vault) as conn:
        r = conn.execute("select * from question where qid=?", (qid,)).fetchone()
        if r is None:
            return None
        q = _row(r)
        q["items"] = [_row(x) for x in conn.execute(
            f"select * from item where item_id in ({','.join('?' * len(q['item_ids']))})", q["item_ids"])] \
            if q["item_ids"] else []
    return q


def auto_items(vault: Path) -> list[dict]:
    with kg.db(vault) as conn:
        rows = conn.execute("select * from item where origin='code' and status='verified' and kind='claim' "
                            "order by created_at desc").fetchall()
    return [_row(r) for r in rows]


def status(vault: Path) -> dict:
    """문서 진행과 탭별 미답 수·완성도 = verified ÷ (verified + open)."""
    with kg.db(vault) as conn:
        docs = [dict(r) for r in conn.execute(
            "select d.doc_id, d.kind, d.title, d.status, d.error, d.created_at, "
            "(select count(*) from chunk c where c.doc_id=d.doc_id) as chunks, "
            "(select count(*) from chunk c where c.doc_id=d.doc_id and c.status in ('done','skipped')) as done "
            "from doc d order by d.created_at desc")]
        open_ = {t: n for t, n in conn.execute("select tab, count(*) from question where status='open' group by tab")}
        answered = {t: n for t, n in conn.execute(
            "select tab, count(*) from question where status='answered' group by tab")}
        auto = conn.execute("select count(*) from item where origin='code' and status='verified'").fetchone()[0]
    tabs = {t: {"open": open_.get(t, 0), "answered": answered.get(t, 0)} for t in TABS}
    tabs["auto"]["open"] = auto
    return {"docs": docs, "tabs": tabs, "open": sum(open_.values())}


def source_card(vault: Path, q: dict) -> dict:
    """승인 화면 맨 위의 원문 카드 — 매뉴얼은 문서명·쪽·청크 원문과 인용, 레코드는 기록 목록."""
    ctx = q.get("context") or {}
    src = ctx.get("source") or {}
    if src.get("chunk_id"):
        with kg.db(vault) as conn:
            r = conn.execute("select c.text, c.page, d.title, d.kind, d.source from chunk c join doc d "
                             "using(doc_id) where c.chunk_id=?", (src["chunk_id"],)).fetchone()
        if r:
            return {"kind": "web" if r["kind"] == "web" else "manual", "title": r["title"], "page": r["page"],
                    "text": r["text"], "quote": src.get("quote") or "", "url": r["source"] if r["kind"] == "web" else None,
                    "chunk_id": src["chunk_id"]}
    if src.get("records"):
        return {"kind": "record", "records": src["records"], "text": "; ".join(ctx.get("contexts") or [])}
    return {"kind": "none"}


# ---------------------------------------------------------------- 문장 템플릿 (질문을 만드는 LLM 호출은 없다)
def _label(vocab: Vocabulary, tid: str | None, fallback: str = "") -> str:
    return vocab.label(tid) if tid and tid in vocab.terms else (fallback or str(tid or ""))


def cond_text(vocab: Vocabulary, claim: dict) -> str:
    parts = [f"{k}={_label(vocab, claim.get(k + '_id'), claim.get(k) or '')}"
             for k in ("material", "equipment") if claim.get(k) or claim.get(k + "_id")]
    parts += [f"{lo:g}–{hi:g} {vocab.unit_symbol(u)}" for u, (lo, hi) in (claim.get("range") or {}).items()]
    return ", ".join(parts) or "없음"


def relation_text(vocab: Vocabulary, claim: dict) -> str:
    p = vocab.predicates.get(claim["predicate"])
    s = _label(vocab, claim.get("subject_id"), claim["subject"])
    o = _label(vocab, claim.get("object_id"), claim["object"])
    phrase = p["phrase_ko"].format(s=s, o=o) if p else f"{s} {claim['predicate']} {o}"
    return f"원문에 따르면 {phrase}. 조건: {cond_text(vocab, claim)}. 맞나요?"


def spec_text(vocab: Vocabulary, claim: dict) -> str:
    s = _label(vocab, claim.get("subject_id"), claim["subject"])
    o = _label(vocab, claim.get("object_id"), claim["object"])
    kind = "권장" if claim.get("spec_kind") == "recommended" else "허용"
    rng = ", ".join(f"{lo:g}–{hi:g} {vocab.unit_symbol(u)}" for u, (lo, hi) in (claim.get("range") or {}).items())
    return f"'{o}'의 '{s}' {kind} 범위가 {rng}인가요?"


def identity_text(vocab: Vocabulary, surface: str, term_id: str) -> str:
    t = vocab.terms.get(term_id, {})
    ko = f"({t['label_ko']})" if t.get("label_ko") else ""
    return f"'{surface}'는 '{vocab.label(term_id)}'{ko}과 같은 대상인가요?"


def new_term_text(vocab: Vocabulary, surface: str, kind: str, parent: str | None) -> str:
    return f"'{surface}'를 새 {KIND_KO.get(kind, kind)} 용어로 등록할까요? 상위 개념: {_label(vocab, parent) if parent else '없음'}"


# ---------------------------------------------------------------- YAML 쓰기
def _ont(vault: Path, name: str) -> Path:
    return Path(vault) / "ontology" / name


def _load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_yaml(p: Path, data: dict) -> None:
    data["version"] = int(data.get("version") or 0) + 1
    write_atomic(p, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def claim_id(claim: dict) -> str:
    key = json.dumps([claim["subject"], claim["predicate"], claim["object"], claim.get("conditions") or {}],
                     sort_keys=True, ensure_ascii=False)
    return "c-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def to_yaml_claim(c: dict, origin: str, reviewer: str | None) -> dict:
    """정규화된 클레임 초안(payload) → claims.yaml 항목 (4.3 형식)."""
    conditions = {"material": c.get("material_id"), "equipment": c.get("equipment_id"),
                  "range": {u: list(v) for u, v in (c.get("range") or {}).items()}, "fixed": {}}
    out = {"subject": c["subject_id"], "predicate": c["predicate"], "object": c["object_id"],
           "conditions": conditions, "claim_status": c.get("claim_status", "reported"),
           "spec_kind": c.get("spec_kind") if c["predicate"] == "spec_range" else None,
           "sources": [{"doc_id": c.get("doc_id"), "chunk_id": c.get("chunk_id"), "page": c.get("page"),
                        "quote": (c.get("quote") or "")[:400]}],
           "origin": origin, "reviewer": reviewer,
           "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    return {"id": claim_id(out), **out}


def add_claim(vault: Path, claim: dict) -> str:
    """claims.yaml에 더한다. 같은 내용(같은 id)이면 출처만 더한다(재게시 멱등)."""
    p = _ont(vault, "claims.yaml")
    doc = _load_yaml(p)
    claims = [c for c in doc.get("claims") or [] if isinstance(c, dict)]
    cur = next((c for c in claims if c.get("id") == claim["id"]), None)
    if cur:
        have = {s.get("chunk_id") for s in cur.get("sources") or []}
        cur["sources"] = (cur.get("sources") or []) + [s for s in claim["sources"] if s.get("chunk_id") not in have]
    else:
        claims.append(claim)
    doc["claims"] = claims
    _save_yaml(p, doc)
    return claim["id"]


def remove_claim(vault: Path, cid: str) -> bool:
    p = _ont(vault, "claims.yaml")
    doc = _load_yaml(p)
    claims = [c for c in doc.get("claims") or [] if isinstance(c, dict)]
    keep = [c for c in claims if c.get("id") != cid]
    if len(keep) == len(claims):
        return False
    doc["claims"] = keep
    _save_yaml(p, doc)
    return True


def add_overlay(vault: Path, section: str, entry: dict) -> None:
    p = _ont(vault, "overlay.yaml")
    doc = _load_yaml(p)
    doc[section] = [x for x in doc.get(section) or [] if isinstance(x, dict)] + [entry]
    _save_yaml(p, doc)


def _new_term_id(vocab: Vocabulary, label: str) -> str:
    from .manual import slugify
    base = f"lab:{slugify(label)}"
    tid, n = base, 2
    while tid in vocab.terms:
        tid, n = f"{base}-{n}", n + 1
    return tid


# ---------------------------------------------------------------- 승인 처리
class AnswerError(ValueError):
    pass


def answer(cfg, qid: str, action: str, reason_code: str | None = None, edit: dict | None = None,
           reviewer: str = "local") -> dict:
    """권장대로(accept)·수정(edit)·아니오(reject)·보류(hold)·건너뛰기(skip). 승인은 YAML에 쓰고 그래프를 다시 계산한다."""
    vault = Path(cfg.vault)
    q = get_question(vault, qid)
    if q is None:
        raise AnswerError("질문을 찾을 수 없습니다")
    if q["status"] != "open":
        raise AnswerError("이미 답한 질문입니다")
    edit = edit or {}
    kind, rec, items = q["kind"], q["recommended"] or {}, q["items"]
    if action == "skip":
        with kg.db(vault) as conn:
            conn.execute("update question set priority=priority+100 where qid=?", (qid,))
        return {"qid": qid, "status": "open", "skipped": True}
    if action == "hold":
        with kg.db(vault) as conn:
            conn.execute("update question set tab='held' where qid=?", (qid,))
            conn.executemany("update item set status='held' where item_id=?", [(i["item_id"],) for i in items])
        return {"qid": qid, "status": "open", "held": True}
    if action == "reject" and kind in ("relation", "spec", "held", "conflict") and reason_code not in REASONS:
        raise AnswerError(f"거절 사유 코드가 필요합니다: {', '.join(REASONS)}")
    if action not in ("accept", "edit", "reject"):
        raise AnswerError(f"알 수 없는 동작: {action}")

    vocab = load_vocabulary(vault)
    run_id = trace.start(vault, "approval", q["text"][:60])
    wrote: list[str] = []
    verdict = "rejected" if action == "reject" else "verified"
    ctx = q["context"] or {}
    if kind in ("identity", "cause_label"):
        surface = ctx.get("surface", "")
        term_id = edit.get("term_id") or rec.get("term_id")
        if action == "reject":
            if term_id in vocab.terms:
                add_overlay(vault, "aliases", {"surface": surface, "term_id": term_id, "verdict": "negative",
                                               "origin": "human", "reviewer": reviewer, "qid": qid})
                wrote.append("negative 별칭")
        else:
            if term_id not in vocab.terms:
                raise AnswerError("연결할 용어를 고르세요")
            add_overlay(vault, "aliases", {"surface": surface, "term_id": term_id, "verdict": "positive",
                                           "origin": "human", "reviewer": reviewer, "qid": qid,
                                           "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
            wrote.append(f"별칭 {surface} → {vocab.label(term_id)}")
    elif kind == "new_term":
        surface = ctx.get("surface", "")
        if action != "reject":
            if edit.get("term_id"):          # 기존 용어에 연결
                if edit["term_id"] not in vocab.terms:
                    raise AnswerError("연결할 용어를 고르세요")
                add_overlay(vault, "aliases", {"surface": surface, "term_id": edit["term_id"], "verdict": "positive",
                                               "origin": "human", "reviewer": reviewer, "qid": qid})
                wrote.append(f"별칭 {surface} → {vocab.label(edit['term_id'])}")
            else:
                nt = {**(rec.get("new_term") or {}), **{k: v for k, v in edit.items() if v not in (None, "")}}
                label = str(nt.get("label") or surface).strip()
                kind_ = nt.get("kind") if nt.get("kind") in TERM_KINDS else ctx.get("kind", "material")
                parent = nt.get("parent") if nt.get("parent") in vocab.terms else None
                tid = _new_term_id(vocab, label)
                add_overlay(vault, "terms", {"id": tid, "label": label, "kind": kind_, "parent": parent,
                                             "label_ko": nt.get("label_ko") or "",
                                             "synonyms": [surface] if canon(surface) != canon(label) else [],
                                             "origin": "human", "reviewer": reviewer, "qid": qid,
                                             "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
                wrote.append(f"용어 {tid}")
    elif kind in ("relation", "spec", "held", "conflict"):
        claim = dict(rec.get("claim") or {})
        if kind == "conflict":
            choice = edit.get("choice", "B")
            if action != "reject" and choice in ("B", "both"):
                if choice == "B" and rec.get("existing_id"):
                    remove_claim(vault, rec["existing_id"])
                    wrote.append(f"기존 클레임 {rec['existing_id']} 제거")
            else:
                claim = {}
        if action != "reject" and claim:
            claim = _apply_edit(vocab, claim, edit)
            missing = [s for s in ("subject_id", "object_id") if claim.get(s) not in vocab.terms]
            if missing or claim.get("predicate") not in vocab.predicates:
                raise AnswerError("주어·목적어 용어와 술어가 확정돼야 승인할 수 있습니다")
            cid = add_claim(vault, to_yaml_claim(claim, "llm", reviewer))
            wrote.append(f"클레임 {cid}")
    trace.event(vault, run_id, "p2.approve", "ok" if verdict == "verified" else "info",
                ("승인" if verdict == "verified" else "거절") + (f" · {', '.join(wrote)}" if wrote else ""),
                {"qid": qid, "kind": kind, "action": action})
    with kg.db(vault) as conn:
        conn.execute("update question set status='answered', answer=?, answered_at=? where qid=?",
                     (json.dumps({"action": action, "reason_code": reason_code, "edit": edit}, ensure_ascii=False),
                      time.time(), qid))
        conn.executemany("update item set status=?, reviewer=?, reviewed_at=?, reason_code=? where item_id=?",
                         [(verdict, reviewer, time.time(), reason_code, i["item_id"]) for i in items])
    if wrote:
        out = kg.rebuild(vault)
        from .ontology_agent import reevaluate_waiting   # 순환 import를 피한다
        again = reevaluate_waiting(cfg, run_id)
        trace.event(vault, run_id, "p2.store", "ok",
                    f"그래프 다시 계산 · 엣지 {out['edges']}개, 대기 클레임 재평가 {again}건", {"rebuild": out})
        trace.event(vault, run_id, "p2.context", "ok", "승인한 지식이 다음 추출의 기존 개념·관계가 됨")
    trace.finish(vault, run_id)
    return {"qid": qid, "status": "answered", "verdict": verdict, "wrote": wrote, "run_id": run_id}


def _apply_edit(vocab: Vocabulary, claim: dict, edit: dict) -> dict:
    """수정 폼: 술어·방향, 주어·목적어 용어, 범위 값·단위, 허용·권장."""
    c = dict(claim)
    if edit.get("predicate"):
        p = vocab.predicate(edit["predicate"])
        if p is None:
            raise AnswerError("술어는 7개 중 하나여야 합니다")
        c["predicate"] = p["name"]
    if edit.get("swap"):
        c["subject"], c["object"] = c["object"], c["subject"]
        c["subject_id"], c["object_id"] = c.get("object_id"), c.get("subject_id")
    for k in ("subject_id", "object_id", "material_id", "equipment_id"):
        if edit.get(k):
            if edit[k] not in vocab.terms:
                raise AnswerError(f"어휘에 없는 용어: {edit[k]}")
            c[k] = edit[k]
    if edit.get("lo") is not None and edit.get("hi") is not None:
        unit = vocab.unit_id(edit.get("unit") or next(iter(c.get("range") or {}), ""))
        lo, hi = float(edit["lo"]), float(edit["hi"])
        if unit is None or lo > hi:
            raise AnswerError("범위의 단위와 최소·최대 값을 확인하세요")
        c["range"] = {unit: [lo, hi]}
    if edit.get("spec_kind") in ("allowed", "recommended"):
        c["spec_kind"] = edit["spec_kind"]
    return c


def bulk_accept(cfg, qids: list[str], reviewer: str = "local") -> list[dict]:
    """동일성 탭에서만 권장대로 일괄 승인한다."""
    vault = Path(cfg.vault)
    out = []
    for qid in qids:
        q = get_question(vault, qid)
        if q is None or q["tab"] != "identity" or q["status"] != "open":
            continue
        out.append(answer(cfg, qid, "accept", reviewer=reviewer))
    return out


def revoke(cfg, item_id: str, reviewer: str = "local") -> dict:
    """자동 승인(또는 기존 승인) 취소 — claims.yaml에서 지우고 항목을 rejected로 둔다."""
    vault = Path(cfg.vault)
    with kg.db(vault) as conn:
        r = conn.execute("select * from item where item_id=?", (item_id,)).fetchone()
    if r is None:
        raise AnswerError("항목을 찾을 수 없습니다")
    payload = json.loads(r["payload"] or "{}")
    cid = payload.get("claim_id")
    removed = remove_claim(vault, cid) if cid else False
    with kg.db(vault) as conn:
        conn.execute("update item set status='rejected', reviewer=?, reviewed_at=?, reason_code='other' "
                     "where item_id=?", (reviewer, time.time(), item_id))
    if removed:
        kg.rebuild(vault)
    return {"item_id": item_id, "removed": removed}
