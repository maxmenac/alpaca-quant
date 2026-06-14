"""Tests for the run_experiment CLI. Synthetic + tmp_path only — no .env, no network."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_experiment.py"
_FACTORS = [1.03, 0.98, 1.05, 0.97, 1.04, 0.96]


def _bars(path: Path, n: int = 20) -> Path:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * _FACTORS[i % len(_FACTORS)])
    pl.DataFrame(
        {
            "symbol": ["AAPL"] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n)],
            "trade_count": [500] * n,
            "vwap": closes,
        }
    ).write_parquet(path)
    return path


def _weights(path: Path, n: int = 20) -> Path:
    pl.DataFrame(
        {
            "symbol": ["AAPL"] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "weight": [1.0] * n,
        }
    ).write_parquet(path)
    return path


def _costs(path: Path) -> Path:
    path.write_text(
        yaml.dump(
            {
                "commission_bps": 0,
                "slippage_bps_daily": 5,
                "slippage_bps_stress_2x": 10,
                "slippage_bps_stress_5x": 25,
            }
        )
    )
    return path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _base_args(tmp_path: Path) -> list[str]:
    return [
        "--bars",
        str(_bars(tmp_path / "bars.parquet")),
        "--weights",
        str(_weights(tmp_path / "weights.parquet")),
        "--costs",
        str(_costs(tmp_path / "costs.yaml")),
        "--registry",
        str(tmp_path / "registry.jsonl"),
        "--report-dir",
        str(tmp_path / "reports"),
        "--weight-source",
        "caller:cli_test",
    ]


def test_as_of_required(tmp_path: Path) -> None:
    result = _run_cli(_base_args(tmp_path))  # no --as-of
    assert result.returncode != 0
    assert "--as-of" in result.stderr
    assert "required" in result.stderr.lower()


def test_full_run(tmp_path: Path) -> None:
    result = _run_cli(_base_args(tmp_path) + ["--as-of", "2024-01-15"])
    assert result.returncode == 0, result.stderr
    assert "run_id" in result.stdout
    assert "future_leak_detected" in result.stdout
    assert (tmp_path / "registry.jsonl").is_file()
    reports = list((tmp_path / "reports").glob("experiment_*.json"))
    assert len(reports) == 1


def test_missing_weights_file(tmp_path: Path) -> None:
    args = [
        "--bars",
        str(_bars(tmp_path / "bars.parquet")),
        "--weights",
        str(tmp_path / "nope.parquet"),
        "--costs",
        str(_costs(tmp_path / "costs.yaml")),
        "--registry",
        str(tmp_path / "registry.jsonl"),
        "--report-dir",
        str(tmp_path / "reports"),
        "--weight-source",
        "caller:cli_test",
        "--as-of",
        "2024-01-15",
    ]
    result = _run_cli(args)
    assert result.returncode != 0
    assert "not found" in result.stderr.lower()


def test_no_secret_names_in_output(tmp_path: Path) -> None:
    result = _run_cli(_base_args(tmp_path) + ["--as-of", "2024-01-15"])
    combined = result.stdout + result.stderr
    assert "ALPACA_API_KEY_ID" not in combined
    assert "ALPACA_API_SECRET_KEY" not in combined
