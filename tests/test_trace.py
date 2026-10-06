from horcrux import trace


def test_run_lifecycle(tmp_path):
    rid = trace.start(tmp_path, "ask", "질문")
    trace.event(tmp_path, rid, "p3.link", "ok", "연결 2개", {"terms": ["a"]}, 3)
    trace.event(tmp_path, rid, "p3.answer", "ok", "답변")
    trace.finish(tmp_path, rid)
    got = trace.get_run(tmp_path, rid)
    assert got["run"]["status"] == "done"
    assert [e["stage"] for e in got["events"]] == ["p3.link", "p3.answer"]
    assert got["events"][0]["data"] == {"terms": ["a"]} and got["events"][0]["ms"] == 3
    assert [e["seq"] for e in trace.get_run(tmp_path, rid, after=1)["events"]] == [2]
    assert trace.get_run(tmp_path, "없음") is None


def test_client_run_id_and_large_data(tmp_path):
    rid = trace.start(tmp_path, "ask", "q", run_id="client-1")
    assert rid == "client-1"
    trace.event(tmp_path, rid, "p3.search", "ok", "x", {"blob": "가" * 5000})
    assert trace.get_run(tmp_path, rid)["events"][0]["data"] == {"truncated": True}


def test_prune_keeps_latest_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "MAX_RUNS", 3)
    ids = [trace.start(tmp_path, "ask", f"q{i}") for i in range(5)]
    trace.event(tmp_path, ids[0], "p3.link", "ok", "지워진 실행")
    assert [r["run_id"] for r in trace.list_runs(tmp_path)] == ids[::-1][:3]


def test_trace_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(trace, "db", boom)
    rid = trace.start(tmp_path, "ask", "q")
    trace.event(tmp_path, rid, "p3.link", "ok", "x")
    trace.finish(tmp_path, rid)
    assert rid
