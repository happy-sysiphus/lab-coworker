import os

import yaml

from horcrux import kg
from horcrux.records import (
    ExperimentRecord, Parameter, Reference, Resolution, SuspectedCause, Symptom, record_path, save_record,
)


def _save(vault, rid, raw="원문", **kw):
    rec = ExperimentRecord(id=rid, date="2026-09-29", **kw)
    save_record(vault, rec, raw, "정리")
    return rec


def _edges(vault, rid):
    with kg.db(vault) as conn:
        return {(r["rel"], r["dst"]) for r in conn.execute(
            "select rel, dst from edge where source_kind='record' and source_id=?", (rid,))}


def test_sync_links_terms_and_makes_temp_nodes(tmp_path):
    _save(tmp_path, "r1", equipment=["flow reactor", "FR-01"], materials=["XPhos Pd G3", "THF"],
          experiment_type="Suzuki-Miyaura coupling",
          parameters=[Parameter(name="residence_time", value="360 s"), Parameter(name="촉매 종류", value="XPhos")],
          symptom=Symptom(category="low_value", description="수율 낮음"),
          suspected_causes=[SuspectedCause(cause="protodeboronation")])
    out = kg.rebuild(tmp_path)
    assert out["records"] == 1 and out["temp"] == 3
    e = _edges(tmp_path, "r1")
    assert {("USES_EQUIPMENT", "lg:flow_reactor"), ("USES_EQUIPMENT", "tmp:equipment:fr1"),
            ("USES_MATERIAL", "CHEBI:26911"), ("USES_MATERIAL", "tmp:material:xphospdg3"),
            ("OF_TECHNIQUE", "RXNO:0000140"), ("HAS_PARAMETER", "lg:residence_time"),
            ("EXHIBITS", "sym:low_value"), ("SUSPECTS", "lg:protodeboronation")} <= e
    g = kg.load_graph(tmp_path)
    hp = next(p for rel, dst, p in g.out["exp:r1"] if dst == "lg:residence_time")
    assert (hp["lo"], hp["unit"], hp["value"]) == (360.0, "unit:SEC", "360 s")
    assert g.nodes["tmp:equipment:fr1"]["status"] == "temp"
    assert g.nodes["exp:r1"]["props"]["symptom"] == "low_value"


def test_long_cause_gets_truncated_temp_label(tmp_path):
    long = "보론산이 반응 중에 분해돼 수율이 떨어진 것으로 보인다. 다음엔 온도를 낮춰 보고 체류 시간도 줄여 보자"
    _save(tmp_path, "r1", resolution=Resolution(resolved=True, actual_cause=long))
    kg.rebuild(tmp_path)
    g = kg.load_graph(tmp_path)
    cid = next(dst for rel, dst, _ in g.out["exp:r1"] if rel == "CONFIRMED_CAUSE")
    assert cid.startswith("tmp:cause:")
    assert g.nodes[cid]["label"].endswith("…") and g.nodes[cid]["props"]["full"] == long


def test_mentions_followup_delta_and_references(tmp_path):
    _save(tmp_path, "r1", raw="XPhos로 돌렸다", parameters=[Parameter(name="temperature", value="100 °C")])
    _save(tmp_path, "r2", raw="온도만 낮췄다", followup_of="r1",
          parameters=[Parameter(name="temperature", value="80 °C")],
          references=[Reference(type="record", record_id="r1")])
    kg.rebuild(tmp_path)
    assert ("MENTIONS", "lg:xphos") in _edges(tmp_path, "r1")
    g = kg.load_graph(tmp_path)
    fu = next(p for rel, dst, p in g.out["exp:r2"] if rel == "FOLLOWUP_OF")
    assert fu["delta"] == {"temperature": ["100 °C", "80 °C"]}
    assert ("REFERENCES", "exp:r1") in _edges(tmp_path, "r2")


def test_needs_review_and_corrupt_records_are_skipped(tmp_path):
    _save(tmp_path, "r1", needs_review=True)
    record_path(tmp_path, "r2").write_text("---\n: [\n---\n본문", encoding="utf-8")
    out = kg.rebuild(tmp_path)
    assert (out["records"], out["skipped"]) == (0, 2)
    assert "exp:r1" not in kg.load_graph(tmp_path).nodes


