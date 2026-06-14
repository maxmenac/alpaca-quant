"""Tests for the backtest experiment runner. Synthetic + tmp_path only — no .env, no network."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
import yaml

from alpaca_quant.research.experiment_registry import read_experiment_records
from alpaca_quant.research.experiment_runner import (
    ExperimentRunError,
    compute_config_hash,
    flatten_experiment_metrics,
    run_backtest_experiment,
)

_FACTORS = [1.03, 0.98, 1.05, 0.97, 1.04, 0.96]


def _bars(tmp_path: Path, n: int = 20, symbol: str = "AAPL") -> Path:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * _FACTORS[i % len(_FACTORS)])
    df = pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n)],
            "trade_count": [500] * n,
            "vwap": closes,
        }
    )
    path = tmp_path / "historical_bars.parquet"
    df.write_parquet(path)
    return path


def _weights(
    tmp_path: Path, n: int = 20, symbol: str = "AAPL", *, drop_weight: bool = False
) -> Path:
    df = pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "weight": [1.0] * n,
        }
    )
    if drop_weight:
        df = df.drop("weight")
    path = tmp_path / ("weights_noweight.parquet" if drop_weight else "weights.parquet")
    df.write_parquet(path)
    return path


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


def _run(tmp_path: Path, **overrides):
    kwargs = {
        "bars_path": _bars(tmp_path),
        "weights_path": _weights(tmp_path),
        "as_of": "2024-01-15",
        "weight_source": "caller:test_v1",
        "costs_path": _costs(tmp_path),
        "registry_path": tmp_path / "experiment_registry.jsonl",
        "report_dir": tmp_path / "reports",
        "repo_dir": tmp_path,  # not a git repo -> git_sha None, deterministic
    }
    kwargs.update(overrides)
    return run_backtest_experiment(**kwargs)


class TestRun:
    def test_record_has_numeric_metrics(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.record.metrics
        assert all(isinstance(v, float) for v in result.record.metrics.values())
        assert "bt.sharpe" in result.record.metrics

    def test_record_provenance(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        rec = result.record
        assert rec.as_of == "2024-01-15"
        assert rec.weight_source == "caller:test_v1"
        assert rec.config_hash and rec.config_hash.startswith("sha256:")
        assert rec.report_path is not None

    def test_no_backtesting_false_safety_flags_true(self, tmp_path: Path) -> None:
        rec = _run(tmp_path).record
        assert rec.no_backtesting is False
        assert rec.no_trading is True
        assert rec.no_model_training is True
        assert rec.no_live_execution is True
        assert rec.no_order_submission is True

    def test_report_files_written(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.report_paths.json_path.is_file()
        assert result.report_paths.markdown_path.is_file()

    def test_registry_entry_appended(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        records = read_experiment_records(tmp_path / "experiment_registry.jsonl")
        assert len(records) == 1
        assert records[0].run_id == result.record.run_id

    def test_pit_cutoff_enforced(self, tmp_path: Path) -> None:
        # bars run to 2024-01-21; as_of 2024-01-10 must exclude later rows from the result
        result = _run(tmp_path, as_of="2024-01-10")
        max_ts = result.backtest_result.periods["timestamp"].max()
        assert max_ts.date() <= date(2024, 1, 10)


class TestDeterminism:
    def test_same_config_same_hash_and_metrics(self, tmp_path: Path) -> None:
        bars = _bars(tmp_path)
        weights = _weights(tmp_path)
        costs = _costs(tmp_path)
        common = {
            "bars_path": bars,
            "weights_path": weights,
            "as_of": "2024-01-15",
            "weight_source": "caller:test_v1",
            "costs_path": costs,
            "registry_path": tmp_path / "reg.jsonl",
            "report_dir": tmp_path / "rep",
            "repo_dir": tmp_path,
        }
        a = run_backtest_experiment(**common)
        b = run_backtest_experiment(**common)
        assert a.record.config_hash == b.record.config_hash
        assert a.record.metrics == b.record.metrics


class TestValidation:
    def test_as_of_required(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            run_backtest_experiment(
                bars_path=_bars(tmp_path),
                weights_path=_weights(tmp_path),
                weight_source="caller:test",
            )  # type: ignore[call-arg]

    def test_missing_weight_column_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ExperimentRunError, match="missing required columns"):
            _run(tmp_path, weights_path=_weights(tmp_path, drop_weight=True))

    def test_blank_weight_source_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ExperimentRunError, match="weight_source"):
            _run(tmp_path, weight_source="  ")

    def test_missing_weights_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ExperimentRunError, match="weights Parquet not found"):
            _run(tmp_path, weights_path=tmp_path / "nope.parquet")


class TestHelpers:
    def test_config_hash_deterministic(self) -> None:
        cfg = {"a": 1, "b": "x"}
        assert compute_config_hash(cfg) == compute_config_hash({"b": "x", "a": 1})

    def test_config_hash_changes(self) -> None:
        assert compute_config_hash({"a": 1}) != compute_config_hash({"a": 2})

    def test_flatten_booleans_are_floats(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        flat = flatten_experiment_metrics(result.backtest_result, result.battery_report)
        assert flat["nb.future_leak_detected"] in (0.0, 1.0)
        assert all(isinstance(v, float) for v in flat.values())
