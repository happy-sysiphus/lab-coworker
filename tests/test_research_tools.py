from horcrux import kg
from horcrux import research_agent as ra
from horcrux.vocab import load_vocabulary


def _ctx(vault):
    return load_vocabulary(vault), kg.load_graph(vault)


def test_link_question_terms_records_quantities_unlinked(kg_vault):
    voc, g = _ctx(kg_vault)
    q = "XPhos Pd G3로 flow reactor 100도에서 수율이 낮아요. 2026-09-01_a-001 참고. K3PO4 써도 되나?"
    link = ra.link_question(voc, g, q)
    assert {"lg:xphos", "lg:flow_reactor", "tmp:material:xphospdg3"} <= set(link.terms)
    assert link.records == ["exp:2026-09-01_a-001"]
    assert [(x["lo"], x["unit"]) for x in link.quantities] == [(100.0, "unit:DEG_C")]
    assert link.unlinked == ["K3PO4"]


def test_link_question_flags_unknown_model_name_and_skips_stopwords(kg_vault):
    voc, g = _ctx(kg_vault)
    link = ra.link_question(voc, g, "Can we use SPhos Pd G4 with the flow reactor?")
    assert link.unlinked == ["G4"]


def test_cases_rank_by_shared_terms_symptom_and_confirmation(kg_vault):
    _, g = _ctx(kg_vault)
    ranked = ra.tool_cases(g, ["lg:flow_reactor", "tmp:material:xphospdg3"], symptom="low_value")
    assert ranked == ["exp:2026-09-01_a-001", "exp:2026-09-02_a-002", "exp:2026-09-03_b-001"]


def test_causes_count_confirmed_and_rejected(kg_vault):
    _, g = _ctx(kg_vault)
    c = next(x for x in ra.tool_causes(g, ["exp:2026-09-01_a-001"], []) if x["id"] == "lg:protodeboronation")
    assert (c["confirmed"], c["rejected"], c["records"]) == (1, 1, ["2026-09-01_a-001", "2026-09-03_b-001"])


def test_relations_include_two_hop_path(kg_vault):
    voc, _ = _ctx(kg_vault)
    items = ra.tool_relations(voc, ["quantitykind:Temperature"])
    assert sorted(i["kind"] for i in items) == ["clm", "path"]
    path = next(i for i in items if i["kind"] == "path")
    assert [c["id"] for c in path["claims"]] == ["c-1", "c-2"]
    assert not ra.compatible({"range": {"unit:DEG_C": [80, 120]}}, {"range": {"unit:DEG_C": [10, 50]}})


def test_specs_compare_question_and_case_values(kg_vault):
    voc, g = _ctx(kg_vault)
    specs = ra.tool_specs(voc, g, ["quantitykind:Temperature"],
                          [{"lo": 120.0, "hi": 120.0, "unit": "unit:DEG_C"}], ["exp:2026-09-01_a-001"])
    assert specs[0]["claim"]["id"] == "s-1"
    assert [(c["who"], c["value"], c["result"]) for c in specs[0]["checks"]] == [
        ("질문", "120 °C", "outside"), ("2026-09-01_a-001", "100 °C", "inside")]


def test_wiki_and_followups(kg_vault):
    voc, g = _ctx(kg_vault)
    wiki = ra.tool_wiki(kg_vault, voc, g, ["lg:flow_reactor"], ["exp:2026-09-01_a-001"])
    assert [w["id"] for w in wiki] == ["equipment/flow-reactor", "failure-modes/suzuki-miyaura-coupling-값낮음"]
    fu = ra.tool_followups(g, ["exp:2026-09-01_a-001"])
    assert fu == [{"record_id": "2026-09-02_a-002", "base_id": "2026-09-01_a-001",
                   "delta": {"temperature": ["100 °C", "80 °C"]}}]


def test_collect_orders_cards_and_respects_budget(kg_vault, monkeypatch):
    voc, g = _ctx(kg_vault)
    link = ra.link_question(voc, g, "flow reactor temperature 120도에서 XPhos Pd G3 수율이 낮아요")
    cards, hits = ra.collect(kg_vault, voc, g, link, ra.INITIAL_TOOLS)
    ids = [c["id"] for c in cards]
    assert ids[0] == "spec:s-1" and ids[1].startswith("rec:")
    assert {"cause:lg:protodeboronation", "clm:c-1", "wiki:equipment/flow-reactor",
            "fu:2026-09-02_a-002"} <= set(ids)
    assert "120 °C → 범위 밖" in cards[0]["text"]
    assert hits["cases"] == 3
    monkeypatch.setattr(ra, "CARD_LIMIT", 3)
    assert [c["kind"] for c in ra.collect(kg_vault, voc, g, link, ra.INITIAL_TOOLS)[0]] == ["spec", "rec", "rec"]


def _passage(vault, cid, text, page=3):
    with kg.db(vault) as conn:
        conn.execute("insert or ignore into doc(doc_id, kind, title, source, sha256, pages, page_range, status, error, "
                     "created_at) values('man-x','manual','Flow manual','x.pdf','h',9,'all','done',null,0)")
        conn.execute("insert into chunk(chunk_id, doc_id, page, seq, text, status, rounds, error) values(?,?,?,?,?,?,?,?)",
                     (cid, "man-x", page, 1, text, "done", 0, None))
    kg.rebuild(vault)


def test_passages_need_two_shared_terms_when_question_links_two(kg_vault):
    _passage(kg_vault, "man-x#1", "In the flow reactor, protodeboronation grows with temperature.")
    _passage(kg_vault, "man-x#2", "Clean the flow reactor weekly.", page=4)
    voc, g = _ctx(kg_vault)
    two = ra.tool_passages(kg_vault, g, ["lg:flow_reactor", "lg:protodeboronation"])
    assert [p["chunk_id"] for p in two] == ["man-x#1"] and two[0]["title"] == "Flow manual" and two[0]["page"] == 3
    one = ra.tool_passages(kg_vault, g, ["lg:flow_reactor"])
    assert {p["chunk_id"] for p in one} == {"man-x#1", "man-x#2"}
    link = ra.link_question(voc, g, "flow reactor에서 protodeboronation이 늘어요")
    cards, hits = ra.collect(kg_vault, voc, g, link, ra.INITIAL_TOOLS)
    assert hits["passages"] == 1 and any(c["id"] == "psg:man-x#1" for c in cards)


def test_query_stage_never_reads_vectors_or_fulltext_index():
    import inspect
    src = inspect.getsource(ra)
    assert "chunk_fts" not in src and "load_vecs" not in src and "embed(" not in src

