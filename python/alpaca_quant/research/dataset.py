"""Research dataset loader: align local bars + computed features for notebook research.

Local Parquet only. Uses Polars. No Alpaca API calls. No .env reads. No network.
No trading. No backtesting. No model training. No signal/label/target generation.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
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


@dataclass(frozen=True)
class ResearchDatasetManifest:
    """Lightweight, non-secret manifest describing a built research dataset."""

    dataset_id: str
    created_at: str
    symbols: list[str]
    start: str | None
    end: str | None
    as_of: str | None
    bars_path: str
    features_paths: list[str]
    row_count: int
    feature_count: int
    known_gaps: list[str] = field(default_factory=list)
    no_trading: bool = True
    no_backtesting: bool = True
    no_model_training: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _validated_path(path: str | Path, kind: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise ResearchDatasetError(f"{kind} Parquet file not found: {resolved}")
    return resolved


def _as_path_list(paths: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(paths, (str, Path)):
        items: list[str | Path] = [paths]
    else:
        items = list(paths)
    if not items:
        raise ResearchDatasetError("at least one features path is required")
    return [Path(p) for p in items]


def _require_columns(df: pl.DataFrame, required: Sequence[str], kind: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ResearchDatasetError(f"{kind} is missing required columns: {', '.join(missing)}")


def _reject_duplicates(df: pl.DataFrame, kind: str) -> None:
    key_df = df.select(JOIN_KEYS)
    if key_df.is_duplicated().any():
        raise ResearchDatasetError(f"{kind} contains duplicate symbol/timestamp rows")


def _normalized_symbols(
    symbol: str | Sequence[str] | None,
) -> list[str] | None:
    if symbol is None:
        return None
    raw = [symbol] if isinstance(symbol, str) else list(symbol)
    normalized: list[str] = []
    for s in raw:
        if not isinstance(s, str):
            raise ResearchDatasetError("symbol filter entries must be strings")
        cleaned = s.strip().upper()
        if not cleaned:
            raise ResearchDatasetError("symbol filter must not contain empty strings")
        normalized.append(cleaned)
    if not normalized:
        raise ResearchDatasetError("symbol filter must contain at least one symbol")
    # de-duplicate while preserving order
    seen: set[str] = set()
    unique = [s for s in normalized if not (s in seen or seen.add(s))]
    return unique


def _normalized_date(value: str | date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ResearchDatasetError(
            f"{field_name} must be an ISO date string or date object"
        ) from exc


def _read_features(features_files: list[Path]) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    feature_value_columns_seen: list[str] | None = None
    for f in features_files:
        frame = pl.read_parquet(f)
        if frame.is_empty():
            raise ResearchDatasetError(f"features dataset is empty: {f}")
        _require_columns(frame, REQUIRED_FEATURE_COLUMNS, "features")
        value_cols = [c for c in FEATURE_NAMES if c in frame.columns]
        slim = frame.select(list(JOIN_KEYS) + ["feature_set_id"] + value_cols)
        if feature_value_columns_seen is None:
            feature_value_columns_seen = value_cols
        elif value_cols != feature_value_columns_seen:
            raise ResearchDatasetError(
                "features files have mismatched feature columns; cannot combine: "
                f"{feature_value_columns_seen} vs {value_cols}"
            )
        frames.append(slim)
    combined = pl.concat(frames, how="vertical")
    return combined


def load_research_dataset(
    bars_path: str | Path,
    features_path: str | Path | Sequence[str | Path],
    symbol: str | Sequence[str] | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    as_of: str | date | None = None,
) -> pl.DataFrame:
    """Load and align local bars + features into one notebook-ready Polars DataFrame.

    - Reads local Parquet only; performs no network or Alpaca calls.
    - Accepts one or many features files (one per symbol is typical).
    - Inner-joins bars and features on (symbol, timestamp).
    - Validates required columns, rejects empty inputs and duplicate keys.
    - Optionally filters to one or more symbols and/or a date range.
    - `as_of` is an inclusive upper bound on the date: no rows after it are returned
      (lookahead guard). It composes with `end` (both bounds are applied).
    - Creates no target, label, signal, or order columns.
    - Deterministic ordering: sorted by (symbol, timestamp).
    """
    bars_file = _validated_path(bars_path, "bars")
    features_files = [_validated_path(p, "features") for p in _as_path_list(features_path)]

    bars = pl.read_parquet(bars_file)
    if bars.is_empty():
        raise ResearchDatasetError("bars dataset is empty")
    _require_columns(bars, REQUIRED_BARS_COLUMNS, "bars")
    _reject_duplicates(bars, "bars")

    features = _read_features(features_files)
    _reject_duplicates(features, "features")

    target_symbols = _normalized_symbols(symbol)
    if target_symbols is not None:
        bar_symbol_set = set(bars["symbol"].unique().to_list())
        feature_symbol_set = set(features["symbol"].unique().to_list())
        missing_in_bars = [s for s in target_symbols if s not in bar_symbol_set]
        missing_in_features = [s for s in target_symbols if s not in feature_symbol_set]
        if missing_in_bars:
            raise ResearchDatasetError(
                f"bars dataset has no rows for symbol(s): {missing_in_bars}"
            )
        if missing_in_features:
            raise ResearchDatasetError(
                f"features dataset has no rows for symbol(s): {missing_in_features}"
            )
        bars = bars.filter(pl.col("symbol").is_in(target_symbols))
        features = features.filter(pl.col("symbol").is_in(target_symbols))

    bar_symbols = set(bars["symbol"].unique().to_list())
    feature_symbols = set(features["symbol"].unique().to_list())
    if bar_symbols.isdisjoint(feature_symbols):
        raise ResearchDatasetError(
            "bars and features have no overlapping symbols: "
            f"bars={sorted(bar_symbols)} features={sorted(feature_symbols)}"
        )

    start_date = _normalized_date(start, "start")
    end_date = _normalized_date(end, "end")
    as_of_date = _normalized_date(as_of, "as_of")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ResearchDatasetError("end date must be on or after start date")
    if start_date is not None and as_of_date is not None and as_of_date < start_date:
        raise ResearchDatasetError("as_of date must be on or after start date")

    if start_date is not None:
        bars = bars.filter(pl.col("timestamp").dt.date() >= start_date)
        features = features.filter(pl.col("timestamp").dt.date() >= start_date)
    if end_date is not None:
        bars = bars.filter(pl.col("timestamp").dt.date() <= end_date)
        features = features.filter(pl.col("timestamp").dt.date() <= end_date)
    if as_of_date is not None:
        # inclusive upper bound — no rows after as_of (lookahead guard)
        bars = bars.filter(pl.col("timestamp").dt.date() <= as_of_date)
        features = features.filter(pl.col("timestamp").dt.date() <= as_of_date)

    joined = bars.join(features, on=list(JOIN_KEYS), how="inner")

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


def _make_dataset_id(
    bars_path: str,
    symbols: Sequence[str],
    start: str | None,
    end: str | None,
    as_of: str | None,
) -> str:
    """Semi-deterministic id: hash of inputs, no random component."""
    key = f"{bars_path}|{','.join(symbols)}|{start}|{end}|{as_of}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"rds-{digest}"


def build_research_dataset_manifest(
    df: pl.DataFrame,
    bars_path: str | Path,
    features_path: str | Path | Sequence[str | Path],
    *,
    as_of: str | date | None = None,
    known_gaps: Sequence[str] | None = None,
) -> ResearchDatasetManifest:
    """Build a lightweight, non-secret manifest for a built research dataset."""
    summary = summarize_research_dataset(df)
    bars_resolved = str(Path(bars_path).resolve())
    features_resolved = [str(p.resolve()) for p in _as_path_list(features_path)]
    as_of_date = _normalized_date(as_of, "as_of")
    as_of_str = as_of_date.isoformat() if as_of_date is not None else None

    dataset_id = _make_dataset_id(
        bars_resolved, summary.symbols, summary.start, summary.end, as_of_str
    )

    return ResearchDatasetManifest(
        dataset_id=dataset_id,
        created_at=datetime.now(UTC).isoformat(),
        symbols=summary.symbols,
        start=summary.start,
        end=summary.end,
        as_of=as_of_str,
        bars_path=bars_resolved,
        features_paths=features_resolved,
        row_count=summary.row_count,
        feature_count=summary.feature_column_count,
        known_gaps=list(known_gaps or []),
    )
