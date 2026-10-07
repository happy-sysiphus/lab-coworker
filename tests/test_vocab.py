import yaml

from horcrux.vocab import canon, ensure_common, load_vocabulary


def _overlay(vault, data):
    p = vault / "ontology" / "overlay.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_canon_rules():
    assert canon("FR-01") == canon("FR 1호기") == "fr1"
    assert canon("FR-01") != canon("FR-02")
    assert canon("residence_time") == canon("Residence Time")
    assert canon("트라이메틸알루미늄") == canon("트리메틸알루미늄")


def test_ensure_common_copies_upgrades_and_repairs(tmp_path):
    dst = ensure_common(tmp_path)
    assert dst.exists()
    dst.write_text(yaml.safe_dump({"version": "0.0.1", "terms": []}), encoding="utf-8")
    ensure_common(tmp_path)
    assert yaml.safe_load(dst.read_text(encoding="utf-8"))["version"] != "0.0.1"
    dst.write_text("terms: [unclosed", encoding="utf-8")
    ensure_common(tmp_path)
    assert yaml.safe_load(dst.read_text(encoding="utf-8"))["profile_id"] == "labgene-common"


def test_link_by_label_synonym_and_kind_blocking(tmp_path):
    v = load_vocabulary(tmp_path)
    assert v.link("parameter", "residence_time") == ("linked", ["lg:residence_time"])
    assert v.link("material", "THF") == ("linked", ["CHEBI:26911"])
    assert v.link("parameter", "THF") == ("unlinked", [])
    assert v.link("metric", "수율") == ("unlinked", [])   # label_ko는 연결에 쓰지 않는다


def test_overlay_terms_and_aliases(tmp_path):
    _overlay(tmp_path, {
        "terms": [{"id": "lab:fr-01", "label": "FR-01", "kind": "equipment", "parent": "lg:flow_reactor"}],
        "aliases": [{"surface": "수율", "term_id": "lg:reaction_yield", "verdict": "positive"},
                    {"surface": "loading", "term_id": "lg:catalyst_loading", "verdict": "negative"}]})
    v = load_vocabulary(tmp_path)
    assert v.link("metric", "수율") == ("linked", ["lg:reaction_yield"])
    assert v.link("parameter", "loading") == ("unlinked", [])
    assert v.link("equipment", "FR 1호기") == ("linked", ["lab:fr-01"])
    assert v.link("equipment", "FR-02") == ("unlinked", [])


def test_broken_overlay_is_skipped_with_warning(tmp_path):
    p = tmp_path / "ontology" / "overlay.yaml"
    p.parent.mkdir(parents=True)
    p.write_text("terms: [unclosed", encoding="utf-8")
    v = load_vocabulary(tmp_path)
    assert v.warnings and "overlay.yaml" in v.warnings[0]
    assert v.link("material", "THF")[0] == "linked"


def test_same_uses_canon_and_aliases(tmp_path):
    _overlay(tmp_path, {"aliases": [
        {"surface": "보론산 분해", "term_id": "lg:protodeboronation", "verdict": "positive"}]})
    v = load_vocabulary(tmp_path)
    assert v.same("cause", "전구체  열화", "전구체 열화")
    assert v.same("cause", "보론산 분해", "protodeboronation")
    assert not v.same("cause", "퍼지 부족", "protodeboronation")


def test_find_mentions_boundaries(tmp_path):
    _overlay(tmp_path, {"aliases": [
        {"surface": "수율", "term_id": "lg:reaction_yield", "verdict": "positive"}]})
    v = load_vocabulary(tmp_path)
    found = [tid for *_, tid in v.find_mentions("XPhos 쓰는 flow reactor에서 수율이 낮고 baseline이 흔들림")]
    assert found == ["lg:xphos", "lg:flow_reactor", "lg:reaction_yield"]   # baseline 안의 base는 잡지 않는다


def test_find_mentions_skips_parameters_by_default(tmp_path):
    v = load_vocabulary(tmp_path)
    assert v.find_mentions("reaction time and temperature") == []
    assert [t for *_, t in v.find_mentions("temperature", kinds=("parameter",))] == ["quantitykind:Temperature"]


def test_quantities_and_compare(tmp_path):
    v = load_vocabulary(tmp_path)
    q = v.find_quantities("온도 80도에서 체류 시간 5분, 촉매 2 mol%, 10 sccm, Pd G3")
    assert [(x["lo"], x["unit"]) for x in q] == [
        (80.0, "unit:DEG_C"), (5.0, "unit:MIN"), (2.0, "lg:unit_mol_percent")]
    assert v.parse_value("60~110 °C") == {"lo": 60.0, "hi": 110.0, "unit": "unit:DEG_C"}
    assert v.parse_value("5-10 min") == {"lo": 5.0, "hi": 10.0, "unit": "unit:MIN"}
    assert v.compare({"lo": 5, "hi": 5, "unit": "unit:MIN"}, {"lo": 60, "hi": 600, "unit": "unit:SEC"}) == "inside"
    assert v.compare({"lo": 120, "hi": 120, "unit": "unit:DEG_C"},
                     {"lo": 30, "hi": 110, "unit": "unit:DEG_C"}) == "outside"
    assert v.compare({"lo": 2, "hi": 2, "unit": "lg:unit_mol_percent"},
                     {"lo": 30, "hi": 110, "unit": "unit:DEG_C"}) == "incomparable"
    assert v.unit_symbol("unit:DEG_C") == "°C"


def test_predicate_synonyms(tmp_path):
    v = load_vocabulary(tmp_path)
    assert v.predicate("raises")["name"] == "increases"
    assert v.predicate("competes with")["name"] == "competes_with"
    assert v.predicate("explodes") is None


def test_structurally_broken_overlay_entries_are_skipped(tmp_path):
    _overlay(tmp_path, {
        "terms": [{"id": "lab:fr-01", "label": "FR-01", "kind": "equipment", "synonyms": [1, None, "첫 반응기"]},
                  {"id": "lab:x", "label": None, "kind": "equipment"}],
        "overrides": [{"term_id": "CHEBI:26911", "synonyms_add": "thf2"}],
        "aliases": [{"surface": None, "term_id": "lg:reaction_yield", "verdict": "positive"},
                    {"surface": "수율", "term_id": ["bad"], "verdict": "positive"}]})
    v = load_vocabulary(tmp_path)
    assert v.link("equipment", "첫 반응기") == ("linked", ["lab:fr-01"])
    assert v.link("material", "thf2") == ("linked", ["CHEBI:26911"])   # 문자열 하나는 동의어 하나로 받는다
    assert [t for *_, t in v.find_mentions("the flow reactor h")] == ["lg:flow_reactor"]   # 한 글자 표면형이 없다
    assert v.link("metric", "None") == ("unlinked", [])
    assert any("lab:x" in w for w in v.warnings)
