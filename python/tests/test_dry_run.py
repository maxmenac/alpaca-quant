"""Tests for the mocked local ingestion dry run."""

import yaml

from alpaca_quant.data.dry_run import run_mock_ingestion_dry_run
from alpaca_quant.data.duckdb_query import query_bars


def test_mock_ingestion_dry_run_creates_and_verifies_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    output_dir = tmp_path / "nested" / "dry-run"

    result = run_mock_ingestion_dry_run(output_dir)

    assert result.output_dir == output_dir
    assert result.parquet_path.is_file()
    assert result.manifest_path.is_file()
    assert result.verification_passed is True
    assert result.rows_written == 4
    assert result.symbols == ["AAPL", "MSFT"]


def test_dry_run_manifest_is_tier_zero(tmp_path):
    result = run_mock_ingestion_dry_run(tmp_path)

    manifest = yaml.safe_load(result.manifest_path.read_text(encoding="utf-8"))
    declaration = manifest["data_declaration"]
    assert declaration["tier"] == 0
    assert declaration["universe_source"] == "local-mocked-bars"
    assert declaration["known_gaps"]


def test_duckdb_query_reads_dry_run_output(tmp_path):
    result = run_mock_ingestion_dry_run(tmp_path)

    dataframe = query_bars(
        result.parquet_path,
        symbols=["msft"],
        start="2024-01-02",
        end="2024-01-03",
        columns=["symbol", "timestamp", "close"],
    )

    assert dataframe.shape == (2, 3)
    assert dataframe["symbol"].unique().to_list() == ["MSFT"]
