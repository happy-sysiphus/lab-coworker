import sys

import pytest
import yaml

from horcrux import cli


def test_log_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    called = {}
    monkeypatch.setattr(cli, "run_log", lambda cfg: called.setdefault("ok", True))
    cli.main(["log"])
    assert called.get("ok")


def test_unknown_command_exits():
    with pytest.raises(SystemExit):
        cli.main(["nope"])


def test_log_chains_absorb(tmp_path, monkeypatch):
    import horcrux.absorb as absorb_mod

    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    monkeypatch.setattr(cli, "run_log", lambda cfg: tmp_path / "x.md")
    called = {}
    monkeypatch.setattr(absorb_mod, "run_absorb", lambda cfg: called.setdefault("n", 2))
    cli.main(["log"])
    assert called.get("n") == 2


def test_cli_serve_missing_uvicorn_exits_clean(monkeypatch, capsys):
    # fastapi는 있고 uvicorn만 없는 상황(dev extra 설치) 재현 — run_serve 호출이
    # try 밖에 있으면 여기서 트레이스백으로 죽는다 (79c76be 회귀).
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    from horcrux.cli import main
    with pytest.raises(SystemExit) as ei:
        main(["serve"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "uvicorn" in err
    assert "pip install -e" in err   # 무관한 PyPI horcrux 패키지를 가리키지 않아야 함


def test_cli_init_writes_config(monkeypatch, isolated_config):
    answers = iter(["C:/lab/vault", "gemini", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from horcrux.cli import main
    main(["init"])
    data = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert data["vault"] == "C:/lab/vault"
    assert data["provider"] == "gemini"
    assert data["model"] is None          # 빈 입력 + 기존값 없음 = None


def test_cli_init_keeps_existing_on_empty(monkeypatch, isolated_config):
    isolated_config.write_text(yaml.safe_dump({
        "vault": "C:/old", "provider": "codex", "model": "o3",
    }, allow_unicode=True), encoding="utf-8")
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from horcrux.cli import main
    main(["init"])
    data = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert data == {"vault": "C:/old", "provider": "codex", "model": "o3"}


def test_cli_kg_rebuild_and_status(tmp_path, monkeypatch, capsys):
    from horcrux.records import ExperimentRecord, save_record
    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    save_record(tmp_path, ExperimentRecord(id="2026-09-29_a-001", date="2026-09-29",
                                           equipment=["flow reactor", "FR-01"]), "원문", "정리")
    main = cli.main
    main(["kg", "rebuild"])
    assert "레코드 1건" in capsys.readouterr().out
    main(["kg", "status"])
    assert "미연결 표기 1개" in capsys.readouterr().out


def test_log_syncs_graph_after_save(tmp_path, monkeypatch):
    import horcrux.absorb as absorb_mod
    from horcrux import kg
    from horcrux.records import ExperimentRecord, save_record
    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    path = save_record(tmp_path, ExperimentRecord(id="2026-09-29_a-001", date="2026-09-29",
                                                  equipment=["flow reactor"]), "원문", "정리")
    monkeypatch.setattr(cli, "run_log", lambda cfg: path)
    monkeypatch.setattr(absorb_mod, "run_absorb", lambda cfg: 0)
    cli.main(["log"])
    assert ("USES_EQUIPMENT", "lg:flow_reactor") in {
        (r, d) for r, d, _ in kg.load_graph(tmp_path).out["exp:2026-09-29_a-001"]}
