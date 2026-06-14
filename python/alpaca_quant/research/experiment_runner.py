"""Orchestrate a backtest experiment and record it immutably.

Wires the existing blocks: PIT read -> backtest engine -> null-model battery -> experiment
registry + report. It does NOT create a strategy: weights are caller-provided (local Parquet).

Local-only. No network. No Alpaca API. No .env. No real alpha, no strategy discovery, no
optimizer, no model training, no live trading, no order logic.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from alpaca_quant.backtest.costs.model import load_cost_model
from alpaca_quant.backtest.engine.engine import BacktestResult, run_backtest
from alpaca_quant.backtest.null_models import NullBatteryReport, run_null_battery
from alpaca_quant.data.pit.reader import load_pit_bars
from alpaca_quant.research.experiment_registry import (
    ExperimentRecord,
    append_experiment_record,
    new_experiment_record,
)
from alpaca_quant.research.experiment_report import (
    ReportPaths,
    build_report_payload,
    write_report,
)

DEFAULT_REGISTRY = "data/runs/experiment_registry.jsonl"
DEFAULT_REPORT_DIR = "data/runs"
WEIGHT_COLUMNS = ("symbol", "timestamp", "weight")


class ExperimentRunError(RuntimeError):
    """Raised when a backtest experiment cannot be assembled or recorded safely."""


@dataclass(frozen=True)
class ExperimentRunResult:
    record: ExperimentRecord
    report_paths: ReportPaths
    backtest_result: BacktestResult
    battery_report: NullBatteryReport


def compute_config_hash(config: dict) -> str:
    """Deterministic sha256 over the canonical, result-determining configuration."""
    serialized = json.dumps(config, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(serialized.encode()).hexdigest()}"


def flatten_experiment_metrics(
    backtest_result: BacktestResult,
    battery_report: NullBatteryReport,
) -> dict[str, float]:
    """Flat, strictly-numeric metrics map. Booleans are encoded as 1.0/0.0."""
    m = backtest_result.metrics
    nb = battery_report
    return {
        "bt.sharpe": float(m.sharpe),
        "bt.sortino": float(m.sortino),
        "bt.max_drawdown": float(m.max_drawdown),
        "bt.annual_turnover": float(m.annual_turnover),
        "bt.total_return": float(m.total_return),
        "bt.cagr": float(m.cagr),
        "bt.n_periods": float(m.n_periods),
        "nb.baseline.sharpe": float(nb.baseline.sharpe),
        "nb.random.sharpe": float(nb.random_weights.sharpe),
        "nb.shuffled.sharpe": float(nb.shuffled_weights.sharpe),
        "nb.shifted.sharpe": float(nb.shifted_weights.sharpe),
        "nb.future_leak.sharpe": float(nb.future_leak.sharpe),
        "nb.cost_stress_2x.total_return": float(nb.cost_stress_2x.total_return),
        "nb.cost_stress_5x.total_return": float(nb.cost_stress_5x.total_return),
        "nb.future_leak_detected": 1.0 if nb.future_leak_detected else 0.0,
        "nb.random_near_zero": 1.0 if nb.random_near_zero else 0.0,
        "nb.shuffled_near_zero": 1.0 if nb.shuffled_near_zero else 0.0,
    }


def _load_weights(weights_path: str | Path) -> pl.DataFrame:
    path = Path(weights_path)
    if not path.is_file():
        raise ExperimentRunError(f"weights Parquet not found: {path}")
    weights = pl.read_parquet(path)
    missing = [c for c in WEIGHT_COLUMNS if c not in weights.columns]
    if missing:
        raise ExperimentRunError(f"weights are missing required columns: {', '.join(missing)}")
    return weights.select(WEIGHT_COLUMNS)


def _timestamp_to_utc(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize the timestamp column to UTC so frames from different readers join cleanly.

    The DuckDB-backed PIT reader can return a session-local time zone; weights read directly via
    Polars keep their stored zone. Both represent the same instant — align them on UTC.
    """
    dtype = df.schema["timestamp"]
    if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
        return df.with_columns(pl.col("timestamp").dt.convert_time_zone("UTC"))
    return df.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))


