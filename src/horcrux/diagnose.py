from __future__ import annotations

from .config import Config
from .ingest import read_multiline
from .research_agent import research

# 근거 라벨 — 사례가 있으면 머리말 없이 답만, 나머지는 출처를 정직하게 밝힌다
BANNERS = {
    "none": "⚠ 연구실 기록·지식에 근거가 없습니다. 아래는 일반 지식 기반 조언입니다.",
    "knowledge": "ℹ 직접 유사한 실험 기록은 없어, 연구실 지식(위키·승인 관계) 기반 조언입니다.",
    "web": "ℹ 연구실 기록과 지식에 없는 질문이라 웹 근거로 답했습니다. 연구실 검증 전 정보입니다.",
}
MODE_NOTES = {
    "partial": "ℹ 일부 대상({unknown})은 연구실 지식에 없습니다.",
    "unseen": "ℹ 연구실 기록과 지식에 없는 질문입니다.",
}


def diagnose_data(cfg: Config, text: str, run_id: str | None = None) -> dict:
    return research(cfg, text, run_id)


def diagnose(cfg: Config, text: str) -> str:
    d = diagnose_data(cfg, text)
    head = [BANNERS[d["evidence"]]] if d["evidence"] in BANNERS else []
    if d.get("mode") in MODE_NOTES:
        head.append(MODE_NOTES[d["mode"]].format(unknown=", ".join(d.get("unknown") or [])))
    out = ("\n".join(head) + "\n\n" + d["answer"]) if head else d["answer"]
    if d.get("warnings"):
        out += "\n\n(검증 경고: " + "; ".join(d["warnings"]) + ")"
    return out


def run_ask(cfg: Config) -> None:
    print("문제 상황을 설명해주세요. 장비·재료·증상을 포함하면 더 정확합니다. (입력 종료: 빈 줄 2번)")
    text = read_multiline()
    if not text:
        print("입력이 없습니다.")
        return
    print("\n" + diagnose(cfg, text))
