"""온톨로지 어휘 — 공통 어휘(실험 온톨로지 변환본), 연구실 overlay, 승인 클레임을 읽고 정규화·연결·멘션·단위를 다룬다.

질의와 구축이 함께 쓰는 순수 계층이다. LLM·네트워크·SQLite를 모른다.
연결(linking)은 라벨·동의어·positive 별칭의 canon 정확 일치만 쓴다. label_ko는 화면 표시 전용이다.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PKG_ONTOLOGY = Path(__file__).parent / "ontology"
TERM_KINDS = ("equipment", "material", "technique", "parameter", "metric", "cause")
# parameter는 HAS_PARAMETER 엣지로 잇는다. 'time'·'temperature' 같은 일반어가 멘션 잡음이 되지 않게 뺀다
MENTION_KINDS = ("equipment", "material", "technique", "cause", "metric")
# ponytail: 국립국어원 복수 표기 접기는 자주 보이는 것만 둔다. 충돌이 보이면 늘린다
_FOLD = (("트라이", "트리"), ("다이", "디"), ("메테인", "메탄"), ("에테인", "에탄"),
         ("프로페인", "프로판"), ("뷰테인", "부탄"))
_NUM = r"-?\d+(?:\.\d+)?"
_QTY = re.compile(rf"(?<![\w.])({_NUM})(?:\s*(?:~|–|—|-|to)\s*({_NUM}))?")
_BOUND = r"(?<![A-Za-z0-9_])(?:{})(?![A-Za-z0-9_])"   # 라벨 뒤 한글 조사("수율이")는 허용


def canon(text: str) -> str:
    """동일성 비교 키. NFKC·casefold, 'N호기'→N, 공백·하이픈·괄호 제거, 숫자 선행 0 제거, 복수 표기 접기.

    숫자는 보존하므로 FR-01과 FR-02는 절대 같아지지 않는다(호기 hard negative)."""
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    s = re.sub(r"(\d+)\s*호기", r"\1", s)
    s = re.sub(r"[\s\-_·•()\[\]{}]+", "", s)
    s = re.sub(r"\d+", lambda m: str(int(m.group())), s)
    for a, b in _FOLD:
        s = s.replace(a, b)
    return s


def _read_yaml(p: Path) -> dict:
    data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _safe_yaml(p: Path, warnings: list[str]) -> dict:
    """손편집 가능한 진실 파일 — 깨졌으면 그 파일만 건너뛰고 경고를 남긴다."""
    if not p.exists():
        return {}
    try:
        return _read_yaml(p)
    except Exception as e:
        warnings.append(f"{p.name}을(를) 읽지 못해 건너뜀: {e}")
        return {}


def _version_key(v) -> tuple[int, ...]:
    return tuple(int(x) if x.isdigit() else 0 for x in str(v or "0").split("."))


def write_atomic(p: Path, text: str) -> None:
    """설정·진실 파일 쓰기 — 임시 파일에 쓴 뒤 교체한다. 중간에 죽어도 반쯤 쓴 파일이 남지 않는다."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def ensure_common(vault: Path) -> Path:
    """볼트의 공통 온톨로지 사본이 없거나 깨졌거나 동봉본 version이 더 높으면 동봉본을 복사한다."""
    dst = Path(vault) / "ontology" / "common.yaml"
    pkg = PKG_ONTOLOGY / "common.yaml"
    try:
        cur = _read_yaml(dst).get("version", "0") if dst.exists() else None
    except Exception:
        cur = None   # 손편집 금지 파일이 깨졌으면 동봉본으로 되돌린다
    if cur is None or _version_key(_read_yaml(pkg).get("version")) > _version_key(cur):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pkg, dst)
    return dst


