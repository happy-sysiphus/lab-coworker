import pytest

from horcrux.records import (
    ExperimentRecord, Parameter, Resolution, SuspectedCause, Symptom,
    list_records, load_record, make_record_id, record_path, save_record, update_resolution,
)


def sample_record(rid="2026-07-19_test-001"):
    return ExperimentRecord(
        id=rid, date="2026-07-19", experiment_type="박막 증착",
        objective="ITO 박막 증착", equipment=["RF 스퍼터"], materials=["ITO 타겟"],
        parameters=[Parameter(name="RF power", value="150W", controllable=True)],
        results="증착률 5nm/min",
        symptom=Symptom(category="low_value", description="증착률이 평소보다 낮음"),
        suspected_causes=[SuspectedCause(cause="타겟 표면 산화")],
        actions_taken=["타겟 표면 확인"],
    )


def test_roundtrip(tmp_path):
    rec = sample_record()
    path = save_record(tmp_path, rec, "원문 로그입니다", "정리 서술입니다")
    loaded, body = load_record(path)
    assert loaded == rec
    assert "원문 로그입니다" in body
    assert "정리 서술입니다" in body
    assert list_records(tmp_path) == [path]


def test_update_resolution_confirms_cause(tmp_path):
    rec = sample_record()
    rec.suspected_causes.append(SuspectedCause(cause="가스 유량 오류"))
    save_record(tmp_path, rec, "원문", "정리")
    updated = update_resolution(tmp_path, rec.id, True, "타겟 표면 산화", note="연마 후 정상")
    assert updated.resolution == Resolution(resolved=True, actual_cause="타겟 표면 산화", note="연마 후 정상")
    statuses = {c.cause: c.status for c in updated.suspected_causes}
    assert statuses == {"타겟 표면 산화": "confirmed", "가스 유량 오류": "rejected"}
    # 디스크에도 반영
    reloaded, _ = load_record(tmp_path / "raw" / "experiments" / f"{rec.id}.md")
    assert reloaded.resolution.resolved is True


def test_update_resolution_new_cause_appended(tmp_path):
    rec = sample_record()
    save_record(tmp_path, rec, "원문", "정리")
    updated = update_resolution(tmp_path, rec.id, True, "기판 오염")
    assert any(c.cause == "기판 오염" and c.status == "confirmed" for c in updated.suspected_causes)


def test_make_record_id_unique(tmp_path):
    rid1 = make_record_id(tmp_path, "2026-07-19", "박막 증착")
    save_record(tmp_path, sample_record(rid1), "원문", "정리")
    rid2 = make_record_id(tmp_path, "2026-07-19", "박막 증착")
    assert rid1 != rid2
    assert rid1.startswith("2026-07-19_") and rid2.endswith("-002")


def test_roundtrip_with_dashes_in_values(tmp_path):
    rec = sample_record()
    rec.results = "온도 구간 --- 에서 급락"
    path = save_record(tmp_path, rec, "본문에도 --- 구분선", "정리")
    loaded, body = load_record(path)
    assert loaded == rec
    assert "---" in body


@pytest.mark.parametrize("bad", [
    "../../other-lab/raw/experiments/x",
    "..\\..\\other\\x",
    "sub/dir",
    "..",
    "",
])
def test_record_path_rejects_traversal(tmp_path, bad):
    with pytest.raises(ValueError):
        record_path(tmp_path, bad)


def test_record_path_accepts_plain_id(tmp_path):
    assert record_path(tmp_path, "2026-08-01_x-001").name == "2026-08-01_x-001.md"


def test_followup_of_roundtrip(tmp_path):
    rec = ExperimentRecord(id="2026-08-01_x-001", date="2026-08-01",
                           followup_of="2026-07-31_x-001")
    save_record(tmp_path, rec, "원문", "요약")
    loaded, _ = load_record(record_path(tmp_path, rec.id))
    assert loaded.followup_of == "2026-07-31_x-001"


def test_update_resolution_matches_cause_by_canon_and_alias(tmp_path):
    import yaml
    overlay = tmp_path / "ontology" / "overlay.yaml"
    overlay.parent.mkdir(parents=True)
    overlay.write_text(yaml.safe_dump({"aliases": [
        {"surface": "보론산 분해", "term_id": "lg:protodeboronation", "verdict": "positive"}]},
        allow_unicode=True), encoding="utf-8")
    rec = ExperimentRecord(id="2026-09-29_x-001", date="2026-09-29", suspected_causes=[
        SuspectedCause(cause="보론산 분해"), SuspectedCause(cause="퍼지  부족")])
    save_record(tmp_path, rec, "원문", "정리")
    out = update_resolution(tmp_path, rec.id, True, "protodeboronation")
    assert [(c.cause, c.status) for c in out.suspected_causes] == [
        ("보론산 분해", "confirmed"), ("퍼지  부족", "rejected")]
    out = update_resolution(tmp_path, rec.id, True, "퍼지 부족")   # 공백만 다른 같은 원인 — 새로 추가하지 않는다
    assert [c.status for c in out.suspected_causes] == ["rejected", "confirmed"]
