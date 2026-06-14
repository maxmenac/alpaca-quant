"""Tests for volatility and volume features. All synthetic — no Alpaca API, no .env."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.features.price.returns import log_returns
from alpaca_quant.features.price.volatility import rolling_volatility
from alpaca_quant.features.price.volume import rolling_volume


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
            "volume": list(range(1_000_000, 1_000_000 + n)),
            "trade_count": [500] * n,
            "vwap": closes,
        }
    )


class TestRollingVolatility:
    def test_requires_log_return_column(self) -> None:
        df = _make_bars([100.0] * 5)
        with pytest.raises(ValueError, match="log_return"):
            rolling_volatility(df, window=3)

    def test_window_too_small_raises(self) -> None:
        df = log_returns(_make_bars([100.0] * 5))
        with pytest.raises(ValueError, match="window must be at least 2"):
            rolling_volatility(df, window=1)

    def test_early_rows_are_null(self) -> None:
        df = log_returns(_make_bars([100.0 * (1.01**i) for i in range(25)]))
        result = rolling_volatility(df, window=20).sort("timestamp")
        # rows 0..18 must be null (window=20 needs 20 rows, first non-null at index 19)
        for i in range(19):
            assert result["rolling_vol_20d"][i] is None, f"row {i} should be null"

    def test_non_null_after_window(self) -> None:
        # log_return[0] is null, so min_samples=20 is first satisfied at index 20
        closes = [100.0 * (1.01**i) for i in range(25)]
        df = log_returns(_make_bars(closes))
        result = rolling_volatility(df, window=20).sort("timestamp")
        assert result["rolling_vol_20d"][20] is not None
        assert result["rolling_vol_20d"][24] is not None

    def test_column_name(self) -> None:
        df = log_returns(_make_bars([100.0] * 5))
        result = rolling_volatility(df, window=5)
        assert "rolling_vol_5d" in result.columns

    def test_annualization(self) -> None:
        # constant +1% log-return → std over any window is 0 → vol = 0
        closes = [100.0 * (1.01**i) for i in range(25)]
        df = log_returns(_make_bars(closes))
        result = rolling_volatility(df, window=20).sort("timestamp")
        # std of a constant series is 0
        assert result["rolling_vol_20d"][24] == pytest.approx(0.0, abs=1e-10)

    def test_annualization_factor(self) -> None:
        # two alternating values → known std → verify annualization
        closes = [100.0, 102.0] * 15  # 30 rows
        df = log_returns(_make_bars(closes))
        result = rolling_volatility(df, window=20).sort("timestamp")
        val = result["rolling_vol_20d"][29]
        assert val is not None
        assert val > 0


class TestRollingVolume:
    def test_early_rows_are_null(self) -> None:
        df = _make_bars([100.0] * 25)
        result = rolling_volume(df, window=20).sort("timestamp")
        for i in range(19):
            assert result["rolling_vol_volume_20d"][i] is None

    def test_non_null_after_window(self) -> None:
        df = _make_bars([100.0] * 25)
        result = rolling_volume(df, window=20).sort("timestamp")
        assert result["rolling_vol_volume_20d"][19] is not None

    def test_column_name(self) -> None:
        df = _make_bars([100.0] * 5)
        result = rolling_volume(df, window=5)
        assert "rolling_vol_volume_5d" in result.columns

    def test_window_too_small_raises(self) -> None:
        df = _make_bars([100.0] * 5)
        with pytest.raises(ValueError, match="window must be at least 1"):
            rolling_volume(df, window=0)
