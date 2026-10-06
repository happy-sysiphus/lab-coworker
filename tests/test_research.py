import pytest

from horcrux import research_agent as ra
from horcrux import trace
from horcrux.config import Config
from horcrux.records import record_path

GOOD = ("유사 사례:\n- 같은 반응기에서 수율이 낮았던 사례가 있다 [rec:2026-09-01_a-001]\n"
        "원인 후보:\n- 탈붕소화가 확정된 적이 있다 [cause:lg:protodeboronation]\n"
        "확인 방법:\n- 온도부터 확인한다 [일반지식]")


def _no_reform(*a, **k):
    raise AssertionError("재구성은 품질 목표를 못 채웠을 때만 부른다")


def test_seen_path_answers_without_reformulation(kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate_parsed", _no_reform)
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: GOOD)
    d = ra.research(Config(vault=kg_vault), "XPhos Pd G3로 flow reactor 돌렸는데 수율이 낮아요")
    assert (d["mode"], d["rounds"], d["evidence"], d["warnings"]) == ("seen", 0, "records", [])
    assert set(d) == {"answer", "evidence", "records", "wiki", "cards", "terms", "unknown", "mode",
                      "rounds", "warnings", "run_id"}   # 응답 계약
    assert d["records"][0]["id"] == "2026-09-01_a-001"
    assert set(d["records"][0]) == {"id", "date", "experiment_type", "objective", "symptom", "resolution"}
    assert "equipment/flow-reactor" in d["wiki"]
    stages = [e["stage"] for e in trace.get_run(kg_vault, d["run_id"])["events"]]
    assert stages == ["p3.link", "p3.search", "p3.integrate", "p3.evaluate", "p3.answer", "p3.verify"]


def test_reformulation_adds_terms_and_drops_hallucinated_ids(kg_vault, monkeypatch):
    calls = []

    def fake_reform(cfg, system, user, schema):
        calls.append(user)
        return ra.Reform(term_ids=["lg:flow_reactor", "lg:없는용어"], tools=["cases", "causes"], symptom="low_value")

    monkeypatch.setattr(ra, "generate_parsed", fake_reform)
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: GOOD)
    d = ra.research(Config(vault=kg_vault), "반응기 쪽에서 왜 값이 안 나올까요?")
    assert len(calls) == 1 and "lg:flow_reactor | flow reactor | 흐름 반응기" in calls[0]
    assert (d["mode"], d["rounds"]) == ("seen", 1)
    assert {"id": "lg:flow_reactor", "label": "flow reactor"} in d["terms"]
    events = trace.get_run(kg_vault, d["run_id"])["events"]
    assert [e["stage"] for e in events] == [   # 용어가 하나도 연결되지 않는 질의 — 워크플로 뷰가 그대로 그리는 계약
        "p3.link", "p3.search", "p3.integrate", "p3.evaluate", "p3.reformulate", "p3.tool",
        "p3.search", "p3.integrate", "p3.evaluate", "p3.answer", "p3.verify"]
    assert next(e for e in events if e["stage"] == "p3.reformulate")["data"]["dropped"] == ["lg:없는용어"]


def test_partial_and_unseen_modes(kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: "유사 사례:\n- 일반 조언 [일반지식]")
    monkeypatch.setattr(ra, "generate_parsed",
                        lambda cfg, s, u, schema: ra.Reform(unknown=["SPhos Pd G4"]))
    d = ra.research(Config(vault=kg_vault), "flow reactor에서 SPhos Pd G4 써도 되나요?")
    assert (d["mode"], d["unknown"]) == ("partial", ["SPhos Pd G4"])
    monkeypatch.setattr(ra, "generate_parsed",
                        lambda cfg, s, u, schema: ra.Reform(unknown=["플라즈마 처리"]))
    d = ra.research(Config(vault=kg_vault), "플라즈마 처리는 어떻게 하나요?")
    assert (d["mode"], d["evidence"], d["cards"]) == ("unseen", "none", [])


def test_repair_once_then_return_warnings(kg_vault, monkeypatch):
    answers = iter(["유사 사례:\n- 수율 55 %였다 [rec:없는-id]\n- 근거 없이 단정한다",
                    "유사 사례:\n- 수율 55 %였다 [rec:2026-09-01_a-001]"])
    seen = []

    def fake_generate(cfg, s, u):
        seen.append(u)
        return next(answers)

    monkeypatch.setattr(ra, "generate_parsed", _no_reform)
    monkeypatch.setattr(ra, "generate", fake_generate)
    d = ra.research(Config(vault=kg_vault), "XPhos Pd G3 flow reactor 수율")
    assert len(seen) == 2 and "고칠 점" in seen[1] and "카드에 없는 인용" in seen[1]
    assert d["warnings"] == ["근거에 없는 수치 55: 수율 55 %였다"]


def test_evidence_label_rules():
    def card(kind):
        return {"id": f"{kind}:x", "kind": kind, "title": "", "text": ""}
    assert ra.evidence_label([card("wiki"), card("rec")]) == "records"
    assert ra.evidence_label([card("wiki"), card("clm")]) == "knowledge"
    assert ra.evidence_label([card("wiki")]) == "knowledge"
    assert ra.evidence_label([card("web")]) == "web"
    assert ra.evidence_label([]) == "none"


def test_verify_rules():
    cards = [{"id": "rec:r1", "kind": "rec", "title": "사례", "text": "yield 40 %"},
             {"id": "web:1", "kind": "web", "title": "웹", "text": "외부 글"}]
    good = ("유사 사례:\n- 수율 40 %였다 [rec:r1]\n원인 후보:\n- 외부 자료에 따르면 촉매 문제 [web:1]\n"
            "확인 방법:\n- 장비 점검 [일반지식]")
    assert ra.verify(good, cards, "질문") == []
    bad = "1) 유사 사례\n- 수율 41 %였다 [rec:r1]\n- 촉매 문제 [web:1]\n- 인용 없음\n- 엉뚱한 인용 [clm:x]"
    issues = ra.verify(bad, cards, "질문")
    assert any("41" in i for i in issues)
    assert any("웹 근거 표시 누락" in i for i in issues)
    assert any("인용 없는 목록 줄" in i for i in issues)
    assert any("카드에 없는 인용: clm:x" in i for i in issues)
    assert not any("1) 유사 사례" in i or "유사 사례" == i for i in issues)


def test_empty_vault_and_corrupt_record_do_not_crash(tmp_path, kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: "유사 사례:\n- 없음 [일반지식]")
    monkeypatch.setattr(ra, "generate_parsed", lambda cfg, s, u, schema: ra.Reform())
    d = ra.research(Config(vault=tmp_path / "empty"), "아무거나")
    assert (d["evidence"], d["mode"]) == ("none", "unseen")
    record_path(kg_vault, "2026-09-09_bad-001").write_text("---\n: [\n---\n깨짐", encoding="utf-8")
    d = ra.research(Config(vault=kg_vault), "flow reactor 수율")
    assert d["evidence"] == "records"


def test_llm_failure_marks_run_failed(kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate_parsed", _no_reform)

    def boom(cfg, s, u):
        raise RuntimeError("claude 응답 없음")

    monkeypatch.setattr(ra, "generate", boom)
    with pytest.raises(RuntimeError):
        ra.research(Config(vault=kg_vault), "XPhos Pd G3 flow reactor", run_id="r-fail")
    assert trace.get_run(kg_vault, "r-fail")["run"]["status"] == "failed"
