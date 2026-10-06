import pytest

from horcrux import cli
from horcrux.config import load_vault_config
from horcrux.vocab import NOTICE, load_vocabulary, select_domains


def test_select_domains_writes_config_and_notice(tmp_path):
    (tmp_path / "config.yaml").write_text("required_parameters: [온도]\n", encoding="utf-8")
    assert select_domains(tmp_path, ["materials-process-chem"]) is None
    vcfg = load_vault_config(tmp_path)
    assert vcfg.domains == ["materials-process-chem"]
    assert vcfg.required_parameters == ["온도"]          # 기존 설정은 보존
    assert select_domains(tmp_path, ["life-science"]) == NOTICE
    assert select_domains(tmp_path, ["materials-process-chem", "life-science"]) == NOTICE


def test_select_domains_keeps_hand_written_lines(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("# 게이트 설정\nrequired_parameters: [온도]\ndomains:\n  - life-science\n", encoding="utf-8")
    select_domains(tmp_path, ["materials-process-chem"])
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# 게이트 설정\nrequired_parameters: [온도]\n")
    assert text.count("domains:") == 1
    assert load_vault_config(tmp_path).domains == ["materials-process-chem"]


def test_select_unknown_domain_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        select_domains(tmp_path, ["nope"])
    with pytest.raises(ValueError):
        select_domains(tmp_path, [])
    assert not (tmp_path / "config.yaml").exists()


def test_vocabulary_ignores_selection(tmp_path):
    select_domains(tmp_path, ["life-science"])
    assert load_vocabulary(tmp_path).link("material", "THF")[0] == "linked"


def test_cli_ontology_use_and_domains(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    cli.main(["ontology", "use", "materials-process-chem", "life-science"])
    assert NOTICE in capsys.readouterr().out
    cli.main(["ontology", "domains"])
    out = capsys.readouterr().out
    assert "* materials-process-chem" in out and "* life-science" in out
    assert "suzuki-flow-v1" in out


def test_cli_ontology_use_unknown_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HORCRUX_VAULT", str(tmp_path))
    with pytest.raises(SystemExit):
        cli.main(["ontology", "use", "nope"])
    assert "알 수 없는 도메인" in capsys.readouterr().err