@dataclass
class Vocabulary:
    terms: dict[str, dict]
    units: list[dict]
    predicates: dict[str, dict]           # name -> predicate
    aliases: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    version: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._index: dict[tuple[str, str], set[str]] = {}
        self._negative: set[tuple[str, str]] = set()
        self._surface: dict[str, set[str]] = {}      # casefold 표면형 -> 용어 id (멘션용)
        for tid, t in self.terms.items():
            if t.get("hidden"):
                continue
            for s in [t["label"], *t.get("synonyms", [])]:
                self._add(t, s)
        for a in self.aliases:
            t = self.terms.get(a.get("term_id"))
            surface = str(a.get("surface", "")).strip()
            if t is None or not surface:
                continue
            if a.get("verdict") == "positive":
                self._add(t, surface)
            elif a.get("verdict") == "negative":
                self._negative.add((canon(surface), t["id"]))
                self._surface.get(surface.casefold(), set()).discard(t["id"])
        self._units = {u["id"]: u for u in self.units}
        self._unit_syn = sorted(((s, u) for u in self.units for s in [u["label"], *u.get("synonyms", [])]),
                                key=lambda x: -len(x[0]))
        self._pred_syn = {canon(s): p for p in self.predicates.values()
                          for s in [p["name"], p.get("label", ""), *p.get("synonyms", [])] if s}
        self._mention_rx: dict[tuple[str, ...], re.Pattern | None] = {}

    def _add(self, t: dict, surface: str) -> None:
        self._index.setdefault((t["kind"], canon(surface)), set()).add(t["id"])
        self._surface.setdefault(surface.casefold(), set()).add(t["id"])

    # ---------------------------------------------------------------- 연결
    def link(self, kind: str, text: str) -> tuple[str, list[str]]:
        """('linked', [id]) | ('unlinked', []) | ('ambiguous', ids). 같은 종류 안에서만 비교한다."""
        key = canon(text)
        if not key:
            return "unlinked", []
        ids = sorted(i for i in self._index.get((kind, key), ()) if (key, i) not in self._negative)
        if len(ids) == 1:
            return "linked", ids
        return ("ambiguous", ids) if ids else ("unlinked", [])

    def same(self, kind: str, a: str, b: str) -> bool:
        """표현만 다른 같은 대상인가 — canon이 같거나 둘 다 같은 용어로 연결된다."""
        if canon(a) == canon(b):
            return True
        sa, ia = self.link(kind, a)
        sb, ib = self.link(kind, b)
        return sa == sb == "linked" and ia == ib

    def predicate(self, name: str) -> dict | None:
        return self._pred_syn.get(canon(name))

    def label(self, tid: str) -> str:
        t = self.terms.get(tid)
        return (t.get("display") or t["label"]) if t else tid

    # ---------------------------------------------------------------- 멘션
    def find_mentions(self, text: str, kinds: tuple[str, ...] = MENTION_KINDS) -> list[tuple[int, int, str]]:
        """(start, end, term_id) — 긴 표면형 우선, 겹침 없음, 대소문자 무시. 여러 용어에 걸리는 표면형은 건너뛴다."""
        if kinds not in self._mention_rx:
            surfaces = [s for s, ids in self._surface.items()
                        if len(ids) == 1 and self.terms[next(iter(ids))]["kind"] in kinds]
            surfaces.sort(key=len, reverse=True)
            self._mention_rx[kinds] = re.compile(
                _BOUND.format("|".join(map(re.escape, surfaces))), re.IGNORECASE) if surfaces else None
        rx = self._mention_rx[kinds]
        if rx is None:
            return []
        return [(m.start(), m.end(), next(iter(self._surface[m.group(0).casefold()])))
                for m in rx.finditer(text)]

    # ---------------------------------------------------------------- 단위
    def _unit_at(self, s: str) -> tuple[dict, str] | None:
        low = s.casefold()
        for syn, u in self._unit_syn:
            k = syn.casefold()
            if not low.startswith(k):
                continue
            nxt = s[len(syn):len(syn) + 1]
            # 영문 단위 뒤에 영문·숫자가 붙으면 다른 단위다 ('s' 뒤 'ccm'). 한글 단위 뒤 조사는 허용
            if k[-1:].isascii() and k[-1:].isalpha() and nxt.isascii() and nxt.isalnum():
                continue
            return u, syn
        return None

    def find_quantities(self, text: str) -> list[dict]:
        """'80도', '60~110 °C', '5-10 min', '2 mol%' → [{lo, hi, unit, start, end}]. 단위가 없는 수는 뺀다."""
        out = []
        for m in _QTY.finditer(text):
            rest = text[m.end():]
            stripped = rest.lstrip()
            hit = self._unit_at(stripped)
            if hit is None:
                continue
            u, syn = hit
            lo = float(m.group(1))
            hi = float(m.group(2)) if m.group(2) else lo
            lo, hi = min(lo, hi), max(lo, hi)
            out.append({"lo": lo, "hi": hi, "unit": u["id"], "start": m.start(),
                        "end": m.end() + len(rest) - len(stripped) + len(syn)})
        return out

    def parse_value(self, text: str) -> dict | None:
        q = self.find_quantities(text)
        return {k: q[0][k] for k in ("lo", "hi", "unit")} if q else None

    def unit_symbol(self, unit_id: str) -> str:
        u = self._units.get(unit_id)
        return (u.get("symbol") or u["label"]) if u else unit_id

    def to_si(self, value: float, unit_id: str) -> tuple[str, float] | None:
        u = self._units.get(unit_id)
        if u is None:
            return None
        return u["dimension"], float(value) * float(u["factor"]) + float(u["offset"])

    def compare(self, q: dict, rng: dict) -> str:
        """값(구간) q가 범위 rng 안인가 — 같은 차원일 때만 SI로 환산해 비교한다."""
        a, b = self.to_si(q["lo"], q["unit"]), self.to_si(q["hi"], q["unit"])
        c, d = self.to_si(rng["lo"], rng["unit"]), self.to_si(rng["hi"], rng["unit"])
        if None in (a, b, c, d) or a[0] != c[0]:
            return "incomparable"
        eps = 1e-9
        return "inside" if c[1] - eps <= a[1] and b[1] <= d[1] + eps else "outside"


