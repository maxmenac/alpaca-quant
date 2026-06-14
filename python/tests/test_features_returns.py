"""Tests for price return features. All fixtures are synthetic — no Alpaca API, no .env."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.features.price.returns import daily_returns, log_returns


def _make_bars(closes: list[float], symbol: str = "AAPL") -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [
                datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)
            ],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * n,
            "trade_count": [500] * n,
            "vwap": closes,
        }
    )


class TestDailyReturns:
    def test_first_row_is_null(self) -> None:
        df = daily_returns(_make_bars([100.0, 110.0, 121.0]))
        assert df.sort("timestamp")["daily_return"][0] is None

    def test_second_row_correct(self) -> None:
        df = daily_returns(_make_bars([100.0, 110.0])).sort("timestamp")
        assert df["daily_return"][1] == pytest.approx(0.10, rel=1e-6)

    def test_column_added(self) -> None:
        df = daily_returns(_make_bars([100.0, 200.0]))
        assert "daily_return" in df.columns

    def test_multiple_symbols_grouped(self) -> None:
        aapl = _make_bars([100.0, 110.0], symbol="AAPL")
        msft = _make_bars([200.0, 220.0], symbol="MSFT")
        combined = pl.concat([aapl, msft])
        result = daily_returns(combined).sort(["symbol", "timestamp"])

        aapl_rows = result.filter(pl.col("symbol") == "AAPL")["daily_return"]
        msft_rows = result.filter(pl.col("symbol") == "MSFT")["daily_return"]

        assert aapl_rows[0] is None
        assert aapl_rows[1] == pytest.approx(0.10, rel=1e-6)
        assert msft_rows[0] is None
        assert msft_rows[1] == pytest.approx(0.10, rel=1e-6)


class TestLogReturns:
    def test_first_row_is_null(self) -> None:
        df = log_returns(_make_bars([100.0, 110.0])).sort("timestamp")
        assert df["log_return"][0] is None

    def test_column_added(self) -> None:
        df = log_returns(_make_bars([100.0, 110.0]))
        assert "log_return" in df.columns

    def test_value_matches_manual(self) -> None:
        import math

        df = log_returns(_make_bars([100.0, 110.0])).sort("timestamp")
        expected = math.log(110.0 / 100.0)
        assert df["log_return"][1] == pytest.approx(expected, rel=1e-6)

    def test_multiple_symbols_grouped(self) -> None:
        aapl = _make_bars([100.0, 110.0], symbol="AAPL")
        msft = _make_bars([200.0, 220.0], symbol="MSFT")
        result = log_returns(pl.concat([aapl, msft])).sort(["symbol", "timestamp"])

        assert result.filter(pl.col("symbol") == "AAPL")["log_return"][0] is None
        assert result.filter(pl.col("symbol") == "MSFT")["log_return"][0] is None
