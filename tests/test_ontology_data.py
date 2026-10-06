from collections import Counter
from pathlib import Path

import yaml

ONT = Path(__file__).resolve().parents[1] / "src" / "horcrux" / "ontology"
FIXTURE = Path(__file__).parent / "fixtures" / "suzuki_flow.yaml"   # labgene 실험 프로파일 사본


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_common_preserves_experiment_profile():
    src = {t["id"]: t for t in _load(FIXTURE)["terms"]}
    common = _load(ONT / "common.yaml")
    conv = {x["id"]: x for sec in ("terms", "units", "predicates") for x in common[sec]}
    assert set(conv) - set(src) == {"lg:spec_range"}
    assert set(src) <= set(conv)
    for tid, t in src.items():
        c = conv[tid]
        assert c["label"] == t["label"], tid
        assert set(t.get("synonyms", [])) <= set(c["synonyms"]), tid
        assert (c["source"], c["verified"]) == (t["source"], t["verified"]), tid
    assert common["source_profile"] == "suzuki-flow-v1"


def test_common_kinds_units_and_predicates():
    common = _load(ONT / "common.yaml")
    assert Counter(t["kind"] for t in common["terms"]) == {
        "material": 34, "technique": 5, "parameter": 4, "metric": 3, "cause": 2, "equipment": 1}
    ids = {t["id"] for t in common["terms"]}
    assert all(t["parent"] in ids for t in common["terms"] if t["parent"])
    assert all(t["label_ko"] for t in common["terms"])
    for u in common["units"]:
        assert u["symbol"] and u["dimension"] and isinstance(u["factor"], float)
    assert sorted(p["name"] for p in common["predicates"]) == sorted(
        ["increases", "decreases", "requires", "promotes", "inhibits", "competes_with", "spec_range"])
    assert common["claims"] == []


def test_domains_registry_has_one_active_domain():
    reg = _load(ONT / "domains.yaml")
    active = [d for d in reg["domains"] if d["status"] == "active"]
    assert [d["id"] for d in active] == ["materials-process-chem"]
    assert active[0]["vocabulary"] == "suzuki-flow-v1"
    assert 4 <= len(reg["domains"]) - 1 <= 6
    for d in reg["domains"]:
        assert d["status"] in ("active", "showcase")
        for b in d["bundle"]:
            assert b["ontology"] in reg["ontologies"], b
