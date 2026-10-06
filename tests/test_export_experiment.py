import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from horcrux import kg
from horcrux.config import load_vault_config
from horcrux.records import list_records, load_record

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_experiment.py"


def _module():
    spec = importlib.util.spec_from_file_location("export_experiment", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _labgene(root: Path) -> Path:
    """본실험 원장의 최소 사본 — 조건별 에피소드 1개, 상담 1건, 실험 2건(두 번째만 성공)."""
    (root / "configs" / "tasks").mkdir(parents=True)
    (root / "configs" / "tasks" / "suzuki_flow_01.yaml").write_text(yaml.safe_dump({
        "task_id": "suzuki_flow_01",
        "title": "Suzuki-Miyaura coupling in flow: 3-bromoquinoline with 3,5-dimethylisoxazole-4-boronic acid pinacol ester",
        "problem": "... using DBU (2.0 equiv) in THF/water 5:1 ...",
        "success": [{"metric": "yield", "target": 78.67}, {"metric": "ton", "target": 65.56}]}), encoding="utf-8")
    run = root / "artifacts" / "pilot-02"
    run.mkdir(parents=True)
    con = sqlite3.connect(run / "ledger.sqlite")
    con.executescript("""
        create table episodes(episode_id, condition, task_id, episode_order);
        create table actions(action_id, episode_id, seq, kind, payload_json);
        create table observations(action_id, json);
        create table cost_events(id, json);
    """)
    con.execute("insert into episodes values('product-r1-e001','product','suzuki_flow_01',1)")
    con.execute("insert into actions values('product-r1-e001:a001','product-r1-e001',1,'consult',?)",
                (json.dumps({"args": {"question": "어떤 촉매?"}}),))
    for i, (cat, temp, ok, y) in enumerate([("SPhos Pd G3", 100.0, False, 24.3), ("XPhos Pd G3", 110.0, True, 81.2)], 2):
        aid = f"product-r1-e001:a00{i}"
        con.execute("insert into actions values(?,?,?,?,?)", (aid, "product-r1-e001", i, "run_experiment",
                    json.dumps({"args": {"hypothesis": f"{cat} 가설", "parameters": {}}})))
        con.execute("insert into observations values(?,?)", (aid, json.dumps({
            "parameters": {"catalyst": cat, "residence_time": 360.0, "temperature": temp, "catalyst_loading": 1.2},
            "results": {"yield": y, "ton": y / 1.2}, "meets_success_criteria": ok})))
    con.commit()
    con.close()
    return root


def test_write_vault_converts_experiments_deterministically(tmp_path):
    mod = _module()
    run = mod.load_run(_labgene(tmp_path / "labgene"), "pilot-02")
    vault = tmp_path / "demo"
    ids = mod.write_vault(run, vault, "2026-09-29", "labgene pilot-02")
    assert ids == ["2026-09-29_suzuki-miyaura-coupling-001", "2026-09-29_suzuki-miyaura-coupling-002"]
    first, body = load_record(list_records(vault)[0])
    second, _ = load_record(list_records(vault)[1])
    assert first.title == "SPhos Pd G3 100°C 360s"
    assert first.materials == ["SPhos Pd G3", "3-bromoquinoline",
                               "3,5-dimethylisoxazole-4-boronic acid pinacol ester", "DBU", "THF", "water"]
    assert [(p.name, p.value) for p in first.parameters] == [
        ("temperature", "100 °C"), ("residence time", "360 s"), ("catalyst loading", "1.2 mol%"),
        ("catalyst", "SPhos Pd G3")]
    assert first.symptom.category == "low_value" and "78.67" in first.symptom.description
    assert (second.symptom.category, second.followup_of) == ("none", first.id)
    assert "출처: labgene pilot-02 product-r1-e001:a002" in body
    assert load_vault_config(vault).domains == ["materials-process-chem"]
    with pytest.raises(SystemExit):
        mod.write_vault(run, vault, "2026-09-29", "labgene pilot-02")   # 빈 볼트가 아니면 거부


def test_exported_records_link_to_experiment_vocabulary(tmp_path):
    mod = _module()
    vault = tmp_path / "demo"
    mod.write_vault(mod.load_run(_labgene(tmp_path / "labgene"), "pilot-02"), vault, "2026-09-29", "x")
    kg.rebuild(vault)
    out = {(r, d) for r, d, _ in kg.load_graph(vault).out["exp:2026-09-29_suzuki-miyaura-coupling-002"]}
    assert {("OF_TECHNIQUE", "RXNO:0000140"), ("USES_EQUIPMENT", "lg:flow_reactor"),
            ("USES_MATERIAL", "lg:3_bromoquinoline"), ("USES_MATERIAL", "CHEBI:26911"),
            ("HAS_PARAMETER", "lg:residence_time"), ("HAS_PARAMETER", "lg:catalyst_loading"),
            ("HAS_PARAMETER", "tmp:parameter:catalyst"),
            ("FOLLOWUP_OF", "exp:2026-09-29_suzuki-miyaura-coupling-001")} <= out
