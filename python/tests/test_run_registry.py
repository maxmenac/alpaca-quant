"""Tests for the append-only controlled fetch run registry."""

from datetime import UTC, datetime

import pytest

from alpaca_quant.data.run_registry import (
    FetchRunRecord,
    RunRegistryError,
    append_fetch_run_record,
    read_fetch_run_records,
)


def record(run_id: str = "fetch-test-001", **overrides) -> FetchRunRecord:
    values = {
        "run_id": run_id,
        "created_at": datetime(2026, 6, 14, 12, tzinfo=UTC),
        "symbols": ["aapl", "MSFT"],
        "start": "2024-01-02",
        "end": "2024-01-08",
        "feed": "iex",
        "rows_written": 10,
        "output_dir": "data/runs/alpaca_controlled_001",
        "parquet_path": "data/runs/alpaca_controlled_001/historical_bars.parquet",
        "manifest_path": "data/runs/alpaca_controlled_001/data_declaration.yaml",
        "data_declaration_id": "dq-tier0-alpaca-iex-2024-01-02-2024-01-08",
        "verification_passed": True,
        "known_gaps": ["IEX covers only a subset of US market volume"],
        "status": "success",
    }
    values.update(overrides)
    return FetchRunRecord(**values)


def test_create_valid_fetch_run_record():
    fetch_record = record()

    assert fetch_record.symbols == ["AAPL", "MSFT"]
    assert fetch_record.mode == "controlled_historical_fetch"
    assert fetch_record.status == "success"


def test_append_and_read_one_record(tmp_path):
    registry_path = tmp_path / "nested" / "fetch_registry.jsonl"

    append_fetch_run_record(registry_path, record())
    records = read_fetch_run_records(registry_path)

    assert registry_path.is_file()
    assert len(records) == 1
    assert records[0].run_id == "fetch-test-001"


def test_append_two_records_preserves_order(tmp_path):
    registry_path = tmp_path / "fetch_registry.jsonl"

    append_fetch_run_record(registry_path, record("fetch-test-001"))
    append_fetch_run_record(registry_path, record("fetch-test-002"))

    assert [item.run_id for item in read_fetch_run_records(registry_path)] == [
        "fetch-test-001",
        "fetch-test-002",
    ]
    assert len(registry_path.read_text(encoding="utf-8").splitlines()) == 2


def test_invalid_jsonl_raises_clear_error(tmp_path):
    registry_path = tmp_path / "fetch_registry.jsonl"
    append_fetch_run_record(registry_path, record())
    with registry_path.open("a", encoding="utf-8") as registry:
        registry.write("not-json\n")

    with pytest.raises(RunRegistryError, match="line 2"):
        read_fetch_run_records(registry_path)


def test_safe_record_does_not_serialize_environment_secrets(tmp_path, monkeypatch):
    registry_path = tmp_path / "fetch_registry.jsonl"
    api_key = "configured-key-must-not-appear"
    api_secret = "configured-secret-must-not-appear"
    monkeypatch.setenv("ALPACA_API_KEY_ID", api_key)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", api_secret)

    append_fetch_run_record(registry_path, record())

    serialized = registry_path.read_text(encoding="utf-8")
    assert api_key not in serialized
    assert api_secret not in serialized


def test_secret_value_is_rejected_and_not_serialized(tmp_path):
    registry_path = tmp_path / "fetch_registry.jsonl"
    secret = "secret-value-must-not-be-written"
    unsafe_record = record(known_gaps=[f"accidental secret: {secret}"])

    with pytest.raises(RunRegistryError, match="configured secret value"):
        append_fetch_run_record(
            registry_path,
            unsafe_record,
            sensitive_values=[secret],
        )

    assert not registry_path.exists()
