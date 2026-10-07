import importlib.util
from pathlib import Path

import pytest

from horcrux import kg, manual, trace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_demo_manual.py"


def _pdf_bytes():
    spec = importlib.util.spec_from_file_location("make_demo_manual", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pdf_bytes


def _manual(extra: str = "") -> bytes:
    """영문 2쪽 + 스캔처럼 글자가 거의 없는 1쪽. 쪽마다 같은 머리말과 쪽번호가 있다."""
    return _pdf_bytes()([
        ["ACME Flow Reactor Manual", "Operating limits", "",
         "The reactor temperature must stay between 30 and 110 °C.",
         "Higher temperature promotes proto-", "deboronation of heteroaryl boronic acids." + extra, "Page 1"],
        ["ACME Flow Reactor Manual", "Residence time", "",
         "Use a residence time of 60 to 600 s for Suzuki-Miyaura coupling in THF.", "Page 2"],
        ["ACME Flow Reactor Manual", "x", "Page 3"],
    ], "ACME Flow Reactor Manual")


def test_extract_clean_and_skip_scanned_pages():
    pages = manual.extract_pages(_manual())
    assert [p for p, _ in pages] == [1, 2, 3]
    kept, skipped = manual.clean_pages(pages)
    assert skipped == [3]
    first = kept[0][1]
    assert "ACME Flow Reactor Manual" not in first and "Page 1" not in first   # 머리말·쪽번호 제거
    assert "promotes protodeboronation" in first                               # 줄 끝 하이픈 연결
    assert [p for p, _ in manual.extract_pages(_manual(), "2-3")] == [2, 3]


def test_chunks_respect_size_and_sentence_boundaries():
    text = " ".join(f"Sentence {i} keeps the reactor stable under flow." for i in range(60))
    chunks = manual.chunk_pages([(4, text)])
    assert len(chunks) >= 2 and all(len(t) <= manual.CHUNK_MAX for _, t in chunks)
    assert all(t.endswith(".") for _, t in chunks) and {p for p, _ in chunks} == {4}


def test_add_manual_stores_truth_index_and_passages(tmp_path):
    run = trace.start(tmp_path, "manual", "ACME")
    out = manual.add_manual(tmp_path, "ACME manual.pdf", _manual(), run_id=run)
    assert (out["doc_id"], out["created"], out["skipped"]) == ("man-acme-manual", True, [3])
    d = tmp_path / "raw" / "manuals"
    assert (d / "man-acme-manual.pdf").read_bytes()[:5] == b"%PDF-"
    md = (d / "man-acme-manual.md").read_text(encoding="utf-8")
    assert md.startswith("---\n") and "<!-- page: 1 -->" in md and "title: ACME Flow Reactor Manual" in md
    with kg.db(tmp_path) as conn:
        assert conn.execute("select status from doc").fetchone()[0] == "queued"
        assert conn.execute("select count(*) from chunk where status='pending'").fetchone()[0] == out["chunks"]
        hit = conn.execute("select chunk_id from chunk_fts where chunk_fts match '\"promotes protodeboronation\"'").fetchall()
        assert [r[0] for r in hit] == ["man-acme-manual#1"]
    g = kg.load_graph(tmp_path)
    assert ("MENTIONS", "lg:protodeboronation") in {(r, d) for r, d, _ in g.out["psg:man-acme-manual#1"]}
    stages = [e["stage"] for e in trace.get_run(tmp_path, run)["events"]]
    assert stages == ["p1.save", "p1.text", "p1.clean", "p1.chunk"]


def test_same_bytes_return_existing_doc_and_same_name_gets_suffix(tmp_path):
    first = manual.add_manual(tmp_path, "ACME manual.pdf", _manual())
    again = manual.add_manual(tmp_path, "ACME manual.pdf", _manual())
    assert (again["doc_id"], again["created"]) == (first["doc_id"], False)
    other = manual.add_manual(tmp_path, "ACME manual.pdf", _manual(" Extra sentence."))
    assert other["doc_id"] == "man-acme-manual-2"


def test_unreadable_pdf_is_rejected_without_leftovers(tmp_path):
    with pytest.raises(ValueError):
        manual.add_manual(tmp_path, "broken.pdf", b"not a pdf at all")
    assert not list((tmp_path / "raw" / "manuals").glob("*")) if (tmp_path / "raw" / "manuals").exists() else True
