import pytest
from fastapi.testclient import TestClient

from horcrux import server
from horcrux.config import Config
from horcrux.ingest import ParsedLog
from horcrux.records import ExperimentRecord, record_path, save_record, write_md


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "run_absorb", lambda cfg: 0)
    return TestClient(server.create_app(Config(vault=tmp_path))), tmp_path


def test_parse_returns_parsed_and_gaps(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(server, "parse_log",
                        lambda cfg, text, vcfg: ParsedLog(objective="막 증착"))
    r = c.post("/api/parse", json={"text": "오늘 증착"})
    assert r.status_code == 200
    assert r.json()["parsed"]["objective"] == "막 증착"
    assert any("결과" in g for g in r.json()["gaps"])  # results 미기재 → 재질문


def test_save_creates_record_with_followup(client):
    c, vault = client
    parsed = ParsedLog(experiment_type="증착", objective="o", results="r",
                       summary="요약").model_dump()
    r = c.post("/api/records", json={"text": "원문", "parsed": parsed,
                                     "followup_of": "2026-07-31_x-001"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert record_path(vault, rid).exists()
    detail = c.get(f"/api/records/{rid}").json()
    assert detail["record"]["followup_of"] == "2026-07-31_x-001"
    assert "원문" in detail["body"]


def test_save_raw_needs_review(client):
    c, _ = client
    r = c.post("/api/records/raw", json={"text": "깨진 로그"})
    rid = r.json()["id"]
    detail = c.get(f"/api/records/{rid}").json()
    assert detail["record"]["needs_review"] is True


def test_ask_passthrough_with_run_id(client, monkeypatch):
    c, _ = client
    seen = {}

    def fake(cfg, t, run_id=None):
        seen["run_id"] = run_id
        return {"answer": "a", "evidence": "none", "records": [], "wiki": []}

    monkeypatch.setattr(server, "diagnose_data", fake)
    assert c.post("/api/ask", json={"text": "q", "run_id": "r1"}).json()["evidence"] == "none"
    assert seen["run_id"] == "r1"


def test_list_and_detail_404(client):
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_a-001", date="2026-08-01"), "원문", "s")
    assert c.get("/api/records").json()["records"][0]["id"] == "2026-08-01_a-001"
    assert c.get("/api/records/없는-id").status_code == 404


def test_feedback_updates_resolution(client):
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_b-001", date="2026-08-01"), "원문", "s")
    r = c.post("/api/feedback", json={"record_id": "2026-08-01_b-001",
                                      "resolved": True, "cause": "타겟 산화"})
    assert r.status_code == 200
    detail = c.get("/api/records/2026-08-01_b-001").json()
    assert detail["record"]["resolution"]["resolved"] is True
    assert detail["record"]["resolution"]["actual_cause"] == "타겟 산화"


def test_references_roundtrip(client):
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_c-001", date="2026-08-01"), "원문", "s")
    refs = [{"type": "paper", "title": "ALD 논문", "url": "https://doi.org/10.1/x", "record_id": ""},
            {"type": "record", "title": "", "url": "", "record_id": "2026-08-01_c-001"}]
    r = c.put("/api/records/2026-08-01_c-001/references", json={"references": refs})
    assert r.status_code == 200
    assert r.json()["record"]["references"] == refs
    detail = c.get("/api/records/2026-08-01_c-001").json()
    assert detail["record"]["references"] == refs
    assert "원문 로그" in detail["body"]  # 본문 보존


def test_references_missing_record(client):
    c, _ = client
    assert c.put("/api/records/없는것/references", json={"references": []}).status_code == 404


def test_legacy_record_without_references_key(client):
    c, vault = client
    # references 키가 없는 구버전 md도 읽혀야 한다
    write_md(record_path(vault, "2026-08-01_d-001"),
             {"id": "2026-08-01_d-001", "date": "2026-08-01"}, "본문")
    assert c.get("/api/records").json()["records"][0]["references"] == []


def test_auth_config_local(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    j = c.get("/api/auth-config").json()
    assert j == {"deploy": False, "supabase_url": None, "supabase_anon_key": None}


def test_config_endpoint(client):
    c, _ = client
    j = c.get("/api/config").json()
    assert "objective" in j["required_fields"]
    assert j["provider"] == "claude"


def test_save_syncs_graph_and_records_run(client):
    from horcrux import trace
    c, vault = client
    parsed = ParsedLog(experiment_type="Suzuki-Miyaura coupling", equipment=["flow reactor"],
                       objective="o", results="r", summary="요약").model_dump()
    r = c.post("/api/records", json={"text": "원문", "parsed": parsed}).json()
    rid = r["id"]
    graph = c.get("/api/kg/graph").json()
    exp = next(n for n in graph["nodes"] if n["id"] == f"exp:{rid}")
    assert exp["kind"] == "experiment"
    link = {"source": f"exp:{rid}", "target": "lg:flow_reactor", "rel": "USES_EQUIPMENT", "kind": "record"}
    assert link in graph["links"]
    run = trace.get_run(vault, r["run_id"])
    assert run["run"]["status"] == "done"
    assert [e["stage"] for e in run["events"]] == ["p1.parse", "p1.save", "p1.wiki", "p2.normalize", "p2.store"]


def test_feedback_and_edit_resync_graph(client):
    from horcrux import kg
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_a-001", date="2026-08-01"), "원문", "s")
    c.post("/api/feedback", json={"record_id": "2026-08-01_a-001", "resolved": True, "cause": "protodeboronation"})
    out = {(r, d) for r, d, _ in kg.load_graph(vault).out["exp:2026-08-01_a-001"]}
    assert ("CONFIRMED_CAUSE", "lg:protodeboronation") in out
    c.put("/api/records/2026-08-01_a-001", json={"equipment": ["flow reactor"]})
    out = {(r, d) for r, d, _ in kg.load_graph(vault).out["exp:2026-08-01_a-001"]}
    assert ("USES_EQUIPMENT", "lg:flow_reactor") in out


def test_kg_rebuild_endpoint(client):
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_a-001", date="2026-08-01"), "원문", "s")
    out = c.post("/api/kg/rebuild").json()
    assert out["records"] == 1 and out["claims"] == 0


def test_flow_runs_list_and_events_after(client):
    from horcrux import trace
    c, vault = client
    rid = trace.start(vault, "ask", "질문 하나")
    trace.event(vault, rid, "p3.link", "ok", "연결")
    trace.event(vault, rid, "p3.answer", "ok", "답변")
    runs = c.get("/api/flow/runs").json()["runs"]
    assert runs[0]["run_id"] == rid and runs[0]["n_events"] == 2 and runs[0]["kind"] == "ask"
    got = c.get(f"/api/flow/runs/{rid}?after=1").json()
    assert got["run"]["status"] == "running" and [e["stage"] for e in got["events"]] == ["p3.answer"]
    assert c.get("/api/flow/runs/없는-실행").status_code == 404


def test_feedback_run_goes_straight_to_graph(client):
    from horcrux import trace
    c, vault = client
    save_record(vault, ExperimentRecord(id="2026-08-01_a-001", date="2026-08-01"), "원문", "s")
    c.post("/api/feedback", json={"record_id": "2026-08-01_a-001", "resolved": True, "cause": "protodeboronation"})
    run = next(r for r in trace.list_runs(vault) if r["kind"] == "feedback")
    stages = [e["stage"] for e in trace.get_run(vault, run["run_id"])["events"]]
    assert stages == ["fb.feedback", "p2.store"]   # 워크플로 뷰의 "피드백 → 지식 그래프" 되먹임 선

