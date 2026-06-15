"""Phase 4C point-in-time joins: PIT universe membership, as-of reference joins, identity.

All logic is local, deterministic, and anti-leakage. It answers "what was knowable at t",
never "what is the latest known value". No network, no Alpaca API, no .env, no model, no alpha.
"""

from collections.abc import Sequence
from typing import Any

import polars as pl

from alpaca_quant.research.targets import SYMBOL_COL, TIMESTAMP_COL

VALID_FROM_COL = "valid_from"
VALID_TO_COL = "valid_to"
AVAILABLE_AT_COL = "available_at"

UNIVERSE_STATUS_COL = "universe_status"
PERMANENT_ID_COL = "permanent_id"

# universe_status values
UNIVERSE_IN = "in_universe"
UNIVERSE_OUT = "not_in_universe"
UNIVERSE_MISSING = "no_universe_data"


class PitJoinError(RuntimeError):
    """Raised when a point-in-time join or membership check cannot be performed safely."""


def _require_columns(df: pl.DataFrame, required: Sequence[str], *, label: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise PitJoinError(f"{label} is missing required columns: {', '.join(missing)}")


def _require_temporal(df: pl.DataFrame, column: str, *, label: str) -> None:
    if not df.schema[column].is_temporal():
        raise PitJoinError(f"{label} column {column!r} must be a date or datetime type")


def annotate_universe_membership(
    df: pl.DataFrame,
    universe: pl.DataFrame | None,
    *,
    id_column: str = SYMBOL_COL,
) -> pl.DataFrame:
    """Add a ``universe_status`` column: in_universe / not_in_universe / no_universe_data.

    A row ``(id, timestamp)`` is ``in_universe`` only if some universe interval covers it:
    ``valid_from <= timestamp`` and (``valid_to`` is null/open or ``timestamp <= valid_to``).
    Delisted ids stay present until valid_to; not-yet-listed ids are out before valid_from.
    """
    _require_columns(df, (id_column, TIMESTAMP_COL), label="panel")
    _require_temporal(df, TIMESTAMP_COL, label="panel")

    if universe is None:
        return df.with_columns(pl.lit(UNIVERSE_MISSING).alias(UNIVERSE_STATUS_COL))

    _require_columns(
        universe, (id_column, VALID_FROM_COL, VALID_TO_COL), label="universe table"
    )
    _require_temporal(universe, VALID_FROM_COL, label="universe table")
    if universe[VALID_FROM_COL].null_count() > 0:
        raise PitJoinError("universe valid_from must not contain nulls")
    if not universe[VALID_TO_COL].dtype.is_temporal():
        raise PitJoinError("universe valid_to must be a date or datetime type (nulls = open)")
    contradictions = universe.filter(
        pl.col(VALID_TO_COL).is_not_null() & (pl.col(VALID_TO_COL) < pl.col(VALID_FROM_COL))
    )
    if not contradictions.is_empty():
        raise PitJoinError("universe contains intervals where valid_to < valid_from")

    intervals = universe.select([id_column, VALID_FROM_COL, VALID_TO_COL])
    joined = df.join(intervals, on=id_column, how="left")
    covers = (
        pl.col(VALID_FROM_COL).is_not_null()
        & (pl.col(VALID_FROM_COL) <= pl.col(TIMESTAMP_COL))
        & (pl.col(VALID_TO_COL).is_null() | (pl.col(TIMESTAMP_COL) <= pl.col(VALID_TO_COL)))
    )
    membership = (
        joined.with_columns(covers.alias("_covered"))
        .group_by(df.columns, maintain_order=True)
        .agg(pl.col("_covered").any().alias("_any_cover"))
    )
    return membership.with_columns(
        pl.when(pl.col("_any_cover").fill_null(False))
        .then(pl.lit(UNIVERSE_IN))
        .otherwise(pl.lit(UNIVERSE_OUT))
        .alias(UNIVERSE_STATUS_COL)
    ).drop("_any_cover")


def resolve_permanent_ids(
    df: pl.DataFrame,
    identity: pl.DataFrame | None,
    *,
    id_column: str = SYMBOL_COL,
) -> pl.DataFrame:
    """Map ticker -> permanent_id using date-bounded identity intervals.

    Never merges two tickers without overlapping valid_from/valid_to bounds. When no identity
    table is supplied the permanent_id falls back to the raw id (documented limitation).
    """
    _require_columns(df, (id_column, TIMESTAMP_COL), label="panel")

    if identity is None:
        return df.with_columns(pl.col(id_column).alias(PERMANENT_ID_COL))

    _require_columns(
        identity,
        (PERMANENT_ID_COL, id_column, VALID_FROM_COL, VALID_TO_COL),
        label="identity table",
    )
    _require_temporal(identity, VALID_FROM_COL, label="identity table")
    if not identity[VALID_TO_COL].dtype.is_temporal():
        raise PitJoinError("identity valid_to must be a date or datetime type (nulls = open)")

    intervals = identity.select([id_column, PERMANENT_ID_COL, VALID_FROM_COL, VALID_TO_COL])
    in_bounds = (pl.col(VALID_FROM_COL) <= pl.col(TIMESTAMP_COL)) & (
        pl.col(VALID_TO_COL).is_null() | (pl.col(TIMESTAMP_COL) <= pl.col(VALID_TO_COL))
    )
    joined = df.join(intervals, on=id_column, how="left").with_columns(
        pl.when(in_bounds)
        .then(pl.col(PERMANENT_ID_COL))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias(PERMANENT_ID_COL)
    )
    # One row per original key: take the in-bounds permanent_id, else fall back to the raw id.
    collapsed = (
        joined.group_by(df.columns, maintain_order=True)
        .agg(pl.col(PERMANENT_ID_COL).drop_nulls().first().alias(PERMANENT_ID_COL))
        .with_columns(
            pl.col(PERMANENT_ID_COL).fill_null(pl.col(id_column)).alias(PERMANENT_ID_COL)
        )
    )
    return collapsed


def asof_join_reference(
    df: pl.DataFrame,
    reference: pl.DataFrame,
    *,
    value_columns: Sequence[str],
    id_column: str = SYMBOL_COL,
    fail_on_missing_available_at: bool = True,
) -> pl.DataFrame:
    """Backward as-of join of reference values using real availability time.

    Join condition is ``available_at <= timestamp`` per id. A value published late (large
    available_at) never appears before its availability. Restatements are preserved as-known:
    the latest ``available_at <= t`` wins, never a future revision.
    """
    if not value_columns:
        raise PitJoinError("at least one reference value column is required")
    _require_columns(df, (id_column, TIMESTAMP_COL), label="panel")
    _require_temporal(df, TIMESTAMP_COL, label="panel")

    if AVAILABLE_AT_COL not in reference.columns:
        if fail_on_missing_available_at:
            raise PitJoinError(
                "reference data has no available_at column; cannot enforce as-of join "
                "(set fail_on_missing_available_at=False to mark SUSPECT instead)"
            )
        # Fail-open mode marks every reference value as never-available rather than guessing.
        empty = {column: None for column in value_columns}
        return df.with_columns([pl.lit(v).alias(k) for k, v in empty.items()])

    _require_columns(reference, (id_column, AVAILABLE_AT_COL), label="reference table")
    _require_columns(reference, value_columns, label="reference table")
    _require_temporal(reference, AVAILABLE_AT_COL, label="reference table")
    if reference[AVAILABLE_AT_COL].null_count() > 0:
        raise PitJoinError("reference available_at must not contain nulls")

    left = df.sort([id_column, TIMESTAMP_COL], maintain_order=True)
    right = reference.select([id_column, AVAILABLE_AT_COL, *value_columns]).sort(
        [id_column, AVAILABLE_AT_COL], maintain_order=True
    )
    joined = left.join_asof(
        right,
        left_on=TIMESTAMP_COL,
        right_on=AVAILABLE_AT_COL,
        by=id_column,
        strategy="backward",
    )
    # Drop the right-side key column if polars surfaced it under a different name.
    return joined


def asof_join_summary(
    df: pl.DataFrame,
    value_columns: Sequence[str],
) -> dict[str, Any]:
    """Summarize as-of join coverage (matched vs unmatched) per reference value column."""
    total = df.height
    summary: dict[str, Any] = {"row_count": total, "columns": {}}
    for column in value_columns:
        if column not in df.columns:
            summary["columns"][column] = {"present": False}
            continue
        matched = total - df[column].null_count()
        summary["columns"][column] = {
            "present": True,
            "matched": matched,
            "unmatched": total - matched,
        }
    return summary
