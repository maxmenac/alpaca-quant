"""Feature pipeline: computes all price features and emits a versioned feature set.

The point-in-time path `build_pit_feature_set(..., as_of=...)` is the official way to build
features: it reads bars through the PIT layer so no row after the knowledge cutoff can enter the
computation. `build_feature_set(...)` is a legacy raw-read path kept for backward compatibility
only — no new CLI or production path should call it.
"""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpaca_quant.data.pit.reader import load_pit_bars
from alpaca_quant.features.price.moving_averages import ema, sma
from alpaca_quant.features.price.returns import daily_returns, log_returns
from alpaca_quant.features.price.volatility import rolling_volatility
from alpaca_quant.features.price.volume import rolling_volume

SMA_WINDOWS = (5, 20)
EMA_WINDOWS = (5, 20)
VOL_WINDOW = 20
VOLUME_WINDOW = 20

FEATURE_NAMES = [
    "daily_return",
    "log_return",
    *(f"rolling_vol_{VOL_WINDOW}d",),
    *(f"sma_{w}d" for w in SMA_WINDOWS),
    *(f"ema_{w}d" for w in EMA_WINDOWS),
    f"rolling_vol_volume_{VOLUME_WINDOW}d",
]


def _make_feature_set_id(parquet_path: Path, symbol: str) -> str:
    """Semi-deterministic id: hash of path + symbol, no random component."""
    digest = hashlib.sha256(f"{parquet_path.resolve()}:{symbol}".encode()).hexdigest()[:8]
    return f"feat-{symbol.upper()}-{digest}"


def _make_pit_feature_set_id(parquet_path: Path, symbol: str, as_of: date) -> str:
    """Deterministic id sensitive to the as-of cutoff (distinct cutoffs => distinct ids)."""
    key = f"{parquet_path.resolve()}:{symbol}:{as_of.isoformat()}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"feat-{symbol.upper()}-{digest}"


def _compute_price_features(df: pl.DataFrame, feature_set_id: str) -> pl.DataFrame:
    """Compute all price features on one bars frame and tag it with `feature_set_id`.

    Pure transform: groups by symbol, sorts by timestamp, no lookahead. Early rows may contain
    nulls for window-based features. The caller is responsible for supplying lookahead-safe bars.
    """
    df = daily_returns(df)
    df = log_returns(df)
    df = rolling_volatility(df, window=VOL_WINDOW)
    for w in SMA_WINDOWS:
        df = sma(df, window=w)
    for w in EMA_WINDOWS:
        df = ema(df, window=w)
    df = rolling_volume(df, window=VOLUME_WINDOW)
    return df.with_columns(pl.lit(feature_set_id).alias("feature_set_id"))


def build_pit_feature_set(
    bars_path: str | Path,
    symbol: str,
    *,
    as_of: str | date,
) -> pl.DataFrame:
    """Official feature path: build features from point-in-time bars (no lookahead).

    Reads bars through the PIT layer (`load_pit_bars`), so no row dated after `as_of` can enter
    the computation. `as_of` is required. No Alpaca API calls. No .env reads. No network.
    """
    path = Path(bars_path)
    symbol_upper = symbol.strip().upper()
    bars = load_pit_bars(path, as_of=as_of, symbols=[symbol_upper])
    as_of_date = bars["timestamp"].dt.date().max()
    feature_set_id = _make_pit_feature_set_id(path, symbol_upper, as_of_date)
    return _compute_price_features(bars, feature_set_id)


def build_feature_set(parquet_path: str | Path, symbol: str) -> pl.DataFrame:
    """LEGACY raw-read path — kept for backward compatibility only.

    Reads raw Parquet directly with no as-of cutoff. The official path is
    `build_pit_feature_set(..., as_of=...)`; no new CLI or production path should call this.

    - Groups by symbol, sorts by timestamp — no lookahead within the data it reads.
    - Adds `feature_set_id` column to every row.
    - No Alpaca API calls. No .env reads. No network. No trading.
    """
    path = Path(parquet_path)
    if not path.is_file():
        raise FileNotFoundError(f"Parquet file not found: {path}")

    symbol_upper = symbol.strip().upper()
    df = pl.read_parquet(path).filter(pl.col("symbol") == symbol_upper)

    if df.is_empty():
        raise ValueError(f"No rows found for symbol {symbol_upper!r} in {path}")

    feature_set_id = _make_feature_set_id(path, symbol_upper)
    return _compute_price_features(df, feature_set_id)


def build_feature_manifest(
    parquet_path: str | Path,
    symbol: str,
    feature_df: pl.DataFrame,
    *,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """Build a manifest dict describing the feature set for auditability."""
    path = Path(parquet_path)
    symbol_upper = symbol.strip().upper()
    ts_col = feature_df["timestamp"]
    as_of_str = as_of.isoformat() if isinstance(as_of, date) else as_of

    return {
        "feature_set_id": feature_df["feature_set_id"][0],
        "input_parquet": str(path.resolve()),
        "symbol": symbol_upper,
        "as_of": as_of_str,
        "date_range": {
            "start": str(ts_col.min()),
            "end": str(ts_col.max()),
        },
        "feature_names": FEATURE_NAMES,
        "lookback_windows": {
            "rolling_vol": VOL_WINDOW,
            "sma": list(SMA_WINDOWS),
            "ema": list(EMA_WINDOWS),
            "rolling_vol_volume": VOLUME_WINDOW,
        },
        "row_count": len(feature_df),
        "generated_at": datetime.now(UTC).isoformat(),
        "no_trading": True,
    }
