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


def _labgene_replay(root: Path) -> Path:
    """재생용 원장 — 위 사본에 일반 LLM 에피소드(상담 1, 실험 1), 상담 기록, 조건별 지식 저장소를 더한다."""
    _labgene(root)
    run = root / "artifacts" / "pilot-02"
    con = sqlite3.connect(run / "ledger.sqlite")
    con.executescript("""
        alter table episodes add column outcome text default 'success';
        create table consult_exchanges(action_id, episode_id, json);
    """)
    con.execute("insert into consult_exchanges values(?,?,?)", ("product-r1-e001:a001", "product-r1-e001", json.dumps({
        "question": "Which precatalyst?", "response": {"answer": "Try XPhos Pd G3.",
                                                      "cited_source_ids": ["doc:pd_design#12"]}})))
    con.execute("insert into episodes values('baseline-r1-e001','baseline','suzuki_flow_01',1,'success')")
    con.execute("insert into actions values('baseline-r1-e001:a001','baseline-r1-e001',1,'consult','{}')")
    con.execute("insert into consult_exchanges values(?,?,?)", ("baseline-r1-e001:a001", "baseline-r1-e001", json.dumps({
        "question": "Initial condition?", "response": {"answer": "Try SPhos Pd G3.",
                                                       "cited_source_ids": ["initial:text"],
                                                       "cited_observation_ids": ["obs:product-r1-e001:a003"]}})))
    con.execute("insert into actions values(?,?,?,?,?)", ("baseline-r1-e001:a002", "baseline-r1-e001", 2,
                "run_experiment", json.dumps({"args": {"hypothesis": "SPhos works"}})))
    con.execute("insert into observations values(?,?)", ("baseline-r1-e001:a002", json.dumps({
        "scope": {"action_budget": 50},
        "parameters": {"catalyst": "SPhos Pd G3", "residence_time": 300.0, "temperature": 90.0, "catalyst_loading": 1.0},
        "results": {"yield": 80.04, "ton": 80.04}, "meets_success_criteria": True})))
    con.commit()
    con.close()
    for cond, rows in {"product": [("doc:pd_design", "source", "본문", {"title": "Pd precatalyst design"}),
                                   ("doc:pd_design#12", "chunk", "Precatalysts 6a-6n can be generated in situ. " * 20,
                                    {"header": "Pd precatalyst design | Results"})],
                       "baseline": [("initial:text", "source", "# General background\n\nPalladium coupling.",
                                     {"title": "General background (initial text)"})]}.items():
        d = run / "initial" / cond / "state"
        d.mkdir(parents=True)
        k = sqlite3.connect(d / "knowledge.sqlite")
        k.execute("create table artifacts(id, kind, text, meta)")
        k.executemany("insert into artifacts values(?,?,?,?)", [(i, kd, t, json.dumps(m)) for i, kd, t, m in rows])
        k.commit()
        k.close()
    return root


def test_replay_json_shape_counts_and_citations(tmp_path):
    mod = _module()
    rep = mod.load_replay(_labgene_replay(tmp_path / "labgene"), "pilot-02", label="본실험 v1", date="2026-09-29")
    assert (rep["run_id"], rep["label"], rep["date"], rep["action_budget"]) == ("pilot-02", "본실험 v1", "2026-09-29", 50)
    assert rep["tasks"] == [{"task_id": "suzuki_flow_01", "title": rep["tasks"][0]["title"],
                             "targets": {"yield": 78.67, "ton": 65.56}}]
    base, prod = rep["conditions"]["baseline"], rep["conditions"]["product"]
    assert (base["name"], prod["name"]) == ("일반 LLM", "LAB GENE")
    assert base["summary"] == {"success": 1, "actions": 2, "consults": 1, "experiments": 1}
    assert prod["summary"] == {"success": 1, "actions": 3, "consults": 1, "experiments": 2}
    ep = prod["episodes"][0]
    assert (ep["task_id"], ep["outcome"], ep["actions_to_success"]) == ("suzuki_flow_01", "success", 3)
    consult, first, second = ep["actions"]
    assert consult["kind"] == "consult" and consult["question"] == {"en": "Which precatalyst?", "ko": None}
    assert consult["answer"] == {"en": "Try XPhos Pd G3.", "ko": None}
    cite = consult["cited"][0]
    assert (cite["id"], cite["title"]) == ("doc:pd_design#12", "Pd precatalyst design")
    assert cite["excerpt"].startswith("Precatalysts 6a-6n") and len(cite["excerpt"]) <= 300
    assert (first["kind"], first["success"], second["success"]) == ("experiment", False, True)
    assert first["parameters"]["catalyst"] == "SPhos Pd G3" and first["note"]["en"] == "SPhos Pd G3 가설"
    assert second["results"] == {"yield": 81.2, "ton": 67.67}
    bcite = base["episodes"][0]["actions"][0]["cited"]
    assert [c["id"] for c in bcite] == ["initial:text", "obs:product-r1-e001:a003"]
    assert bcite[0]["title"] == "General background (initial text)"
    assert "XPhos Pd G3" in bcite[1]["excerpt"] and "81.2" in bcite[1]["excerpt"]


def test_translate_fills_korean_in_batches(tmp_path, monkeypatch):
    mod = _module()
    rep = mod.load_replay(_labgene_replay(tmp_path / "labgene"), "pilot-02", label="x", date="2026-09-29")
    calls = []

    def fake(cfg, system, user, schema):
        texts = json.loads(user.split("\n", 1)[1])
        calls.append(len(texts))
        return schema(items=[{"i": t["i"], "ko": "번역:" + t["en"]} for t in texts])

    monkeypatch.setattr(mod, "generate_parsed", fake)
    monkeypatch.setattr(mod, "BATCH", 3)
    mod.translate_replay(rep, cfg=None)
    consult = rep["conditions"]["product"]["episodes"][0]["actions"][0]
    assert consult["question"]["ko"] == "번역:Which precatalyst?"
    assert rep["conditions"]["baseline"]["episodes"][0]["actions"][1]["note"]["ko"] == "번역:SPhos works"
    assert sum(calls) == 7 and max(calls) <= 3   # 질문 2 + 답 2 + 메모 3
    mod.translate_replay(rep, cfg=None)          # 이미 번역된 글은 다시 보내지 않는다
    assert sum(calls) == 7
