"""Phase 4E lineage registry tests: provenance only, synthetic/temp paths only."""

import json
from datetime import UTC, datetime

import pytest

from alpaca_quant.research import synthetic_provenance as sp
from alpaca_quant.research.dataset_report import (
    attach_feature_set_id,
    build_dataset_inspection_report,
)
from alpaca_quant.research.feature_registry import compute_feature_set_id
from alpaca_quant.research.lineage_registry import (
    LineageRegistryError,
    append_lineage_record,
    build_lineage_record,
    export_lineage_records,
    fingerprint_lineage_entry,
    lineage_record_from_manifest_report,
    query_lineage_records,
    read_lineage_records,
)


def _clock():
    return datetime(2026, 6, 16, tzinfo=UTC)


def _inspect(fixture):
    assembled = fixture.assemble(clock=_clock)
    registry = sp.synthetic_registry()
    report = build_dataset_inspection_report(
        assembled.frame,
        manifest=assembled.manifest,
        registry=registry,
        requested_features=[sp.NEUTRAL_FEATURE],
        clock=_clock,
    )
    report = attach_feature_set_id(report, compute_feature_set_id(registry.definitions))
    return assembled, report


def _entry(fixture):
    assembled, report = _inspect(fixture)
    return lineage_record_from_manifest_report(
        manifest=assembled.manifest,
        inspection_report=report,
        clock=_clock,
    ), report


def test_entry_created_from_manifest_and_report_records_lineage_fields() -> None:
    entry, report = _entry(sp.clean_fixture())

    assert entry.record_type == "lineage"
    assert entry.schema_version == 1
    assert entry.entry_id.startswith("lin-")
    assert entry.dataset_id == report["dataset_id"]
    assert entry.dataset_fingerprint == report["dataset_fingerprint"]
    assert entry.feature_set_id == report["feature_set_id"]
    assert entry.verdict == "OK"
    assert entry.declared_corporate_actions_status == sp.CLEAN_CORPORATE_ACTIONS_STATUS


def test_verdict_and_reason_list_are_recorded_verbatim() -> None:
    entry, report = _entry(sp.ambiguous_adjustment_fixture())

    assert entry.verdict == report["verdict"] == "SUSPECT"
    assert entry.reason_list == report["warnings"]
    assert any(
        reason["code"] == "ambiguous_adjustment_declaration"
        for reason in entry.reason_list
    )


def test_ok_and_suspect_verdicts_are_carried_not_recomputed() -> None:
    ok_entry, ok_report = _entry(sp.clean_fixture())
    suspect_entry, suspect_report = _entry(sp.missing_available_at_fixture())

    assert ok_entry.verdict == ok_report["verdict"] == "OK"
    assert ok_entry.reason_list == []
    assert suspect_entry.verdict == suspect_report["verdict"] == "SUSPECT"
    assert suspect_entry.reason_list == suspect_report["warnings"]


def test_entry_fingerprint_is_canonical_and_changes_with_lineage() -> None:
    entry, _ = _entry(sp.clean_fixture())
    payload = entry.model_dump(mode="json")
    shuffled_payload = dict(reversed(list(payload.items())))

    assert fingerprint_lineage_entry(payload) == entry.entry_fingerprint
    assert fingerprint_lineage_entry(shuffled_payload) == entry.entry_fingerprint

    changed = build_lineage_record(
        created_at_utc=entry.created_at_utc,
        dataset_id=entry.dataset_id,
        dataset_fingerprint=entry.dataset_fingerprint,
        feature_set_id=entry.feature_set_id,
        source_label_fingerprint=entry.source_label_fingerprint,
        split_ref=entry.split_ref,
        verdict="SUSPECT",
        reason_list=[{"code": "synthetic", "severity": "SUSPECT", "message": "changed"}],
        declared_corporate_actions_status=entry.declared_corporate_actions_status,
        declared_adjustment_status=entry.declared_adjustment_status,
    )
    assert changed.entry_fingerprint != entry.entry_fingerprint


def test_fingerprint_stable_across_runs_with_frozen_clock() -> None:
    first, _ = _entry(sp.clean_fixture())
    second, _ = _entry(sp.clean_fixture())

    assert first.entry_id == second.entry_id
    assert first.entry_fingerprint == second.entry_fingerprint
    assert first.created_at_utc == second.created_at_utc == _clock()


def test_append_read_query_and_duplicate_guard_use_temp_registry(tmp_path) -> None:
    clean, _ = _entry(sp.clean_fixture())
    dirty, _ = _entry(sp.ambiguous_adjustment_fixture())
    path = tmp_path / "lineage.jsonl"

    append_lineage_record(path, clean)
    append_lineage_record(path, dirty)
    records = read_lineage_records(path)

    assert path.is_file()
    assert "data/runs" not in str(path)
    assert [record.entry_id for record in records] == [clean.entry_id, dirty.entry_id]
    assert query_lineage_records(records, dataset_id=clean.dataset_id) == records
    assert query_lineage_records(records, feature_set_id=clean.feature_set_id) == records
    assert query_lineage_records(records, verdict="SUSPECT") == [dirty]

    with pytest.raises(LineageRegistryError, match="entry_id already exists"):
        append_lineage_record(path, clean)


def test_export_writes_json_to_explicit_temp_path(tmp_path) -> None:
    clean, _ = _entry(sp.clean_fixture())
    dirty, _ = _entry(sp.ambiguous_adjustment_fixture())
    out = tmp_path / "exports" / "lineage.json"

    export_lineage_records([clean, dirty], out)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert out.is_file()
    assert "data/runs" not in str(out)
    assert [item["entry_id"] for item in payload] == [clean.entry_id, dirty.entry_id]


def test_4f0_clean_and_dirty_fixture_registration_regression() -> None:
    clean, _ = _entry(sp.clean_fixture())
    dirty, _ = _entry(sp.missing_available_at_fixture())

    assert clean.verdict == "OK"
    assert dirty.verdict == "SUSPECT"
    assert any(
        reason["code"] == "missing_available_at_semantics"
        for reason in dirty.reason_list
    )
