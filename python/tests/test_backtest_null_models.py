"""Tests for null-model weight transforms. Synthetic in-memory only — no .env, no network."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.backtest.null_models import (
    NullBatteryError,
    future_leak_weights,
    random_weights,
    shifted_weights,
    shuffled_weights,
)


def _frame(closes, weights, symbol: str = "AAPL") -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": [float(c) for c in closes],
            "weight": [float(w) for w in weights],
        }
    )


def _is_finite(series: pl.Series) -> bool:
    s = series.cast(pl.Float64)
    return not (s.is_null().any() or s.is_nan().any() or s.is_infinite().any())


class TestRandomWeights:
    def test_deterministic_same_seed(self) -> None:
        df = _frame([100, 110, 121, 130], [1, 1, 1, 1])
        a = random_weights(df, seed=7)["weight"].to_list()
        b = random_weights(df, seed=7)["weight"].to_list()
        assert a == b

    def test_different_seed_differs(self) -> None:
        df = _frame([100, 110, 121, 130], [1, 1, 1, 1])
        a = random_weights(df, seed=7)["weight"].to_list()
        b = random_weights(df, seed=8)["weight"].to_list()
        assert a != b

    def test_within_bounds_and_finite(self) -> None:
        df = _frame([100, 110, 121, 130], [1, 1, 1, 1])
        out = random_weights(df, seed=7, low=-0.5, high=0.5)
        assert _is_finite(out["weight"])
        assert out["weight"].min() >= -0.5
        assert out["weight"].max() <= 0.5

    def test_row_count_and_other_columns_preserved(self) -> None:
        df = _frame([100, 110, 121], [1, 1, 1])
        out = random_weights(df, seed=1)
        assert out.height == df.height
        assert out["close"].to_list() == df["close"].to_list()

    def test_high_below_low_rejected(self) -> None:
        df = _frame([100, 110], [1, 1])
        with pytest.raises(NullBatteryError, match="high must be >= low"):
            random_weights(df, seed=1, low=1.0, high=-1.0)


class TestShuffledWeights:
    def test_deterministic_same_seed(self) -> None:
        df = _frame([100, 110, 121, 130, 140], [1, 2, 3, 4, 5])
        a = shuffled_weights(df, seed=3)["weight"].to_list()
        b = shuffled_weights(df, seed=3)["weight"].to_list()
        assert a == b

    def test_is_permutation_of_input(self) -> None:
        df = _frame([100, 110, 121, 130, 140], [1, 2, 3, 4, 5])
        out = shuffled_weights(df, seed=3)["weight"].to_list()
        assert sorted(out) == sorted([1.0, 2.0, 3.0, 4.0, 5.0])

    def test_finite(self) -> None:
        df = _frame([100, 110, 121, 130], [1, 2, 3, 4])
        assert _is_finite(shuffled_weights(df, seed=9)["weight"])


class TestShiftedWeights:
    def test_shift_one_fills_first_with_zero(self) -> None:
        df = _frame([100, 110, 121, 130], [0.1, 0.2, 0.3, 0.4])
        out = shifted_weights(df).sort("timestamp")["weight"].to_list()
        assert out[0] == 0.0
        assert out[1] == pytest.approx(0.1)
        assert out[2] == pytest.approx(0.2)

    def test_per_symbol_independence(self) -> None:
        aapl = _frame([100, 110, 121], [0.1, 0.2, 0.3], symbol="AAPL")
        msft = _frame([200, 220, 242], [0.5, 0.6, 0.7], symbol="MSFT")
        out = shifted_weights(pl.concat([aapl, msft])).sort(["symbol", "timestamp"])
        a = out.filter(pl.col("symbol") == "AAPL")["weight"].to_list()
        m = out.filter(pl.col("symbol") == "MSFT")["weight"].to_list()
        assert a[0] == 0.0 and m[0] == 0.0
        assert a[1] == pytest.approx(0.1)
        assert m[1] == pytest.approx(0.5)

    def test_finite(self) -> None:
        df = _frame([100, 110, 121], [0.1, 0.2, 0.3])
        assert _is_finite(shifted_weights(df)["weight"])

    def test_periods_below_one_rejected(self) -> None:
        df = _frame([100, 110], [0.1, 0.2])
        with pytest.raises(NullBatteryError, match="periods must be at least 1"):
            shifted_weights(df, periods=0)


class TestFutureLeakWeights:
    def test_weights_are_signs(self) -> None:
        # up, down, up -> signs +1, -1, then last row unknown -> 0
        df = _frame([100, 110, 100, 120], [0, 0, 0, 0])
        out = future_leak_weights(df).sort("timestamp")["weight"].to_list()
        assert out[0] == 1.0  # 100 -> 110
        assert out[1] == -1.0  # 110 -> 100
        assert out[2] == 1.0  # 100 -> 120
        assert out[3] == 0.0  # last bar: forward unknown -> 0

    def test_values_in_allowed_set(self) -> None:
        df = _frame([100, 110, 100, 120, 115], [0, 0, 0, 0, 0])
        out = future_leak_weights(df)["weight"].to_list()
        assert set(out) <= {-1.0, 0.0, 1.0}

    def test_finite(self) -> None:
        df = _frame([100, 110, 100, 120], [0, 0, 0, 0])
        assert _is_finite(future_leak_weights(df)["weight"])

    def test_drops_internal_forward_column(self) -> None:
        df = _frame([100, 110, 121], [0, 0, 0])
        out = future_leak_weights(df)
        assert "_leak_forward_return" not in out.columns
