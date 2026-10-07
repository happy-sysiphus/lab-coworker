import pytest

ALL_ENV = ("HORCRUX_VAULT", "HORCRUX_PROVIDER", "HORCRUX_MODEL")


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    # 모든 테스트에서 실제 ~/.horcrux/config.yaml·HORCRUX_* env 격리.
    # raising=False: Task 1 구현 전(_config_path 부재)에도 기존 테스트가 안 깨지게.
    from horcrux import config as config_mod
    p = tmp_path / "config.yaml"
    monkeypatch.setattr(config_mod, "_config_path", lambda: p, raising=False)
    for k in ALL_ENV:
        monkeypatch.delenv(k, raising=False)
    return p


@pytest.fixture
def kg_vault(tmp_path):
    """리서치 에이전트 테스트용 볼트 — 스즈키 커플링 흐름 합성 레코드 3건, 승인 클레임 3건, 위키 2개."""
    import yaml
    from horcrux import kg
    from horcrux.records import (
        ExperimentRecord, Parameter, Resolution, SuspectedCause, Symptom, save_record,
    )

    def rec(rid, raw, **kw):
        save_record(tmp_path, ExperimentRecord(id=rid, date=rid[:10], experiment_type="Suzuki-Miyaura coupling",
                                               equipment=["flow reactor"], **kw), raw, "정리")

    rec("2026-09-01_a-001", "XPhos Pd G3로 100도. 수율 낮음", materials=["XPhos Pd G3", "THF"],
        parameters=[Parameter(name="temperature", value="100 °C"), Parameter(name="residence time", value="360 s")],
        results="yield 40 %", symptom=Symptom(category="low_value", description="수율 낮음"),
        suspected_causes=[SuspectedCause(cause="protodeboronation", status="confirmed")],
        resolution=Resolution(resolved=True, actual_cause="protodeboronation"))
    rec("2026-09-02_a-002", "온도를 80도로 낮춤", materials=["XPhos Pd G3"], followup_of="2026-09-01_a-001",
        parameters=[Parameter(name="temperature", value="80 °C"), Parameter(name="residence time", value="360 s")],
        results="yield 70 %", symptom=Symptom(category="none", description="목표 근접"))
    rec("2026-09-03_b-001", "SPhos로 시도", materials=["SPhos Pd G3"],
        parameters=[Parameter(name="temperature", value="60 °C")],
        symptom=Symptom(category="low_value", description="전환율 낮음"),
        suspected_causes=[SuspectedCause(cause="protodeboronation", status="rejected")])
    src = lambda chunk, page, quote: [{"doc_id": "man-x", "chunk_id": chunk, "page": page, "quote": quote}]
    claims = [
        {"id": "c-1", "subject": "quantitykind:Temperature", "predicate": "promotes",
         "object": "lg:protodeboronation", "conditions": {"range": {"unit:DEG_C": [80, 120]}},
         "claim_status": "reported", "sources": src("man-x#3", 4, "higher temperature promotes protodeboronation")},
        {"id": "c-2", "subject": "lg:protodeboronation", "predicate": "decreases", "object": "lg:reaction_yield",
         "conditions": {}, "claim_status": "reported", "sources": src("man-x#5", 6, "protodeboronation lowers yield")},
        {"id": "s-1", "subject": "quantitykind:Temperature", "predicate": "spec_range", "object": "lg:flow_reactor",
         "conditions": {"range": {"unit:DEG_C": [30, 110]}}, "spec_kind": "allowed", "claim_status": "reported",
         "sources": src("man-x#9", 12, "30-110 °C")},
    ]
    (tmp_path / "ontology").mkdir(exist_ok=True)
    (tmp_path / "ontology" / "claims.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    for rel, text in (("equipment/flow-reactor.md", "---\nname: flow reactor\nkind: equipment\n---\n\n흐름 반응기 운용 노하우"),
                      ("failure-modes/suzuki-miyaura-coupling-값낮음.md",
                       "---\nname: Suzuki-Miyaura coupling-값낮음\nkind: failure-modes\n---\n\n값낮음 사례 모음")):
        p = tmp_path / "wiki" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    kg.rebuild(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """단위 테스트는 LLM·네트워크를 부르지 않는다 — 웹 검색과 원문 확인을 기본으로 막는다(필요한 테스트가 덮어쓴다)."""
    from horcrux import research_agent
    monkeypatch.setattr(research_agent, "web_search", lambda cfg, question, focus=None: [])
    monkeypatch.setattr(research_agent, "fetch_text", lambda url, *a, **k: None)

