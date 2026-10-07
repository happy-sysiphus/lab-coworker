import pytest

from horcrux import research_agent as ra
from horcrux import trace
from horcrux.config import Config
from horcrux.llm import WebHit
from horcrux.records import record_path

REAL_FETCH = ra.fetch_text   # conftest가 테스트마다 네트워크 호출을 막기 전의 원본

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


def test_malformed_claims_are_skipped_with_warning(kg_vault, monkeypatch):
    import yaml
    p = kg_vault / "ontology" / "claims.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["claims"] += [
        {"id": "bad-range", "subject": "quantitykind:Temperature", "predicate": "spec_range",
         "object": "lg:flow_reactor", "conditions": {"range": {"unit:DEG_C": [30]}}},
        {"id": "bad-cond", "subject": "quantitykind:Temperature", "predicate": "promotes",
         "object": "lg:protodeboronation", "conditions": "high"},
        {"id": "bad-src", "subject": "lg:protodeboronation", "predicate": "decreases",
         "object": "lg:conversion", "sources": "man-x"}]
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(ra, "generate_parsed", _no_reform)
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: GOOD)
    d = ra.research(Config(vault=kg_vault), "flow reactor temperature 120도에서 XPhos Pd G3 수율이 낮아요")
    assert {"spec:s-1", "clm:c-1"} <= {c["id"] for c in d["cards"]}
    assert sum("claims.yaml" in w for w in d["warnings"]) == 3


def test_broader_alone_still_searches(kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate_parsed",
                        lambda cfg, s, u, schema: ra.Reform(term_ids=["lg:flow_reactor"], tools=["broader"]))
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: GOOD)
    d = ra.research(Config(vault=kg_vault), "반응기 쪽에서 왜 값이 안 나올까요?")
    assert (d["mode"], d["evidence"]) == ("seen", "records")


WEB_HITS = [WebHit(title="Plasma activation", url="https://a.test/p", quote="Plasma  activates the surface.",
                      summary="플라즈마는 표면을 활성화한다"),
            WebHit(title="Blog", url="https://b.test/q", quote="Something not on the page", summary="요약")]


def _web(monkeypatch, seen):
    def fake_search(cfg, question, focus=None):
        seen.append((question, focus))
        return WEB_HITS
    monkeypatch.setattr(ra, "web_search", fake_search)
    monkeypatch.setattr(ra, "fetch_text", lambda url, *a, **k:
                        "Intro. Plasma activates the surface. More." if url == "https://a.test/p" else None)


def test_unseen_searches_web_with_whole_question_and_checks_quotes(kg_vault, monkeypatch):
    seen = []
    _web(monkeypatch, seen)
    monkeypatch.setattr(ra, "generate_parsed", lambda cfg, s, u, schema: ra.Reform(unknown=["플라즈마 처리"]))
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u:
                        "원인 후보:\n- 외부 자료에 따르면 플라즈마는 표면을 활성화한다 [web:1]")
    d = ra.research(Config(vault=kg_vault), "플라즈마 처리는 어떻게 하나요?")
    assert seen == [("플라즈마 처리는 어떻게 하나요?", None)]
    assert (d["mode"], d["evidence"], d["warnings"]) == ("unseen", "web", [])
    assert [(c["id"], c["source"]["verified"]) for c in d["cards"]] == [("web:1", True), ("web:2", False)]
    assert "원문 확인" in d["cards"][0]["text"] and "확인 불가" in d["cards"][1]["text"]
    events = trace.get_run(kg_vault, d["run_id"])["events"]
    assert [e["stage"] for e in events][-4:] == ["p3.evaluate", "p3.web", "p3.answer", "p3.verify"]
    assert "원문 확인 1개" in next(e for e in events if e["stage"] == "p3.web")["summary"]


def test_web_cards_align_reworded_quotes_and_fix_swapped_sources(monkeypatch):
    pages = {"https://a.test": ("Intro. In contrast, we identified MIDA boronate (1a) as the first 2-pyridyl borane that is "
                                "both air stable and can be isolated in a chemically pure form. End."),
             "https://b.test": "Other. The slow release of boronic acids suppresses protodeboronation and homocoupling. End."}
    hits = [WebHit(title="A", url="https://a.test", quote=("MIDA boronate was identified as the first 2-pyridyl borane "
                                                            "that is both air stable and can be isolated in a chemically pure form.")),
            WebHit(title="C", url="https://c.test", quote="The slow release of boronic acids suppresses protodeboronation"),
            WebHit(title="B", url="https://b.test", quote="Slow release is a widely used strategy in many labs")]
    monkeypatch.setattr(ra, "web_search", lambda cfg, q, focus=None: hits)
    monkeypatch.setattr(ra, "fetch_text", lambda url, *a, **k: pages.get(url))
    cards, verified = ra.web_evidence(Config(vault="v"), "질문", None)
    a, c, b = (x["source"] for x in cards)
    assert a["verified"] and a["quote"].startswith("In contrast, we identified MIDA boronate (1a)")   # 페이지 원문으로 교체
    assert c["verified"] and c["url"] == "https://b.test"                                           # 출처 바로잡기
    assert not b["verified"] and verified == 2                                                      # 고쳐 쓴 말은 확인 불가


