"""Tests for moving average features. All synthetic — no Alpaca API, no .env."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.features.price.moving_averages import ema, sma


def _make_bars(closes: list[float], symbol: str = "AAPL") -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * n,
            "trade_count": [500] * n,
            "vwap": closes,
        }
    )


class TestSMA:
    def test_early_rows_null(self) -> None:
        df = sma(_make_bars([100.0] * 10), window=5).sort("timestamp")
        for i in range(4):
            assert df["sma_5d"][i] is None

    def test_value_correct(self) -> None:
        closes = [10.0, 20.0, 30.0, 40.0, 50.0]
        df = sma(_make_bars(closes), window=5).sort("timestamp")
        assert df["sma_5d"][4] == pytest.approx(30.0, rel=1e-6)

    def test_column_name(self) -> None:
        df = sma(_make_bars([100.0] * 5), window=3)
        assert "sma_3d" in df.columns

    def test_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be at least 1"):
            sma(_make_bars([100.0] * 5), window=0)

    def test_constant_series(self) -> None:
        df = sma(_make_bars([50.0] * 10), window=5).sort("timestamp")
        assert df["sma_5d"][4] == pytest.approx(50.0, rel=1e-6)


class TestEMA:
    def test_early_rows_null(self) -> None:
        df = ema(_make_bars([100.0] * 10), window=5).sort("timestamp")
        for i in range(4):
            assert df["ema_5d"][i] is None

    def test_column_name(self) -> None:
        df = ema(_make_bars([100.0] * 5), window=3)
        assert "ema_3d" in df.columns

    def test_non_null_after_window(self) -> None:
        df = ema(_make_bars([100.0] * 10), window=5).sort("timestamp")
        assert df["ema_5d"][4] is not None

    def test_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be at least 1"):
            ema(_make_bars([100.0] * 5), window=0)

    def test_constant_series(self) -> None:
        df = ema(_make_bars([50.0] * 10), window=5).sort("timestamp")
        assert df["ema_5d"][4] == pytest.approx(50.0, rel=1e-4)
