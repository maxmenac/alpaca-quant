"""Tests for experiment report building. Synthetic + tmp_path only — no .env, no network."""

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml

from alpaca_quant.backtest.engine.engine import run_backtest
from alpaca_quant.backtest.null_models import run_null_battery
from alpaca_quant.research.experiment_report import (
    build_report_payload,
    render_markdown,
    write_report,
)

_FACTORS = [1.03, 0.98, 1.05, 0.97, 1.04, 0.96]


def _frame(n: int = 20) -> pl.DataFrame:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * _FACTORS[i % len(_FACTORS)])
    return pl.DataFrame(
        {
            "symbol": ["AAPL"] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": closes,
            "weight": [1.0] * n,
        }
    )


def _costs(tmp_path: Path) -> str:
    path = tmp_path / "costs.yaml"
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
    return str(path)


def _payload(tmp_path: Path) -> dict:
    frame = _frame()
    bt = run_backtest(frame)
    battery = run_null_battery(frame, costs_path=_costs(tmp_path))
    return build_report_payload(
        run_id="exp-test-001",
        as_of="2024-01-21",
        seed=12345,
        config={"horizon": 1, "seed": 12345},
        config_hash="sha256:abc",
        weight_source="caller:test",
        backtest_result=bt,
        battery_report=battery,
    )


def test_payload_keys(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    for key in (
        "run_id",
        "as_of",
        "seed",
        "config",
        "config_hash",
        "weight_source",
        "headline_metrics",
        "null_battery",
        "equity_curve",
    ):
        assert key in payload


def test_markdown_contains_metrics_and_verdicts(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path))
    assert "# Backtest experiment exp-test-001" in md
    assert "sharpe" in md
    assert "future_leak_detected" in md


def test_write_report_creates_both_files(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    assert paths.json_path.is_file()
    assert paths.markdown_path.is_file()


def test_json_report_parses(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    parsed = json.loads(paths.json_path.read_text())
    assert parsed["run_id"] == "exp-test-001"
    assert "null_battery" in parsed


def test_no_secret_names_in_reports(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    combined = paths.json_path.read_text() + paths.markdown_path.read_text()
    assert "ALPACA_API_KEY_ID" not in combined
    assert "ALPACA_API_SECRET_KEY" not in combined
