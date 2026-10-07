import importlib.util
from pathlib import Path

import pytest
import yaml

from horcrux import kg, manual, review, trace
from horcrux import ontology_agent as oa
from horcrux.config import Config
from horcrux.records import ExperimentRecord, save_record

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_demo_manual.py"
P1 = ("The flow reactor temperature must stay between 30 and 110 °C. "
      "Higher temperature promotes protodeboronation of heteroaryl boronic acids. "
      "Suzuki-Miyaura coupling requires a base such as DBU.")
P2 = "SPhos Pd G4 is not recommended for this coupling. SPhos Pd G4 degrades quickly in THF."


def _pdf(pages):
    spec = importlib.util.spec_from_file_location("make_demo_manual", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pdf_bytes(pages, "Ops")


def _claim(s, p, o, quote, rng=None):
    return oa.XClaim(subject=s, predicate=p, object=o, quote=quote,
                     conditions=oa.XCond(range=rng or {}), spec_kind="allowed" if p == "spec_range" else None)


def _fake(monkeypatch, extractions, choices=None):
    calls = []
    ext = iter(extractions)

    def f(cfg, system, user, schema):
        calls.append(schema.__name__)
        if schema is oa.XOut:
            return next(ext)
        return choices or oa.Choices()

    monkeypatch.setattr(oa, "generate_parsed", f)
    monkeypatch.setattr(oa, "embed", lambda texts, kind: None)
    return calls


@pytest.fixture
def manual_vault(tmp_path):
    manual.add_manual(tmp_path, "ops.pdf", _pdf([["Operating limits", "", P1], ["Catalysts", "", P2]]))
    return tmp_path


FIRST = oa.XOut(chunks=[
    oa.XChunk(chunk_id="man-ops#1", claims=[
        _claim("temperature", "spec_range", "flow reactor", "The flow reactor temperature must stay between 30 and 110 °C.",
               {"°C": [30, 110]}),
        _claim("temperature", "promotes", "protodeboronation",
               "Higher temperature promotes protodeboronation of heteroaryl boronic acids."),
        _claim("Suzuki-Miyaura coupling", "requires", "base", "Suzuki-Miyaura coupling requires a base such as DBU."),
        _claim("temperature", "promotes", "protodeboronation", "Hot reactors make boronic acids fall apart."),
    ]),
    oa.XChunk(chunk_id="man-ops#2", claims=[
        _claim("SPhos Pd G4", "inhibits", "Suzuki-Miyaura coupling", "SPhos Pd G4 is not recommended for this coupling."),
    ], mentions=[oa.XMention(surface="SPhos Pd G4", kind="material")]),
])
FIXED = oa.XOut(chunks=[oa.XChunk(chunk_id="man-ops#1", claims=[
    _claim("temperature", "promotes", "protodeboronation",
           "Higher temperature promotes protodeboronation of heteroaryl boronic acids.")])])
NEW_G4 = oa.Choices(choices=[oa.Choice(surface="SPhos Pd G4", choice="NEW", new_term=oa.NewTerm(
    label="SPhos Pd G4", label_ko="SPhos 4세대 전촉매", kind="material", parent="lg:palladacycle_precatalyst"))])


def _built(manual_vault, monkeypatch):
    calls = _fake(monkeypatch, [FIRST, FIXED], NEW_G4)
    run = trace.start(manual_vault, "manual", "ops")
    stats = oa.build(Config(vault=manual_vault), run_id=run)
    return calls, stats, run


def test_build_gates_router_questions_and_auto_approval(manual_vault, monkeypatch):
    calls, stats, run = _built(manual_vault, monkeypatch)
    assert calls == ["XOut", "XOut", "Choices"]                         # 추출 + 재추출 1회 + 후보 선택 1회
    assert stats["auto"] == 1 and stats["errors"] == 0
    tabs = {q["tab"]: q for q in review.list_questions(manual_vault)}
    assert set(tabs) == {"spec", "relation", "new_term"}
    assert tabs["relation"]["count"] == 2                               # 재추출로 고친 같은 관계는 한 질문으로 묶인다
    assert tabs["spec"]["text"] == "'flow reactor'의 'temperature' 허용 범위가 30–110 °C인가요?"
    assert "SPhos Pd G4" in tabs["new_term"]["text"] and "palladacycle precatalyst" in tabs["new_term"]["text"]
    claims = yaml.safe_load((manual_vault / "ontology" / "claims.yaml").read_text(encoding="utf-8"))["claims"]
    assert [(c["predicate"], c["origin"]) for c in claims] == [("requires", "code")]
    with kg.db(manual_vault) as conn:
        assert conn.execute("select status from doc").fetchone()[0] == "done"
        assert conn.execute("select count(*) from item where status='waiting'").fetchone()[0] == 1
        assert {r[0] for r in conn.execute("select status from chunk")} == {"done"}
    stages = [e["stage"] for e in trace.get_run(manual_vault, run)["events"]]
    for s in ("p2.context", "p2.extract", "p2.normalize", "p2.evaluate", "p2.tool", "p2.research", "p2.candidates", "p2.store"):
        assert s in stages
    assert stages.count("p2.extract") == 2 and stages.count("p2.evaluate") == 2
    g = kg.load_graph(manual_vault)
    assert ("requires", "CHEBI:22695") in {(r, d) for r, d, _ in g.out["RXNO:0000140"]}


def test_approvals_write_yaml_merge_terms_and_release_waiting_claims(manual_vault, monkeypatch):
    _built(manual_vault, monkeypatch)
    cfg = Config(vault=manual_vault)
    tabs = {q["tab"]: q for q in review.list_questions(manual_vault)}
    out = review.answer(cfg, tabs["new_term"]["qid"], "accept")
    assert out["wrote"] == ["용어 lab:sphos-pd-g4"]
    overlay = yaml.safe_load((manual_vault / "ontology" / "overlay.yaml").read_text(encoding="utf-8"))
    assert overlay["terms"][0]["parent"] == "lg:palladacycle_precatalyst"
    relations = review.list_questions(manual_vault, "relation")
    assert any("SPhos Pd G4" in q["text"] for q in relations)            # 대기하던 클레임이 관계 질문이 됐다
    spec = review.answer(cfg, tabs["spec"]["qid"], "accept")
    assert [e["stage"] for e in trace.get_run(manual_vault, spec["run_id"])["events"]] == ["p2.approve", "p2.store", "p2.context"]
    g = kg.load_graph(manual_vault)
    assert ("spec_range", "lg:flow_reactor") in {(r, d) for r, d, _ in g.out["quantitykind:Temperature"]}
    with pytest.raises(review.AnswerError):
        review.answer(cfg, tabs["relation"]["qid"], "reject")              # 거절은 사유 코드가 필요하다
    assert review.answer(cfg, tabs["relation"]["qid"], "reject", reason_code="direction")["verdict"] == "rejected"


def test_spec_edit_and_auto_approval_revoke(manual_vault, monkeypatch):
    _built(manual_vault, monkeypatch)
    cfg = Config(vault=manual_vault)
    spec = review.list_questions(manual_vault, "spec")[0]
    review.answer(cfg, spec["qid"], "edit", edit={"lo": 40, "hi": 100, "unit": "°C", "spec_kind": "recommended"})
    claims = yaml.safe_load((manual_vault / "ontology" / "claims.yaml").read_text(encoding="utf-8"))["claims"]
    s = next(c for c in claims if c["predicate"] == "spec_range")
    assert s["conditions"]["range"] == {"unit:DEG_C": [40.0, 100.0]} and s["spec_kind"] == "recommended"
    auto = review.auto_items(manual_vault)[0]
    assert review.revoke(cfg, auto["item_id"])["removed"] is True
    claims = yaml.safe_load((manual_vault / "ontology" / "claims.yaml").read_text(encoding="utf-8"))["claims"]
    assert all(c["predicate"] != "requires" for c in claims)


def test_record_temp_nodes_become_term_questions_once(tmp_path, monkeypatch):
    for i in (1, 2):
        save_record(tmp_path, ExperimentRecord(id=f"2026-09-29_a-00{i}", date="2026-09-29",
                                               materials=["XPhos Pd G3"]), "원문", "정리")
    kg.rebuild(tmp_path)
    choice = oa.Choices(choices=[oa.Choice(surface="XPhos Pd G3", choice="NEW", new_term=oa.NewTerm(
        label="XPhos Pd G3", kind="material", parent="lg:precatalyst_g3"))])
    calls = _fake(monkeypatch, [], choice)
    cfg = Config(vault=tmp_path)
    assert oa.record_candidates(cfg) == 1 and oa.record_candidates(cfg) == 0   # 이미 물은 표기는 다시 묻지 않는다
    assert calls == ["Choices"]
    q = review.list_questions(tmp_path, "new_term")[0]
    assert q["count"] == 2 and q["context"]["source"]["records"] == ["2026-09-29_a-001", "2026-09-29_a-002"]
    review.answer(cfg, q["qid"], "accept")
    out = {(r, d) for r, d, _ in kg.load_graph(tmp_path).out["exp:2026-09-29_a-001"]}
    assert ("USES_MATERIAL", "lab:xphos-pd-g3") in out                    # 임시 노드가 용어 노드로 합쳐졌다


def test_identity_reject_writes_negative_alias(tmp_path, monkeypatch):
    save_record(tmp_path, ExperimentRecord(id="2026-09-29_a-001", date="2026-09-29", materials=["XPhos Pd G3"]), "원문", "정리")
    kg.rebuild(tmp_path)
    _fake(monkeypatch, [], oa.Choices(choices=[oa.Choice(surface="XPhos Pd G3", choice="lg:xphos")]))
    cfg = Config(vault=tmp_path)
    oa.record_candidates(cfg)
    q = review.list_questions(tmp_path, "identity")[0]
    assert q["recommended"]["term_id"] == "lg:xphos"
    review.answer(cfg, q["qid"], "reject")
    overlay = yaml.safe_load((tmp_path / "ontology" / "overlay.yaml").read_text(encoding="utf-8"))
    assert overlay["aliases"][0]["verdict"] == "negative"


def test_research_repoints_quote_without_reextraction(manual_vault, monkeypatch):
    moved = oa.XOut(chunks=[oa.XChunk(chunk_id="man-ops#1", claims=[
        _claim("SPhos Pd G4", "inhibits", "Suzuki-Miyaura coupling", "SPhos Pd G4 degrades quickly in THF.")])])
    calls = _fake(monkeypatch, [moved], NEW_G4)
    oa.build(Config(vault=manual_vault))
    assert calls.count("XOut") == 1                                       # 근거 재탐색으로 고쳤으니 재추출 없음
    with kg.db(manual_vault) as conn:
        row = conn.execute("select payload from item where kind='claim'").fetchone()[0]
    assert '"chunk_id": "man-ops#2"' in row


def test_extraction_cache_and_failure_handling(manual_vault, monkeypatch):
    cfg = Config(vault=manual_vault)
    vocab = oa.load_vocabulary(manual_vault)
    chunk = {"chunk_id": "man-ops#1", "doc_id": "man-ops", "page": 1, "text": P1}
    calls = _fake(monkeypatch, [oa.XOut()])
    oa.extract(cfg, vocab, [chunk], [])
    assert oa.extract(cfg, vocab, [chunk], [])[1] is True and calls == ["XOut"]

    def boom(*a, **k):
        raise RuntimeError("claude 응답 없음")

    monkeypatch.setattr(oa, "generate_parsed", boom)
    with kg.db(manual_vault) as conn:
        conn.execute("delete from llm_cache")
    stats = oa.build(cfg)
    assert stats["errors"] == 1
    with kg.db(manual_vault) as conn:
        assert conn.execute("select status from doc").fetchone()[0] == "error"
        assert {r[0] for r in conn.execute("select status from chunk")} == {"error"}


def test_gates_flag_each_failure(tmp_path):
    vocab = oa.load_vocabulary(tmp_path)
    chunk = {"chunk_id": "c#1", "doc_id": "c", "page": 1}
    text = "The flow reactor temperature must stay between 30 and 110 °C."

    def g(x):
        return oa.gates(vocab, oa.normalize(vocab, x, chunk), text)

    ok = _claim("temperature", "spec_range", "flow reactor", text, {"°C": [30, 110]})
    assert set(g(ok).values()) == {"ok"}
    assert g(_claim("temperature", "spec_range", "flow reactor", text, {"°C": [30, 120]}))["G1"].startswith("number")
    assert g(_claim("temperature", "explodes", "flow reactor", text))["G2"].startswith("predicate")
    assert g(_claim("pressure", "spec_range", "flow reactor", text, {"°C": [30, 110]}))["G3"].startswith("unlinked")
    assert g(_claim("temperature", "spec_range", "flow reactor", text, {"bar": [30, 110]}))["G4"].startswith("unit")
    assert g(_claim("THF", "increases", "reaction yield", "THF raises the yield."))["G1"] == "quote: 원문에 없는 인용"


def test_pull_common_validates_then_replaces_and_rebuilds(kg_vault, monkeypatch):
    import io
    import urllib.request
    from horcrux.vocab import PKG_ONTOLOGY
    dst = kg_vault / "ontology" / "common.yaml"
    before = dst.read_text(encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"terms: nope"))
    with pytest.raises(ValueError):
        oa.pull_common(Config(vault=kg_vault), "https://x.test/common.yaml")
    assert dst.read_text(encoding="utf-8") == before   # 검증 실패면 사본을 건드리지 않는다
    text = (PKG_ONTOLOGY / "common.yaml").read_text(encoding="utf-8").replace("version: 2026.10.0", "version: 2026.11.0")
    text = text.replace("terms:\n", "terms:\n  - {id: 'lab:pulled', label: pulled term, kind: material, parent: null}\n", 1)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: io.BytesIO(text.encode("utf-8")))
    run = trace.start(kg_vault, "ontology", "pull")
    out = oa.pull_common(Config(vault=kg_vault), None, run)
    assert (out["version"], out["added"], out["removed"]) == ("2026.11.0", ["lab:pulled"], [])
    from horcrux.vocab import load_vocabulary
    assert "lab:pulled" in load_vocabulary(kg_vault).terms   # 더 높은 version이라 동봉본으로 되돌아가지 않는다
    assert [e["stage"] for e in trace.get_run(kg_vault, run)["events"]] == ["common.pull"]


