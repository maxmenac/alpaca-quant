"""No-lookahead validation: prove feature at row t is unaffected by future rows.

Strategy: compute features on a base series, then mutate only future rows and
assert that past feature values are unchanged.
"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from alpaca_quant.features.pipeline import build_feature_set
from alpaca_quant.features.price.moving_averages import ema, sma
from alpaca_quant.features.price.returns import daily_returns, log_returns
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
            "volume": [1_000_000] * n,
            "trade_count": [500] * n,
            "vwap": closes,
        }
    )


def _replace_future_rows(df: pl.DataFrame, from_row: int, new_close: float) -> pl.DataFrame:
    """Return a copy where all rows >= from_row have close replaced with new_close."""
    closes = df["close"].to_list()
    closes[from_row:] = [new_close] * (len(closes) - from_row)
    return df.with_columns(
        pl.Series("close", closes),
        pl.Series("open", closes),
        pl.Series("high", closes),
        pl.Series("low", closes),
        pl.Series("vwap", closes),
    )


class TestNoLookaheadReturns:
    def test_daily_return_row_t_unchanged_by_future(self) -> None:
        closes = [100.0 + i for i in range(10)]
        base = daily_returns(_make_bars(closes)).sort("timestamp")

        mutated_closes = closes[:5] + [9999.0] * 5
        mutated = daily_returns(_make_bars(mutated_closes)).sort("timestamp")

        for i in range(5):
            assert base["daily_return"][i] == mutated["daily_return"][i], (
                f"daily_return[{i}] changed after mutating future rows"
            )

    def test_log_return_row_t_unchanged_by_future(self) -> None:
        closes = [100.0 + i for i in range(10)]
        base = log_returns(_make_bars(closes)).sort("timestamp")

        mutated_closes = closes[:5] + [9999.0] * 5
        mutated = log_returns(_make_bars(mutated_closes)).sort("timestamp")

        for i in range(5):
            b = base["log_return"][i]
            m = mutated["log_return"][i]
            if b is None:
                assert m is None
            else:
                assert abs(b - m) < 1e-12, f"log_return[{i}] changed after mutating future rows"


class TestNoLookaheadSMA:
    def test_sma_past_rows_unchanged_by_future(self) -> None:
        closes = [float(i + 1) for i in range(15)]
        base = sma(_make_bars(closes), window=5).sort("timestamp")

        # mutate rows 8 onward
        mutated_closes = closes[:8] + [9999.0] * 7
        mutated = sma(_make_bars(mutated_closes), window=5).sort("timestamp")

        for i in range(8):
            b = base["sma_5d"][i]
            m = mutated["sma_5d"][i]
            if b is None:
                assert m is None
            else:
                assert abs(b - m) < 1e-10, f"sma_5d[{i}] changed after mutating future rows"

    def test_ema_past_rows_unchanged_by_future(self) -> None:
        closes = [float(i + 1) for i in range(15)]
        base = ema(_make_bars(closes), window=5).sort("timestamp")

        mutated_closes = closes[:8] + [9999.0] * 7
        mutated = ema(_make_bars(mutated_closes), window=5).sort("timestamp")

        for i in range(8):
            b = base["ema_5d"][i]
            m = mutated["ema_5d"][i]
            if b is None:
                assert m is None
            else:
                assert abs(b - m) < 1e-10, f"ema_5d[{i}] changed after mutating future rows"


class TestNoLookaheadVolatility:
    def test_rolling_vol_past_rows_unchanged_by_future(self) -> None:
        closes = [100.0 * (1.005**i) for i in range(30)]
        df_base = log_returns(_make_bars(closes))
        base = rolling_volatility(df_base, window=20).sort("timestamp")

        mutated_closes = closes[:22] + [9999.0] * 8
        df_mut = log_returns(_make_bars(mutated_closes))
        mutated = rolling_volatility(df_mut, window=20).sort("timestamp")

        for i in range(22):
            b = base["rolling_vol_20d"][i]
            m = mutated["rolling_vol_20d"][i]
            if b is None:
                assert m is None
            else:
                assert abs(b - m) < 1e-10, (
                    f"rolling_vol_20d[{i}] changed after mutating future rows"
                )


class TestNoLookaheadVolume:
    def test_rolling_volume_past_rows_unchanged_by_future(self) -> None:
        n = 25
        base_df = _make_bars([100.0] * n)
        base = rolling_volume(base_df, window=5).sort("timestamp")

        # mutate volume in rows 10 onward — build a fresh df with different volumes
        volumes = [1_000_000] * 10 + [999_999_999] * 15
        mutated_df = base_df.with_columns(pl.Series("volume", volumes))
        mutated = rolling_volume(mutated_df, window=5).sort("timestamp")

        for i in range(10):
            b = base["rolling_vol_volume_5d"][i]
            m = mutated["rolling_vol_volume_5d"][i]
            if b is None:
                assert m is None
            else:
                assert abs(b - m) < 1e-6, (
                    f"rolling_vol_volume_5d[{i}] changed after mutating future rows"
                )


class TestNoLookaheadPipeline:
    def test_pipeline_past_rows_unchanged_by_future(self, tmp_path: Path) -> None:
        closes = [100.0 * (1.005**i) for i in range(30)]
        n = len(closes)
        df = pl.DataFrame(
            {
                "symbol": ["AAPL"] * n,
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

        base_parquet = tmp_path / "base.parquet"
        df.write_parquet(base_parquet)
        base_result = build_feature_set(base_parquet, "AAPL").sort("timestamp")

        # mutate rows 22 onward
        mutated_closes = closes[:22] + [9999.0] * 8
        mutated_df = df.with_columns(
            pl.Series("close", mutated_closes),
            pl.Series("open", mutated_closes),
            pl.Series("high", mutated_closes),
            pl.Series("low", mutated_closes),
            pl.Series("vwap", mutated_closes),
        )
        mut_parquet = tmp_path / "mutated.parquet"
        mutated_df.write_parquet(mut_parquet)
        mut_result = build_feature_set(mut_parquet, "AAPL").sort("timestamp")

        feature_cols = [c for c in base_result.columns if c not in ("feature_set_id",)]
        for i in range(22):
            for col in feature_cols:
                b = base_result[col][i]
                m = mut_result[col][i]
                if b is None:
                    assert m is None, f"{col}[{i}]: base=None but mutated={m}"
                elif isinstance(b, float):
                    assert abs(b - m) < 1e-8, (
                        f"{col}[{i}] changed after mutating future rows: {b} != {m}"
                    )
                else:
                    assert b == m, f"{col}[{i}] changed: {b} != {m}"