def test_partial_web_focuses_on_unknown_and_keeps_internal_cards(kg_vault, monkeypatch):
    seen = []
    _web(monkeypatch, seen)
    monkeypatch.setattr(ra, "generate_parsed", lambda cfg, s, u, schema: ra.Reform(unknown=["SPhos Pd G4"]))
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: "유사 사례:\n- 일반 조언 [일반지식]")
    d = ra.research(Config(vault=kg_vault), "flow reactor에서 SPhos Pd G4 써도 되나요?")
    assert seen[0][1] == ["SPhos Pd G4"] and d["mode"] == "partial"
    kinds = [c["kind"] for c in d["cards"]]
    assert kinds[-2:] == ["web", "web"] and set(kinds[:-2]) - {"wiki"}   # 내부 카드는 그대로, 웹은 예산 밖 뒤에


def test_web_failures_and_budget_become_warnings(kg_vault, monkeypatch):
    monkeypatch.setattr(ra, "generate_parsed", lambda cfg, s, u, schema: ra.Reform(unknown=["플라즈마 처리"]))
    monkeypatch.setattr(ra, "generate", lambda cfg, s, u: "확인 방법:\n- 일반 조언 [일반지식]")

    def boom(cfg, question, focus=None):
        raise RuntimeError("검색 시간 초과")
    monkeypatch.setattr(ra, "web_search", boom)
    d = ra.research(Config(vault=kg_vault), "플라즈마 처리는 어떻게 하나요?")
    assert d["warnings"] == ["웹 검색 실패: 검색 시간 초과"] and d["cards"] == []
    status = {e["stage"]: e["status"] for e in trace.get_run(kg_vault, d["run_id"])["events"]}
    assert status["p3.web"] == "fail"

    def unsupported(cfg, question, focus=None):
        raise ra.WebUnsupported("codex는 웹 검색을 지원하지 않습니다")
    monkeypatch.setattr(ra, "web_search", unsupported)
    d = ra.research(Config(vault=kg_vault), "플라즈마 처리는 어떻게 하나요?")
    assert d["warnings"] == ["codex는 웹 검색을 지원하지 않습니다"]
    d = ra.research(Config(vault=kg_vault), "플라즈마 처리는 어떻게 하나요?", web_ok=lambda: False)
    assert "사용량 한도" in d["warnings"][0]   # 한도에 닿으면 검색을 부르지 않는다


class _Resp:
    def __init__(self, body: bytes, ctype: str):
        from email.message import Message
        self.body, self.headers = body, Message()
        self.headers["Content-Type"] = ctype

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return self.body[:n]


def test_fetch_text_strips_scripts_and_skips_pdf(monkeypatch):
    html = "<html><script>var x = 1</script><p>Protodeboronation   is <b>fast</b></p></html>".encode("utf-8")
    monkeypatch.setattr(ra.urllib.request, "urlopen", lambda req, timeout: _Resp(html, "text/html; charset=utf-8"))
    assert REAL_FETCH("https://x.test/a") == "Protodeboronation is fast"
    monkeypatch.setattr(ra.urllib.request, "urlopen", lambda req, timeout: _Resp(b"%PDF-1.4", "application/pdf"))
    assert REAL_FETCH("https://x.test/a.pdf") is None
    assert REAL_FETCH("file:///etc/passwd") is None
    page = "The “masking” reagent protects the vulnerable boronic acid – slowly. Later text follows here."
    assert ra.quote_found(page, "The 'masking'  reagent protects the vulnerable boronic acid - slowly")
    assert ra.quote_found(page, "The masking ... nope") is False
    assert ra.quote_found(page, "reagent protects the vulnerable… Later text follows")
    assert not ra.quote_found(None, "reagent protects the vulnerable") and not ra.quote_found(page, "acid")