def test_export_contribution_leaves_out_record_derived_items(kg_vault):
    import json
    with kg.db(kg_vault) as conn:
        conn.execute("insert into doc(doc_id, title, kind, source) values('man-x', 'X manual', 'manual', 'x.pdf')")
        conn.execute("insert into question(qid, context) values('q-doc', ?)",
                     (json.dumps({"source": {"chunk_id": "man-x#3"}}),))
        conn.execute("insert into question(qid, context) values('q-rec', ?)",
                     (json.dumps({"source": {"records": ["2026-09-03_b-001"]}}),))
    (kg_vault / "ontology" / "overlay.yaml").write_text(yaml.safe_dump({
        "terms": [{"id": "lab:from-manual", "label": "from manual", "kind": "material", "qid": "q-doc"},
                  {"id": "lab:from-record", "label": "from record", "kind": "material", "qid": "q-rec"}],
        "aliases": [{"surface": "XPG3", "term_id": "lg:flow_reactor", "verdict": "positive", "qid": "q-doc"},
                    {"surface": "nope", "term_id": "lg:flow_reactor", "verdict": "negative", "qid": "q-doc"}]},
        allow_unicode=True), encoding="utf-8")
    doc = yaml.safe_load((kg_vault / "ontology" / "claims.yaml").read_text(encoding="utf-8"))
    doc["claims"].append({"id": "c-rec", "subject": "lg:protodeboronation", "predicate": "decreases",
                          "object": "lg:conversion", "sources": [{"record_id": "2026-09-01_a-001"}]})
    (kg_vault / "ontology" / "claims.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    p = oa.export_contribution(Config(vault=kg_vault), kg_vault / "out.yaml")
    got = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert [t["id"] for t in got["terms"]] == ["lab:from-manual"]
    assert got["aliases"] == [{"surface": "XPG3", "term_id": "lg:flow_reactor"}]
    assert [c["id"] for c in got["claims"]] == ["c-1", "c-2", "s-1"]
    assert got["claims"][0]["sources"] == [{"title": "X manual", "page": 4,
                                            "quote": "higher temperature promotes protodeboronation"}]
