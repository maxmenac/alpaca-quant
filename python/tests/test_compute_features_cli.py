"""Tests for the compute_features CLI. tmp_path only — no .env, no network.

Verifies --as-of is mandatory and that the CLI uses the PIT path (no lookahead past as_of).
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compute_features.py"


def _bars_df(symbol: str = "AAPL", n_rows: int = 10) -> pl.DataFrame:
    closes = [100.0 + i for i in range(n_rows)]
    return pl.DataFrame(
        {
            "symbol": [symbol] * n_rows,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n_rows)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n_rows)],
            "trade_count": [500] * n_rows,
            "vwap": closes,
        }
    )


def _make_run(tmp_path: Path, run: str = "run_x") -> Path:
    run_dir = tmp_path / run
    run_dir.mkdir(parents=True)
    _bars_df().write_parquet(run_dir / "historical_bars.parquet")
    return run_dir


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_as_of_is_required(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    result = _run_cli(["--run-dir", str(run_dir), "--symbol", "AAPL"])
    assert result.returncode != 0
    # argparse prints the missing-required-argument error to stderr
    assert "--as-of" in result.stderr
    assert "required" in result.stderr.lower()


def test_runs_with_as_of(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    result = _run_cli(
        ["--run-dir", str(run_dir), "--symbol", "AAPL", "--as-of", "2024-01-06"]
    )
    assert result.returncode == 0, result.stderr
    assert (run_dir / "features_AAPL.parquet").is_file()
    assert (run_dir / "features_AAPL_manifest.yaml").is_file()


def test_cli_respects_as_of_cutoff(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    _run_cli(["--run-dir", str(run_dir), "--symbol", "AAPL", "--as-of", "2024-01-06"])
    df = pl.read_parquet(run_dir / "features_AAPL.parquet")
    # bars start 2024-01-02; as_of 2024-01-06 inclusive => 5 rows, none after the cutoff
    assert df["timestamp"].dt.date().max().isoformat() == "2024-01-06"
    assert len(df) == 5


def test_cli_manifest_records_as_of(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    _run_cli(["--run-dir", str(run_dir), "--symbol", "AAPL", "--as-of", "2024-01-06"])
    manifest = yaml.safe_load((run_dir / "features_AAPL_manifest.yaml").read_text())
    assert manifest["as_of"] == "2024-01-06"


def test_cli_missing_bars_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty_run"
    empty.mkdir()
    result = _run_cli(
        ["--run-dir", str(empty), "--symbol", "AAPL", "--as-of", "2024-01-06"]
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower()
