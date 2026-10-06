from __future__ import annotations

from datetime import date as _date

from pydantic import BaseModel, Field

from . import ingest as ingest_mod
from .absorb import run_absorb
from .config import Config
from .llm import generate_parsed
from .records import save_record

SEED_SYSTEM = """wet lab 연구실의 가상 실험 로그를 만든다.
시나리오 예: RF 스퍼터링 ITO 박막 증착, 졸겔 TiO2 합성, 전기화학 증착, 스핀코팅.
신입~중급 연구원이 실험 직후 쓴 것 같은 자연스러운 한국어 로그 (목적, 장비, 공정변수 값, 결과 포함).
일부는 성공, 일부는 문제 포함 — 값이 낮음 / 재현 안 됨 / 개형이 이상함을 골고루.
서로 다른 시나리오·조건으로 다양하게."""


class SeedBatch(BaseModel):
    logs: list[str] = Field(default_factory=list)


def run_seed(cfg: Config, n: int) -> int:
    batch = generate_parsed(cfg, SEED_SYSTEM, f"실험 로그 {n}건을 생성하라.", SeedBatch)
    today = _date.today().isoformat()
    saved = 0
    for text in batch.logs[:n]:
        parsed = ingest_mod.parse_log(cfg, text)
        rec = ingest_mod.to_record(cfg.vault, parsed, today)
        save_record(cfg.vault, rec, text, parsed.summary)
        saved += 1
    if saved:
        run_absorb(cfg)
        try:
            from . import kg
            kg.sync_records(cfg.vault)
        except Exception as e:   # 저장은 확정 — 그래프는 'horcrux kg rebuild'로 다시 만들 수 있다
            print(f"(KG 동기화 실패 — 'horcrux kg rebuild'로 재시도: {e})")
    print(f"합성 로그 {saved}건 저장 (위키 편찬 포함)")
    return saved
