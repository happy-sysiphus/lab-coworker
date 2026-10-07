from horcrux import diagnose as dg
from horcrux.config import Config


def _fake(evidence, warnings=()):
    return lambda cfg, text, run_id=None, web_ok=None: {"answer": "답변", "evidence": evidence, "warnings": list(warnings)}


def test_records_answer_has_no_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "research", _fake("records"))
    assert dg.diagnose(Config(vault=tmp_path), "질문") == "답변"


def test_none_and_knowledge_banners(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "research", _fake("none"))
    assert dg.diagnose(Config(vault=tmp_path), "질문").startswith("⚠")
    monkeypatch.setattr(dg, "research", _fake("knowledge", ["근거에 없는 수치 5"]))
    out = dg.diagnose(Config(vault=tmp_path), "질문")
    assert "연구실 지식" in out and "검증 경고: 근거에 없는 수치 5" in out


def test_mode_note_names_unknown_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "research", lambda cfg, text, run_id=None, web_ok=None: {
        "answer": "답변", "evidence": "records", "warnings": [], "mode": "partial", "unknown": ["SPhos Pd G4"]})
    assert dg.diagnose(Config(vault=tmp_path), "질문") == "ℹ 일부 대상(SPhos Pd G4)은 연구실 지식에 없습니다.\n\n답변"


def test_diagnose_data_passes_run_id(tmp_path, monkeypatch):
    seen = {}

    def fake(cfg, text, run_id=None, web_ok=None):
        seen["run_id"] = run_id
        return {"answer": "a", "evidence": "none", "warnings": []}

    monkeypatch.setattr(dg, "research", fake)
    dg.diagnose_data(Config(vault=tmp_path), "질문", run_id="r1")
    assert seen["run_id"] == "r1"