def test_refresh_incremental_vocab_change_and_removal(tmp_path):
    _save(tmp_path, "r1", equipment=["FR-01"])
    assert kg.refresh(tmp_path)["mode"] == "rebuild"
    assert kg.refresh(tmp_path) == {"mode": "incremental", "changed": 0, "removed": 0, "records": 0}
    p = record_path(tmp_path, "r1")   # 옵시디언 손편집 흉내 — mtime이 바뀐 레코드만 다시 동기화
    p.write_text(p.read_text(encoding="utf-8").replace("FR-01", "FR-02"), encoding="utf-8")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    out = kg.refresh(tmp_path)
    assert (out["mode"], out["changed"]) == ("incremental", 1)
    assert ("USES_EQUIPMENT", "tmp:equipment:fr2") in _edges(tmp_path, "r1")
    overlay = tmp_path / "ontology" / "overlay.yaml"   # 어휘가 바뀌면 전부 다시 만든다
    overlay.write_text(yaml.safe_dump({"terms": [
        {"id": "lab:fr-02", "label": "FR-02", "kind": "equipment", "parent": "lg:flow_reactor"}]}), encoding="utf-8")
    assert kg.refresh(tmp_path)["mode"] == "rebuild"
    assert ("USES_EQUIPMENT", "lab:fr-02") in _edges(tmp_path, "r1")
    assert "tmp:equipment:fr2" not in kg.load_graph(tmp_path).nodes   # 고아 임시 노드 정리
    p.unlink()
    out = kg.refresh(tmp_path)
    assert out["removed"] == 1 and "exp:r1" not in kg.load_graph(tmp_path).nodes


def test_claim_edges_from_vault_claims(tmp_path):
    claims = tmp_path / "ontology" / "claims.yaml"
    claims.parent.mkdir(parents=True)
    claims.write_text(yaml.safe_dump({"claims": [
        {"id": "c-1", "subject": "quantitykind:Temperature", "predicate": "raises", "object": "lg:conversion"},
        {"id": "c-2", "subject": "없는:용어", "predicate": "increases", "object": "lg:conversion"}]}), encoding="utf-8")
    out = kg.rebuild(tmp_path)
    assert out["claims"] == 1
    g = kg.load_graph(tmp_path)
    assert ("increases", "lg:conversion") in {(r, d) for r, d, _ in g.out["quantitykind:Temperature"]}


def test_rebuild_twice_gives_same_graph(tmp_path):
    _save(tmp_path, "r1", equipment=["flow reactor", "FR-01"], materials=["XPhos Pd G3"],
          suspected_causes=[SuspectedCause(cause="protodeboronation")])
    _save(tmp_path, "r2", followup_of="r1", parameters=[Parameter(name="temperature", value="80 °C")])

    def snapshot():
        with kg.db(tmp_path) as conn:
            return (sorted(tuple(r) for r in conn.execute("select * from node")),
                    sorted(tuple(r) for r in conn.execute("select * from edge")))

    kg.rebuild(tmp_path)
    first = snapshot()
    kg.rebuild(tmp_path)
    assert snapshot() == first


def test_graph_data_for_ui(tmp_path):
    _save(tmp_path, "r1", equipment=["flow reactor"], actions_taken=["온도 낮춤"])
    data = kg.graph_data(tmp_path)
    ids = {n["id"] for n in data["nodes"]}
    assert {"exp:r1", "lg:flow_reactor"} <= ids
    assert not any(n["kind"] == "action" for n in data["nodes"])
    fr = next(n for n in data["nodes"] if n["id"] == "lg:flow_reactor")
    assert fr["rec_ids"] == ["r1"] and fr["status"] == "verified" and fr["label_ko"] == "흐름 반응기"
    assert all(link["source"] in ids and link["target"] in ids for link in data["links"])
    assert kg.status(tmp_path)["nodes"] >= 3
