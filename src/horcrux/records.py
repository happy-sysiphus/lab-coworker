from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .vocab import load_vocabulary


class Parameter(BaseModel):
    name: str
    value: str
    controllable: bool = True


class Symptom(BaseModel):
    category: Literal["low_value", "unstable", "abnormal", "none"] = "none"
    description: str = ""


class SuspectedCause(BaseModel):
    cause: str
    status: Literal["unconfirmed", "confirmed", "rejected"] = "unconfirmed"


class Reference(BaseModel):
    # 타입을 Literal이 아니라 str로 둔다 — 나중에 "pdf" 같은 타입이 늘어도
    # 구버전이 신버전 md를 읽다 검증 실패하지 않게. UI는 3종만 만든다.
    type: str = "link"  # paper | link | record
    title: str = ""
    url: str = ""  # DOI는 프론트가 https://doi.org/... 로 정규화해서 보낸다
    record_id: str = ""  # record 타입만 사용


class Resolution(BaseModel):
    resolved: bool = False
    actual_cause: str | None = None
    note: str = ""


class ExperimentRecord(BaseModel):
    id: str
    date: str
    title: str = ""  # AI가 지은 6~15자 제목 — 표시용. 구기록엔 없음(빈 문자열 fallback)
    experiment_type: str = ""
    objective: str = ""
    equipment: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    results: str = ""
    symptom: Symptom = Field(default_factory=Symptom)
    suspected_causes: list[SuspectedCause] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    notes: str = ""  # 특이사항 — 문제로 단정되지 않은 과정 관찰·절차 일탈·환경 특이점
    references: list[Reference] = Field(default_factory=list)
    resolution: Resolution = Field(default_factory=Resolution)
    followup_of: str | None = None  # 후속 실험이면 기준 레코드 id
    needs_review: bool = False


def records_dir(vault: Path) -> Path:
    return vault / "raw" / "experiments"


def record_path(vault: Path, record_id: str) -> Path:
    # record_id는 외부 입력(API 본문·CLI 인자) — 구분자가 섞이면 볼트 밖으로 새어나간다
    if (not record_id or "/" in record_id or "\\" in record_id or ".." in record_id
            or Path(record_id).name != record_id):
        raise ValueError(f"레코드 id가 올바르지 않습니다: {record_id!r}")
    return records_dir(vault) / f"{record_id}.md"


def slugify(label: str) -> str:
    return re.sub(r"[^\w가-힣]+", "-", label).strip("-").lower() or "exp"


def make_record_id(vault: Path, date: str, label: str) -> str:
    slug = slugify(label)
    n = 1
    while record_path(vault, f"{date}_{slug}-{n:03d}").exists():
        n += 1
    return f"{date}_{slug}-{n:03d}"


def write_md(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    path.write_text(f"---\n{fm}---\n\n{body}\n", encoding="utf-8")


def read_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    _, fm, body = re.split(r"(?m)^---\s*$", text, maxsplit=2)
    return yaml.safe_load(fm), body.strip()


def save_record(vault: Path, rec: ExperimentRecord, raw_log: str, summary: str,
                qa: list[tuple[str, str]] | None = None) -> Path:
    body = f"## 원문 로그\n\n{raw_log}\n\n## 정리\n\n{summary}"
    if qa:
        # 재질문 이력은 본문에 남긴다 — 위키·관례 편찬 LLM이 자연히 읽는 위치
        pairs = "\n".join(f"- Q: {q}\n  A: {a}" for q, a in qa)
        body += f"\n\n## 재질문\n\n{pairs}"
    path = record_path(vault, rec.id)
    write_md(path, rec.model_dump(), body)
    return path


def load_record(path: Path) -> tuple[ExperimentRecord, str]:
    meta, body = read_md(path)
    return ExperimentRecord.model_validate(meta), body


def list_records(vault: Path) -> list[Path]:
    d = records_dir(vault)
    return sorted(d.glob("*.md")) if d.exists() else []


def update_resolution(
    vault: Path, record_id: str, resolved: bool,
    actual_cause: str | None, note: str = "",
) -> ExperimentRecord:
    path = record_path(vault, record_id)
    rec, body = load_record(path)
    rec.resolution = Resolution(resolved=resolved, actual_cause=actual_cause, note=note)
    if actual_cause:
        # 표현만 다른 같은 원인(공백·표기 차이, 승인된 별칭)을 기각으로 기록하지 않는다 — 그래프 원인 집계가 오염된다
        same = load_vocabulary(vault).same
        for c in rec.suspected_causes:
            c.status = "confirmed" if same("cause", c.cause, actual_cause) else "rejected"
        if all(c.status != "confirmed" for c in rec.suspected_causes):
            rec.suspected_causes.append(SuspectedCause(cause=actual_cause, status="confirmed"))
    write_md(path, rec.model_dump(), body)
    return rec