def load_vocabulary(vault: Path) -> Vocabulary:
    """공통 어휘(볼트 사본) + overlay(연구실 용어·별칭·오버라이드) + 승인 클레임."""
    vault = Path(vault)
    warnings: list[str] = []
    common = _read_yaml(ensure_common(vault))
    overlay = _safe_yaml(vault / "ontology" / "overlay.yaml", warnings)
    claims_doc = _safe_yaml(vault / "ontology" / "claims.yaml", warnings)
    terms = {t["id"]: dict(t) for t in common.get("terms", [])}
    for t in overlay.get("terms") or []:
        if isinstance(t, dict) and t.get("id") and t.get("label") and t.get("kind") in TERM_KINDS:
            terms[t["id"]] = {"synonyms": [], "parent": None, "label_ko": "", "source": "lab",
                              "verified": False, **t}
    for o in overlay.get("overrides") or []:
        t = terms.get(o.get("term_id")) if isinstance(o, dict) else None
        if t is None:
            continue
        t["synonyms"] = list(t.get("synonyms", [])) + list(o.get("synonyms_add") or [])
        if o.get("label_override"):
            t["display"] = o["label_override"]
        if o.get("hidden"):
            t["hidden"] = True
    claims = [c for c in (common.get("claims") or []) + (claims_doc.get("claims") or [])
              if isinstance(c, dict) and c.get("id")]
    return Vocabulary(
        terms=terms, units=list(common.get("units", [])),
        predicates={p["name"]: p for p in common.get("predicates", [])},
        aliases=[a for a in overlay.get("aliases") or [] if isinstance(a, dict)],
        claims=claims, version=str(common.get("version", "")), warnings=warnings)
