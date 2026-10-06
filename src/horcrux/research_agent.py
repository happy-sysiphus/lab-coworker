"""리서치 에이전트 — 질의 때 연구실 지식은 그래프만 쓴다(벡터·전문 검색·LLM-select 카탈로그 없음).

질문 → 최신화 → 용어 연결 → 관계 검색(그래프 도구) → 근거 통합(카드) → 품질 평가
→ 미달이면 질문 재구성(Claude 1회) → 재검색 → 답변(Claude) → 출처 검증(코드, 수리 1회).
웹 검색(partial·unseen)과 원문 청크(passages)는 다음 마일스톤에서 붙는다. 지금은 mode만 계산한다.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import kg, trace
from .config import Config
from .llm import generate, generate_parsed
from .records import load_record, read_md, record_path
from .vocab import TERM_KINDS, Vocabulary, canon, load_vocabulary

TOOLS = ("cases", "causes", "relations", "specs", "wiki", "followups", "broader")
INITIAL_TOOLS = ("cases", "causes", "relations", "specs", "wiki", "followups")
CARD_LIMIT, CHAR_LIMIT = 15, 12000
CARD_ORDER = ("spec", "rec", "cause", "clm", "path", "psg", "fu", "wiki", "web")   # 예산이 넘치면 앞에서부터 남긴다
CATEGORY_KO = {"low_value": "값낮음", "unstable": "불안정", "abnormal": "비정상"}   # absorb 실패모드 이름 규칙
EXP_RELS = ("USES_EQUIPMENT", "USES_MATERIAL", "OF_TECHNIQUE", "HAS_PARAMETER", "MENTIONS")
_RECORD_ID = re.compile(r"\d{4}-\d{2}-\d{2}_[\w가-힣\-]+")
# 미연결 개체 후보 — 모델명(영문+숫자)을 먼저, 그다음 화학식·약어. 거칠므로 재구성에서 Claude가 다시 판정한다
_ENTITY = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+-?\d+[A-Za-z0-9]*"
    r"|(?:[A-Z][a-z]?\d*(?:\([A-Za-z0-9]+\)\d*)?){2,}"
    r"|[A-Z][a-z]?\([A-Za-z0-9]+\)\d+)(?![A-Za-z0-9])")
_LATIN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3,}(?![A-Za-z0-9])")
# ponytail: 영문 질문이 늘면 불용어 표가 모자란다 — 그때 늘리거나 영문 단어 규칙을 끈다
_STOP = set("""the and for with what which why how does did can could should would will are was were
is this that these those from into about after before during when where who whom our your their
any all some not but also very much many more most less than then too only same other new old
best good better worse use using used try tried run running get set high low first last next
step steps result results data test tests value values condition conditions experiment experiments
reaction reactions sample samples problem problems issue issues help please there here way ways
make made like just still even both each such per via vs etc""".split())


@dataclass
class Linking:
    terms: list[str] = field(default_factory=list)       # 어휘 용어 id + 임시 노드 id (등장 순서)
    records: list[str] = field(default_factory=list)     # 질문에 적힌 레코드 id의 실험 노드
    quantities: list[dict] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)    # 미연결 개체 후보


# ---------------------------------------------------------------- 용어 연결 (LLM 0회)
def link_question(vocab: Vocabulary, g: kg.Graph, question: str) -> Linking:
    link = Linking()
    spans: list[tuple[int, int]] = []

    def add(tid: str) -> None:
        if tid not in link.terms:
            link.terms.append(tid)

    for s, e, tid in vocab.find_mentions(question, kinds=TERM_KINDS):
        add(tid)
        spans.append((s, e))
    temps: dict[str, list[str]] = {}
    for nid, n in g.nodes.items():
        if n["status"] == "temp" and len(n["label"]) >= 2 and not n["label"].endswith("…"):
            temps.setdefault(n["label"].casefold(), []).append(nid)
    if temps:
        rx = re.compile(r"(?<![A-Za-z0-9_])(?:{})(?![A-Za-z0-9_])".format(
            "|".join(map(re.escape, sorted(temps, key=len, reverse=True)))), re.IGNORECASE)
        for m in rx.finditer(question):
            for nid in temps[m.group(0).casefold()]:
                add(nid)
            spans.append((m.start(), m.end()))
    for m in _RECORD_ID.finditer(question):
        nid = kg.exp_id(m.group(0).rstrip("-"))
        if nid in g.nodes and nid not in link.records:
            link.records.append(nid)
        spans.append((m.start(), m.end()))
    link.quantities = vocab.find_quantities(question)
    spans += [(q["start"], q["end"]) for q in link.quantities]
    masked = list(question)
    for s, e in spans:
        masked[s:e] = " " * (e - s)
    rest = "".join(masked)
    for m in _ENTITY.finditer(rest):
        if m.group(0) not in link.unlinked:
            link.unlinked.append(m.group(0))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in _LATIN.finditer(rest):
        w = m.group(0)
        if w.casefold() not in _STOP and w not in link.unlinked:
            link.unlinked.append(w)
    return link


# ---------------------------------------------------------------- 그래프 도구
def tool_cases(g: kg.Graph, terms: list[str], symptom: str | None = None, limit: int = 5) -> list[str]:
    shared: dict[str, set[str]] = {}
    for t in terms:
        for rel, src, _ in g.inn.get(t, []):
            if rel in EXP_RELS and src.startswith("exp:"):
                shared.setdefault(src, set()).add(t)

    def confirmed(e: str) -> bool:
        return any(rel == "CONFIRMED_CAUSE" for rel, _, _ in g.out.get(e, []))

    ranked = sorted(shared, key=lambda e: g.nodes[e]["props"].get("date", ""), reverse=True)
    ranked.sort(key=lambda e: (-len(shared[e]),
                               0 if symptom and g.nodes[e]["props"].get("symptom") == symptom else 1,
                               0 if confirmed(e) else 1))
    return ranked[:limit]


def tool_causes(g: kg.Graph, exps: list[str], terms: list[str]) -> list[dict]:
    ids: list[str] = []
    for e in exps:
        for rel, dst, _ in g.out.get(e, []):
            if rel in ("CONFIRMED_CAUSE", "SUSPECTS") and dst not in ids:
                ids.append(dst)
    ids += [t for t in terms if g.nodes.get(t, {}).get("kind") == "cause" and t not in ids]
    out = []
    for c in ids:
        conf = rej = sus = 0
        recs: set[str] = set()
        for rel, src, props in g.inn.get(c, []):
            if rel == "CONFIRMED_CAUSE":
                conf += 1
                recs.add(src[4:])
            elif rel == "SUSPECTS":
                recs.add(src[4:])
                if props.get("status") == "rejected":
                    rej += 1
                elif props.get("status") == "unconfirmed":
                    sus += 1
        out.append({"id": c, "confirmed": conf, "rejected": rej, "suspected": sus, "records": sorted(recs)})
    return out


def compatible(a: dict, b: dict) -> bool:
    """두 클레임을 이어도 되는가 — 재료·장비가 같고, 같은 단위 범위가 겹치고, 고정 조건이 같아야 한다(하네스 이식)."""
    for k in ("material", "equipment"):
        if a.get(k) and b.get(k) and a[k] != b[k]:
            return False
    rb = b.get("range") or {}
    for unit, (lo, hi) in (a.get("range") or {}).items():
        if unit in rb and (hi < rb[unit][0] or rb[unit][1] < lo):
            return False
    fb = b.get("fixed") or {}
    return all(fb[k] == v for k, v in (a.get("fixed") or {}).items() if k in fb)


def _claims(vocab: Vocabulary, spec: bool) -> list[dict]:
    out = []
    for c in vocab.claims:
        pred = vocab.predicate(str(c.get("predicate", "")))
        if pred and (pred["name"] == "spec_range") == spec and c.get("subject") in vocab.terms \
                and c.get("object") in vocab.terms:
            out.append({**c, "predicate": pred["name"]})
    return out


def tool_relations(vocab: Vocabulary, terms: list[str], limit: int = 8) -> list[dict]:
    claims = _claims(vocab, spec=False)
    tset = set(terms)
    items = [{"kind": "clm", "claims": [c]} for c in claims if c["subject"] in tset or c["object"] in tset]
    for c1 in claims:
        if c1["subject"] not in tset:
            continue
        for c2 in claims:
            if c2["subject"] == c1["object"] and c2["id"] != c1["id"] \
                    and compatible(c1.get("conditions") or {}, c2.get("conditions") or {}):
                items.append({"kind": "path", "claims": [c1, c2]})

    def covered(item: dict) -> int:
        return len({x for c in item["claims"] for x in (c["subject"], c["object"])} & tset)

    items.sort(key=lambda it: (-covered(it), len(it["claims"])))
    return items[:limit]


def tool_specs(vocab: Vocabulary, g: kg.Graph, terms: list[str], quantities: list[dict],
               exps: list[str]) -> list[dict]:
    tset = set(terms)
    out = []
    for c in _claims(vocab, spec=True):
        if c["subject"] not in tset and c["object"] not in tset:
            continue
        rng_items = list(((c.get("conditions") or {}).get("range") or {}).items())
        if not rng_items:
            continue
        unit, (lo, hi) = rng_items[0]
        rng = {"lo": float(lo), "hi": float(hi), "unit": unit}
        dim = (vocab.to_si(0, unit) or ("?", 0))[0]
        checks = []
        for q in quantities:
            if (vocab.to_si(0, q["unit"]) or ("", 0))[0] == dim:
                value = f"{q['lo']:g} {vocab.unit_symbol(q['unit'])}" if q["lo"] == q["hi"] else \
                    f"{q['lo']:g}–{q['hi']:g} {vocab.unit_symbol(q['unit'])}"
                checks.append({"who": "질문", "value": value, "result": vocab.compare(q, rng)})
        for e in exps:
            for rel, dst, p in g.out.get(e, []):
                if rel == "HAS_PARAMETER" and dst == c["subject"] and "unit" in p:
                    checks.append({"who": e[4:], "value": p["value"], "result": vocab.compare(p, rng)})
        out.append({"claim": c, "range": rng, "checks": checks})
    return out


def tool_wiki(vault: Path, vocab: Vocabulary, g: kg.Graph, terms: list[str], exps: list[str]) -> list[dict]:
    tset = set(terms)
    out = []
    for folder, kind in (("equipment", "equipment"), ("materials", "material")):
        for p in sorted((Path(vault) / "wiki" / folder).glob("*.md")):
            try:
                meta, body = read_md(p)
            except Exception:
                continue
            name = str(meta.get("name", p.stem))
            status, ids = vocab.link(kind, name)
            tid = ids[0] if status == "linked" else f"tmp:{kind}:{canon(name)}"
            if tid in tset:
                out.append({"id": f"{folder}/{p.stem}", "name": name, "body": body})
    if exps:
        props = g.nodes[exps[0]]["props"]
        if props.get("symptom") in CATEGORY_KO:
            want = f"{props.get('experiment_type') or '일반'}-{CATEGORY_KO[props['symptom']]}"
            for p in sorted((Path(vault) / "wiki" / "failure-modes").glob("*.md")):
                try:
                    meta, body = read_md(p)
                except Exception:
                    continue
                if meta.get("name") == want:
                    out.append({"id": f"failure-modes/{p.stem}", "name": want, "body": body})
    return out


def tool_followups(g: kg.Graph, exps: list[str]) -> list[dict]:
    out, seen = [], set()
    for e in exps:
        pairs = [(e, dst, p) for rel, dst, p in g.out.get(e, []) if rel == "FOLLOWUP_OF"]
        pairs += [(src, e, p) for rel, src, p in g.inn.get(e, []) if rel == "FOLLOWUP_OF"]
        for fu, base, p in pairs:
            if fu not in seen:
                seen.add(fu)
                out.append({"record_id": fu[4:], "base_id": base[4:], "delta": p.get("delta") or {}})
    return out


# ---------------------------------------------------------------- 증거 카드
def _record_card(vault: Path, record_id: str) -> dict | None:
    try:
        rec, body = load_record(record_path(vault, record_id))
    except Exception:
        return None
    raw = body.split("## 원문 로그", 1)[-1].split("## 정리", 1)[0].strip()
    causes = [f"{c.cause}({c.status})" for c in rec.suspected_causes]
    lines = [f"날짜: {rec.date}", f"유형: {rec.experiment_type}", f"장비: {', '.join(rec.equipment)}",
             f"재료: {', '.join(rec.materials)}",
             "파라미터: " + "; ".join(f"{p.name}={p.value}" for p in rec.parameters),
             f"결과: {rec.results}", f"증상: {rec.symptom.category} {rec.symptom.description}".rstrip(),
             f"해결: {'예, 원인 ' + (rec.resolution.actual_cause or '미기록') if rec.resolution.resolved else '아니오'}",
             f"원인 후보: {', '.join(causes) or '없음'}", f"조치: {', '.join(rec.actions_taken) or '없음'}",
             f"원문: {raw[:400]}"]
    return {"id": f"rec:{rec.id}", "kind": "rec", "title": f"사례 {rec.id} · {rec.title or rec.objective}",
            "text": "\n".join(lines), "source": {"record_id": rec.id}}


def _claim_text(vocab: Vocabulary, c: dict) -> str:
    phrase = vocab.predicates[c["predicate"]]["phrase_ko"].format(s=vocab.label(c["subject"]),
                                                                  o=vocab.label(c["object"]))
    cond = c.get("conditions") or {}
    parts = [f"{k}={vocab.label(cond[k])}" for k in ("material", "equipment") if cond.get(k)]
    parts += [f"{lo:g}–{hi:g} {vocab.unit_symbol(u)}" for u, (lo, hi) in (cond.get("range") or {}).items()]
    src = (c.get("sources") or [{}])[0]
    where = f" 출처: {src.get('doc_id', '')} p.{src.get('page', '?')} \"{src.get('quote', '')}\"" if src else ""
    return phrase + (f" (조건: {', '.join(parts)})" if parts else "") + where


def collect(vault: Path, vocab: Vocabulary, g: kg.Graph, link: Linking, tools, symptom: str | None = None
            ) -> tuple[list[dict], dict]:
    """고른 그래프 도구를 돌려 증거 카드를 만든다. 돌려주는 hits는 도구별 결과 수다."""
    terms, hits, cards = link.terms, {}, []
    exps = list(link.records)
    if "cases" in tools:
        exps += [e for e in tool_cases(g, terms, symptom) if e not in exps]
        hits["cases"] = len(exps)
    cards += [c for c in (_record_card(vault, e[4:]) for e in exps) if c]
    if "causes" in tools:
        cs = tool_causes(g, exps, terms)
        hits["causes"] = len(cs)
        for c in cs:
            n = g.nodes.get(c["id"], {})
            label = n.get("props", {}).get("full") or n.get("label") or c["id"]
            cards.append({"id": f"cause:{c['id']}", "kind": "cause", "title": f"원인 · {label}",
                          "text": f"확정 {c['confirmed']}건, 기각 {c['rejected']}건, 추정 {c['suspected']}건 "
                                  f"(기록: {', '.join(c['records']) or '없음'})",
                          "source": {"term_id": c["id"]}})
    if "relations" in tools:
        rs = tool_relations(vocab, terms)
        hits["relations"] = len(rs)
        for r in rs:
            if r["kind"] == "clm":
                c = r["claims"][0]
                cards.append({"id": f"clm:{c['id']}", "kind": "clm", "title": "관계",
                              "text": _claim_text(vocab, c), "source": (c.get("sources") or [{}])[0]})
            else:
                key = hashlib.sha1("|".join(c["id"] for c in r["claims"]).encode()).hexdigest()[:8]
                cards.append({"id": f"path:{key}", "kind": "path", "title": "경로 (추론)",
                              "text": " → ".join(_claim_text(vocab, c) for c in r["claims"])
                              + "\n(별도 진술을 이은 추론이며 보고된 인과가 아님)",
                              "source": {"claims": [c["id"] for c in r["claims"]]}})
    if "specs" in tools:
        ss = tool_specs(vocab, g, terms, link.quantities, exps)
        hits["specs"] = len(ss)
        word = {"inside": "범위 안", "outside": "범위 밖", "incomparable": "비교 불가"}
        for s in ss:
            c, rng = s["claim"], s["range"]
            kind = "허용" if c.get("spec_kind") == "allowed" else "권장" if c.get("spec_kind") else "명시"
            lines = [f"{vocab.label(c['object'])}의 {vocab.label(c['subject'])} {kind} 범위 "
                     f"{rng['lo']:g}–{rng['hi']:g} {vocab.unit_symbol(rng['unit'])}"]
            lines += [f"{x['who']}: {x['value']} → {word[x['result']]}" for x in s["checks"]]
            cards.append({"id": f"spec:{c['id']}", "kind": "spec", "title": "스펙",
                          "text": "\n".join(lines), "source": (c.get("sources") or [{}])[0]})
    if "wiki" in tools:
        ws = tool_wiki(vault, vocab, g, terms, exps)
        hits["wiki"] = len(ws)
        cards += [{"id": f"wiki:{w['id']}", "kind": "wiki", "title": f"위키 · {w['name']}",
                   "text": w["body"][:1500], "source": {"wiki": w["id"]}} for w in ws]
    if "followups" in tools:
        fs = tool_followups(g, exps)
        hits["followups"] = len(fs)
        cards += [{"id": f"fu:{f['record_id']}", "kind": "fu", "title": f"후속 · {f['record_id']} ← {f['base_id']}",
                   "text": "; ".join(f"{k}: {a} → {b}" for k, (a, b) in f["delta"].items())
                   + "\n(관찰이지 인과가 아님)", "source": {"record_id": f["record_id"]}} for f in fs]
    return budget(cards), hits


def budget(cards: list[dict]) -> list[dict]:
    uniq = list({c["id"]: c for c in cards}.values())
    uniq.sort(key=lambda c: CARD_ORDER.index(c["kind"]) if c["kind"] in CARD_ORDER else len(CARD_ORDER))
    out, used = [], 0
    for c in uniq:
        size = len(c["title"]) + len(c["text"])
        if len(out) >= CARD_LIMIT or used + size > CHAR_LIMIT:
            continue
        out.append(c)
        used += size
    return out
