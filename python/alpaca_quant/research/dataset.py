"""Research dataset loader: align local bars + computed features for notebook research.

Local Parquet only. Uses Polars. No Alpaca API calls. No .env reads. No network.
No trading. No backtesting. No model training. No signal/label/target generation.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from alpaca_quant.data.parquet_writer import BAR_COLUMNS
from alpaca_quant.features.pipeline import FEATURE_NAMES

# Bars must carry the full OHLCV+ schema produced by the ingestion layer.
REQUIRED_BARS_COLUMNS: tuple[str, ...] = tuple(BAR_COLUMNS)

# Features must at minimum carry the join keys and provenance id.
REQUIRED_FEATURE_COLUMNS: tuple[str, ...] = ("symbol", "timestamp", "feature_set_id")

# Join keys shared by both frames.
JOIN_KEYS: tuple[str, ...] = ("symbol", "timestamp")

# Concepts that must never appear in a research dataset at this stage.
# (Exact names — substring matching would falsely flag e.g. `trade_count`.)
FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "target",
        "label",
        "y",
        "signal",
        "alpha",
        "prediction",
        "order",
        "trade",
        "side",
        "qty",
        "quantity",
        "weight",
        "position",
    }
)


class ResearchDatasetError(RuntimeError):
    """Raised when a research dataset cannot be built or validated safely."""


@dataclass(frozen=True)
class ResearchDatasetSummary:
    """Non-secret summary of an aligned research dataset."""

    row_count: int
    symbols: list[str]
    start: str | None
    end: str | None
    feature_columns: list[str]
    feature_column_count: int
    null_counts: dict[str, int]


def _validated_path(path: str | Path, kind: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise ResearchDatasetError(f"{kind} Parquet file not found: {resolved}")
    return resolved


def _require_columns(df: pl.DataFrame, required: Sequence[str], kind: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ResearchDatasetError(f"{kind} is missing required columns: {', '.join(missing)}")


def _reject_duplicates(df: pl.DataFrame, kind: str) -> None:
    key_df = df.select(JOIN_KEYS)
    if key_df.is_duplicated().any():
        raise ResearchDatasetError(f"{kind} contains duplicate symbol/timestamp rows")


def _normalized_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise ResearchDatasetError("symbol filter must be a non-empty string")
    return cleaned


def _normalized_date(value: str | date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ResearchDatasetError(
            f"{field_name} must be an ISO date string or date object"
        ) from exc


def load_research_dataset(
    bars_path: str | Path,
    features_path: str | Path,
    symbol: str | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
) -> pl.DataFrame:
    """Load and align local bars + features into one notebook-ready Polars DataFrame.

    - Reads local Parquet only; performs no network or Alpaca calls.
    - Inner-joins bars and features on (symbol, timestamp).
    - Validates required columns, rejects empty inputs and duplicate keys.
    - Optionally filters to one symbol and/or a date range.
    - Creates no target, label, signal, or order columns.
    """
    bars_file = _validated_path(bars_path, "bars")
    features_file = _validated_path(features_path, "features")

    bars = pl.read_parquet(bars_file)
    features = pl.read_parquet(features_file)

    if bars.is_empty():
        raise ResearchDatasetError("bars dataset is empty")
    if features.is_empty():
        raise ResearchDatasetError("features dataset is empty")

    _require_columns(bars, REQUIRED_BARS_COLUMNS, "bars")
    _require_columns(features, REQUIRED_FEATURE_COLUMNS, "features")

    _reject_duplicates(bars, "bars")
    _reject_duplicates(features, "features")

    target_symbol = _normalized_symbol(symbol)
    if target_symbol is not None:
        bars = bars.filter(pl.col("symbol") == target_symbol)
        features = features.filter(pl.col("symbol") == target_symbol)
        if bars.is_empty():
            raise ResearchDatasetError(f"bars dataset has no rows for symbol {target_symbol!r}")
        if features.is_empty():
            raise ResearchDatasetError(
                f"features dataset has no rows for symbol {target_symbol!r}"
            )

    bar_symbols = set(bars["symbol"].unique().to_list())
    feature_symbols = set(features["symbol"].unique().to_list())
    if bar_symbols.isdisjoint(feature_symbols):
        raise ResearchDatasetError(
            "bars and features have no overlapping symbols: "
            f"bars={sorted(bar_symbols)} features={sorted(feature_symbols)}"
        )

    start_date = _normalized_date(start, "start")
    end_date = _normalized_date(end, "end")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ResearchDatasetError("end date must be on or after start date")
    if start_date is not None:
        bars = bars.filter(pl.col("timestamp").dt.date() >= start_date)
        features = features.filter(pl.col("timestamp").dt.date() >= start_date)
    if end_date is not None:
        bars = bars.filter(pl.col("timestamp").dt.date() <= end_date)
        features = features.filter(pl.col("timestamp").dt.date() <= end_date)

    # Pull only join keys, provenance, and known feature columns from the features frame
    # so OHLCV columns are not duplicated by the join.
    feature_value_columns = [c for c in FEATURE_NAMES if c in features.columns]
    feature_select = list(JOIN_KEYS) + ["feature_set_id"] + feature_value_columns
    features_slim = features.select(feature_select)

    joined = bars.join(features_slim, on=list(JOIN_KEYS), how="inner")

    if joined.is_empty():
        raise ResearchDatasetError(
            "aligned dataset is empty after joining bars and features on symbol/timestamp"
        )

    forbidden_present = sorted(c for c in joined.columns if c in FORBIDDEN_COLUMNS)
    if forbidden_present:
        raise ResearchDatasetError(
            f"research dataset must not contain trading/label columns: {forbidden_present}"
        )

    return joined.sort(list(JOIN_KEYS))


def summarize_research_dataset(df: pl.DataFrame) -> ResearchDatasetSummary:
    """Return a non-secret summary of an aligned research dataset."""
    if df.is_empty():
        raise ResearchDatasetError("cannot summarize an empty research dataset")

    _require_columns(df, JOIN_KEYS, "dataset")

    feature_columns = [c for c in FEATURE_NAMES if c in df.columns]
    null_counts = {c: int(df[c].null_count()) for c in feature_columns}

    ts = df["timestamp"]
    start = str(ts.min()) if len(df) else None
    end = str(ts.max()) if len(df) else None

    return ResearchDatasetSummary(
        row_count=len(df),
        symbols=sorted(df["symbol"].unique().to_list()),
        start=start,
        end=end,
        feature_columns=feature_columns,
        feature_column_count=len(feature_columns),
        null_counts=null_counts,
    )
