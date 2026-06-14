"""Tests for forward-return outcomes. Synthetic only — no .env, no network."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.backtest.outcomes import OutcomeError, forward_returns


def _bars(closes: list[float], symbol: str = "AAPL") -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": closes,
        }
    )


def test_forward_return_value() -> None:
    df = forward_returns(_bars([100.0, 110.0, 121.0])).sort("timestamp")
    vals = df["forward_return_1d"].to_list()
    assert vals[0] == pytest.approx(0.10)
    assert vals[1] == pytest.approx(0.10)
    assert vals[2] is None


def test_last_row_null_per_symbol() -> None:
    df = forward_returns(
        pl.concat([_bars([100.0, 110.0], "AAPL"), _bars([200.0, 210.0], "MSFT")])
    ).sort(["symbol", "timestamp"])
    aapl = df.filter(pl.col("symbol") == "AAPL")["forward_return_1d"].to_list()
    msft = df.filter(pl.col("symbol") == "MSFT")["forward_return_1d"].to_list()
    assert aapl[-1] is None
    assert msft[-1] is None
    assert aapl[0] == pytest.approx(0.10)
    assert msft[0] == pytest.approx(0.05)


def test_horizon_two() -> None:
    df = forward_returns(_bars([100.0, 110.0, 120.0, 130.0]), horizon=2).sort("timestamp")
    vals = df["forward_return_2d"].to_list()
    assert vals[0] == pytest.approx(120.0 / 100.0 - 1.0)
    assert vals[2] is None
    assert vals[3] is None


def test_default_column_name() -> None:
    df = forward_returns(_bars([100.0, 101.0]))
    assert "forward_return_1d" in df.columns


def test_custom_column_name() -> None:
    df = forward_returns(_bars([100.0, 101.0]), out_col="fwd")
    assert "fwd" in df.columns


def test_horizon_below_one_rejected() -> None:
    with pytest.raises(OutcomeError, match="horizon must be at least 1"):
        forward_returns(_bars([100.0, 101.0]), horizon=0)


def test_missing_price_column_rejected() -> None:
    df = _bars([100.0, 101.0]).drop("close")
    with pytest.raises(OutcomeError, match="requires column"):
        forward_returns(df)
