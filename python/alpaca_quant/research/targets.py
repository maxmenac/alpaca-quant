"""Forward-return target labels for offline research.

Labels are realized future outcomes, never features, signals, alpha, predictions, or weights.
This module is local and deterministic: no network, no Alpaca API, no .env, no persistence.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl

SYMBOL_COL = "symbol"
TIMESTAMP_COL = "timestamp"
NULL_REASON_COL = "target_null_reason"
LABEL_PREFIX = "label_forward_return"

FORBIDDEN_INPUT_COLUMNS: frozenset[str] = frozenset(
    {
        "alpha",
        "order",
        "position",
        "prediction",
        "qty",
        "quantity",
        "side",
        "signal",
        "target",
        "target_weight",
        "trade",
        "weight",
    }
)

_FUTURE_PRICE_COL = "_target_future_price"
_FUTURE_TIMESTAMP_COL = "_target_future_timestamp"


class TargetLabelError(RuntimeError):
    """Raised when forward-return labels cannot be built or audited safely."""


@dataclass(frozen=True)
class TargetLabelSummary:
    """Non-secret audit summary for a labelled frame."""

    row_count: int
    valid_label_count: int
    null_label_count: int
    null_fraction: float
    null_breakdown: dict[str, int]
    symbols: list[str]
    start: str | None
    end: str | None
    label_column: str


@dataclass(frozen=True)
class TargetManifest:
    """Deterministic target definition plus non-secret label audit metadata."""

    target_id: str
    created_at: str
    fingerprint: str
    source_dataset_id: str | None
    label_kind: str
    label_column: str
    price_column: str
    horizon: int
    row_count: int
    valid_label_count: int
    null_label_count: int
    null_breakdown: dict[str, int]
    symbols: list[str]
    start: str | None
    end: str | None
    known_gaps: list[str] = field(default_factory=list)
    no_alpha: bool = True
    no_strategy: bool = True
    no_model_training: bool = True
    no_signal_generation: bool = True
    no_weights: bool = True
    no_trading: bool = True
    no_order_submission: bool = True
    no_api_calls: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label_column(horizon: int, label_col: str | None) -> str:
    if label_col is not None:
        if not isinstance(label_col, str) or not label_col.strip():
            raise TargetLabelError("label_col must be a non-empty string")
        cleaned = label_col.strip()
        reserved = FORBIDDEN_INPUT_COLUMNS | {
            SYMBOL_COL,
            TIMESTAMP_COL,
            NULL_REASON_COL,
        }
        if cleaned in reserved:
            raise TargetLabelError(f"label_col {cleaned!r} is reserved")
        return cleaned
    return f"{LABEL_PREFIX}_{horizon}d"


def _validate_horizon(horizon: int) -> None:
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise TargetLabelError("horizon must be an integer of at least 1")


def _require_columns(df: pl.DataFrame, required: tuple[str, ...]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise TargetLabelError(f"target input is missing required columns: {', '.join(missing)}")


def _validate_target_input(
    df: pl.DataFrame,
    *,
    horizon: int,
    price_col: str,
    label_col: str,
) -> None:
    _validate_horizon(horizon)
    if not isinstance(price_col, str) or not price_col.strip():
        raise TargetLabelError("price_col must be a non-empty string")
    if df.is_empty():
        raise TargetLabelError("target input is empty")

    _require_columns(df, (SYMBOL_COL, TIMESTAMP_COL, price_col))
    if label_col in df.columns or NULL_REASON_COL in df.columns:
        raise TargetLabelError("target input already contains target output columns")

    forbidden = sorted(
        column
        for column in df.columns
        if column in FORBIDDEN_INPUT_COLUMNS
        or column == "label"
        or column.startswith("label_")
        or column.startswith("target_")
    )
    if forbidden:
        raise TargetLabelError(
            f"target input must not contain strategy or existing label columns: {forbidden}"
        )

    if df.schema[SYMBOL_COL] != pl.String:
        raise TargetLabelError("symbol column must use string values")
    if df[SYMBOL_COL].null_count() > 0:
        raise TargetLabelError("symbol column must not contain nulls")
    if df.filter(pl.col(SYMBOL_COL).str.strip_chars() == "").height > 0:
        raise TargetLabelError("symbol column must not contain blank values")

    if not df.schema[TIMESTAMP_COL].is_temporal():
        raise TargetLabelError("timestamp column must use a date or datetime type")
    if df[TIMESTAMP_COL].null_count() > 0:
        raise TargetLabelError("timestamp column must not contain nulls")
    if df.select([SYMBOL_COL, TIMESTAMP_COL]).is_duplicated().any():
        raise TargetLabelError("target input contains duplicate symbol/timestamp rows")

    if not df.schema[price_col].is_numeric():
        raise TargetLabelError(f"price column {price_col!r} must be numeric")
    prices = df[price_col].drop_nulls().cast(pl.Float64)
    if prices.is_empty():
        raise TargetLabelError(f"price column {price_col!r} contains no usable values")
    if prices.is_nan().any() or prices.is_infinite().any():
        raise TargetLabelError(f"price column {price_col!r} must contain only finite values")
    if (prices <= 0).any():
        raise TargetLabelError(f"price column {price_col!r} must contain positive values")


def build_forward_return_labels(
    df: pl.DataFrame,
    *,
    horizon: int = 1,
    price_col: str = "close",
    label_col: str | None = None,
) -> pl.DataFrame:
    """Add simple forward-return labels using a per-symbol future shift.

    The output is stably sorted by ``(symbol, timestamp)``. For each row ``t``:

    ``label[t] = price[t + horizon] / price[t] - 1``

    The final ``horizon`` rows of every symbol remain null because their future outcome is
    unknown. Nulls are never filled with zero. ``target_null_reason`` records why each label is
    unavailable.
    """
    resolved_label_col = _label_column(horizon, label_col)
    _validate_target_input(
        df,
        horizon=horizon,
        price_col=price_col,
        label_col=resolved_label_col,
    )

    ordered = df.sort([SYMBOL_COL, TIMESTAMP_COL], maintain_order=True)
    prepared = ordered.with_columns(
        pl.col(price_col)
        .cast(pl.Float64)
        .shift(-horizon)
        .over(SYMBOL_COL)
        .alias(_FUTURE_PRICE_COL),
        pl.col(TIMESTAMP_COL)
        .shift(-horizon)
        .over(SYMBOL_COL)
        .alias(_FUTURE_TIMESTAMP_COL),
    )
    result = prepared.with_columns(
        (
            pl.col(_FUTURE_PRICE_COL) / pl.col(price_col).cast(pl.Float64) - 1.0
        ).alias(resolved_label_col),
        pl.when(pl.col(price_col).is_null())
        .then(pl.lit("source_price_null"))
        .when(pl.col(_FUTURE_TIMESTAMP_COL).is_null())
        .then(pl.lit("insufficient_future_rows"))
        .when(pl.col(_FUTURE_PRICE_COL).is_null())
        .then(pl.lit("future_price_null"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias(NULL_REASON_COL),
    ).drop([_FUTURE_PRICE_COL, _FUTURE_TIMESTAMP_COL])

    _validate_label_output(result, resolved_label_col)
    return result


def _validate_label_output(df: pl.DataFrame, label_col: str) -> None:
    _require_columns(df, (SYMBOL_COL, TIMESTAMP_COL, label_col, NULL_REASON_COL))
    if df.is_empty():
        raise TargetLabelError("labelled target frame is empty")

    labels = df[label_col].drop_nulls().cast(pl.Float64)
    if labels.is_nan().any() or labels.is_infinite().any():
        raise TargetLabelError("target labels must contain only finite values or null")

    missing_reason = df.filter(
        pl.col(label_col).is_null() & pl.col(NULL_REASON_COL).is_null()
    )
    unexpected_reason = df.filter(
        pl.col(label_col).is_not_null() & pl.col(NULL_REASON_COL).is_not_null()
    )
    if not missing_reason.is_empty() or not unexpected_reason.is_empty():
        raise TargetLabelError("target label null-reason ledger is inconsistent")


def summarize_target_labels(
    df: pl.DataFrame,
    *,
    label_col: str,
) -> TargetLabelSummary:
    """Summarize label coverage and the explicit null-reason breakdown."""
    _validate_label_output(df, label_col)
    ordered = df.sort([SYMBOL_COL, TIMESTAMP_COL], maintain_order=True)
    null_rows = ordered.filter(pl.col(label_col).is_null())
    breakdown = {
        str(row[NULL_REASON_COL]): int(row["len"])
        for row in null_rows.group_by(NULL_REASON_COL).len().sort(NULL_REASON_COL).to_dicts()
    }
    row_count = len(ordered)
    null_count = len(null_rows)
    timestamps = ordered[TIMESTAMP_COL]
    return TargetLabelSummary(
        row_count=row_count,
        valid_label_count=row_count - null_count,
        null_label_count=null_count,
        null_fraction=null_count / row_count,
        null_breakdown=breakdown,
        symbols=sorted(ordered[SYMBOL_COL].unique().to_list()),
        start=str(timestamps.min()) if row_count else None,
        end=str(timestamps.max()) if row_count else None,
        label_column=label_col,
    )


def _canonical_timestamp(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def fingerprint_target_labels(
    df: pl.DataFrame,
    *,
    horizon: int,
    price_col: str = "close",
    label_col: str | None = None,
) -> str:
    """Return a deterministic sha256 fingerprint for the target definition and labels."""
    _validate_horizon(horizon)
    resolved_label_col = _label_column(horizon, label_col)
    _require_columns(df, (SYMBOL_COL, TIMESTAMP_COL, price_col))
    _validate_label_output(df, resolved_label_col)

    rows = []
    for row in df.sort([SYMBOL_COL, TIMESTAMP_COL], maintain_order=True).select(
        [SYMBOL_COL, TIMESTAMP_COL, price_col, resolved_label_col, NULL_REASON_COL]
    ).iter_rows(named=True):
        rows.append(
            {
                "symbol": row[SYMBOL_COL],
                "timestamp": _canonical_timestamp(row[TIMESTAMP_COL]),
                "price": row[price_col],
                "label": row[resolved_label_col],
                "null_reason": row[NULL_REASON_COL],
            }
        )

    canonical = json.dumps(
        {
            "schema_version": 1,
            "label_kind": "forward_return",
            "horizon": horizon,
            "price_column": price_col,
            "label_column": resolved_label_col,
            "rows": rows,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def build_target_manifest(
    df: pl.DataFrame,
    *,
    horizon: int,
    price_col: str = "close",
    label_col: str | None = None,
    source_dataset_id: str | None = None,
    known_gaps: list[str] | None = None,
) -> TargetManifest:
    """Build a non-secret manifest for an in-memory forward-return label frame."""
    resolved_label_col = _label_column(horizon, label_col)
    if source_dataset_id is not None and not source_dataset_id.strip():
        raise TargetLabelError("source_dataset_id must be non-empty when provided")
    summary = summarize_target_labels(df, label_col=resolved_label_col)
    fingerprint = fingerprint_target_labels(
        df,
        horizon=horizon,
        price_col=price_col,
        label_col=resolved_label_col,
    )
    digest = fingerprint.removeprefix("sha256:")
    return TargetManifest(
        target_id=f"tgt-{digest[:12]}",
        created_at=datetime.now(UTC).isoformat(),
        fingerprint=fingerprint,
        source_dataset_id=source_dataset_id,
        label_kind="forward_return",
        label_column=resolved_label_col,
        price_column=price_col,
        horizon=horizon,
        row_count=summary.row_count,
        valid_label_count=summary.valid_label_count,
        null_label_count=summary.null_label_count,
        null_breakdown=summary.null_breakdown,
        symbols=summary.symbols,
        start=summary.start,
        end=summary.end,
        known_gaps=list(known_gaps or []),
    )