def run_backtest_experiment(
    *,
    bars_path: str | Path,
    weights_path: str | Path,
    as_of: str | date,
    weight_source: str,
    seed: int = 12345,
    horizon: int = 1,
    symbols: Sequence[str] | None = None,
    costs_path: str = "configs/costs.yaml",
    periods_per_year: int = 252,
    registry_path: str | Path = DEFAULT_REGISTRY,
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    feature_set_id: str | None = None,
    dataset_id: str | None = None,
    decided_by: str | None = None,
    notes: str | None = None,
    repo_dir: str | Path | None = None,
) -> ExperimentRunResult:
    """Run a backtest experiment on caller-provided weights and record it immutably.

    PIT-enforced (`as_of` required): bars are read via load_pit_bars and run_backtest re-asserts
    no-lookahead. The null-model battery runs on the same frame. A JSON + Markdown report is
    written and an immutable registry entry (numeric metrics, no_backtesting=False) is appended.
    """
    if not weight_source or not weight_source.strip():
        raise ExperimentRunError("weight_source must be a non-empty provenance label")
    if horizon < 1:
        raise ExperimentRunError("horizon must be at least 1")

    as_of_str = as_of.isoformat() if isinstance(as_of, date) else str(as_of)

    # PIT read (drops any row after the cutoff), then join caller-provided weights.
    bars = _timestamp_to_utc(load_pit_bars(bars_path, as_of=as_of, symbols=symbols))
    weights = _timestamp_to_utc(_load_weights(weights_path))
    frame = bars.join(weights, on=["symbol", "timestamp"], how="inner")
    if frame.is_empty():
        raise ExperimentRunError("no rows after joining PIT bars with weights on symbol/timestamp")

    cost_model = load_cost_model(costs_path, stress="none")
    # Headline result (with per-period equity for the report); as_of re-asserts no lookahead.
    backtest_result = run_backtest(
        frame,
        horizon=horizon,
        cost_model=cost_model,
        as_of=as_of,
        periods_per_year=periods_per_year,
    )
    battery_report = run_null_battery(
        frame,
        horizon=horizon,
        seed=seed,
        costs_path=costs_path,
        periods_per_year=periods_per_year,
    )

    config = {
        "bars_path": str(Path(bars_path).resolve()),
        "weights_path": str(Path(weights_path).resolve()),
        "weight_source": weight_source,
        "as_of": as_of_str,
        "horizon": horizon,
        "seed": seed,
        "periods_per_year": periods_per_year,
        "commission_bps": cost_model.commission_bps,
        "slippage_bps": cost_model.slippage_bps,
        "symbols": sorted(symbols) if symbols is not None else None,
    }
    config_hash = compute_config_hash(config)

    record = new_experiment_record(
        repo_dir=repo_dir,
        dataset_id=dataset_id,
        feature_set_id=feature_set_id,
        config_hash=config_hash,
        seed=seed,
        as_of=as_of_str,
        weight_source=weight_source,
        metrics=flatten_experiment_metrics(backtest_result, battery_report),
        decided_by=decided_by,
        notes=notes,
        no_backtesting=False,
    )

    payload = build_report_payload(
        run_id=record.run_id,
        as_of=as_of_str,
        seed=seed,
        config=config,
        config_hash=config_hash,
        weight_source=weight_source,
        backtest_result=backtest_result,
        battery_report=battery_report,
    )
    report_paths = write_report(payload, report_dir)

    # Record the report path, then append the immutable entry.
    record = record.model_copy(update={"report_path": str(report_paths.json_path)})
    append_experiment_record(registry_path, record)

    return ExperimentRunResult(
        record=record,
        report_paths=report_paths,
        backtest_result=backtest_result,
        battery_report=battery_report,
    )
