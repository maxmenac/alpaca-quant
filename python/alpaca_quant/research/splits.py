"""Phase 4C purged + embargoed temporal split INDEX DEFINITIONS only.

This module defines deterministic train/validation/test row index sets with leakage-purged and
embargoed boundaries. It does NOT run cross-validation, fit, transform, train a model, generate
signals, or score anything. It only computes which row indices belong to which block so a future
phase could train without label-window leakage.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import polars as pl

from alpaca_quant.research.targets import SYMBOL_COL, TIMESTAMP_COL


class SplitDefinitionError(RuntimeError):
    """Raised when a purged/embargoed split definition cannot be built or is unsafe."""


@dataclass(frozen=True)
class TemporalSplit:
    """Deterministic purged + embargoed split over the ordered timestamp axis.

    Indices reference rows of a frame stably sorted by ``(id_column, timestamp)``. Train indices
    are purged so no training label window overlaps validation/test, then embargoed by at least
    ``max_horizon`` bars after each evaluation block.
    """

    id_column: str
    max_horizon: int
    embargo: int
    n_timestamps: int
    train_index: tuple[int, ...]
    validation_index: tuple[int, ...]
    test_index: tuple[int, ...]
    purged_count: int
    embargoed_count: int
    boundary_timestamps: dict[str, str | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ordered_timestamps(df: pl.DataFrame, id_column: str) -> list[Any]:
    if id_column not in df.columns or TIMESTAMP_COL not in df.columns:
        raise SplitDefinitionError(
            f"frame must contain {id_column!r} and {TIMESTAMP_COL!r} columns"
        )
    if not df.schema[TIMESTAMP_COL].is_temporal():
        raise SplitDefinitionError("timestamp column must be a date or datetime type")
    return sorted(df[TIMESTAMP_COL].unique().to_list())


def make_temporal_split(
    df: pl.DataFrame,
    *,
    max_horizon: int,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    embargo: int | None = None,
    id_column: str = SYMBOL_COL,
) -> TemporalSplit:
    """Build a deterministic purged + embargoed train/validation/test split definition.

    The timestamp axis is partitioned by fraction into train | validation | test blocks. Any
    training row whose label window (``horizon`` bars forward) reaches into a later evaluation
    block is purged. An embargo of at least ``max_horizon`` bars is removed before each
    evaluation block. No model is trained and no CV is executed.
    """
    if isinstance(max_horizon, bool) or not isinstance(max_horizon, int) or max_horizon < 1:
        raise SplitDefinitionError("max_horizon must be an integer of at least 1")
    if embargo is None:
        embargo = max_horizon
    if isinstance(embargo, bool) or not isinstance(embargo, int) or embargo < max_horizon:
        raise SplitDefinitionError("embargo must be an integer >= max_horizon")
    if not (0.0 < train_fraction < 1.0) or not (0.0 < validation_fraction < 1.0):
        raise SplitDefinitionError("train/validation fractions must be in (0, 1)")
    if train_fraction + validation_fraction >= 1.0:
        raise SplitDefinitionError(
            "train_fraction + validation_fraction must leave a non-empty test block"
        )

    timestamps = _ordered_timestamps(df, id_column)
    n = len(timestamps)
    if n < 3:
        raise SplitDefinitionError("need at least 3 distinct timestamps to split")

    train_end = int(n * train_fraction)
    val_end = int(n * (train_fraction + validation_fraction))
    train_end = max(1, train_end)
    val_end = max(train_end + 1, val_end)
    val_end = min(val_end, n - 1)
    if not (0 < train_end < val_end < n):
        raise SplitDefinitionError("fractions produced an empty train/validation/test block")

    # Position of each timestamp in the ordered axis.
    pos = {ts: i for i, ts in enumerate(timestamps)}
    eval_start = train_end  # first evaluation (validation) timestamp position

    purged_positions: set[int] = set()
    embargoed_positions: set[int] = set()
    train_positions: list[int] = []
    for i in range(train_end):
        # Purge: label window [i, i + max_horizon] must not reach into evaluation block.
        if i + max_horizon >= eval_start:
            purged_positions.add(i)
            continue
        # Embargo: drop training rows within `embargo` bars before evaluation block start.
        if eval_start - i <= embargo:
            embargoed_positions.add(i)
            continue
        train_positions.append(i)

    val_positions = set(range(train_end, val_end))
    test_positions = set(range(val_end, n))

    # Map timestamp positions to dataframe row indices (sorted frame).
    ordered = df.sort([id_column, TIMESTAMP_COL], maintain_order=True)
    row_ts = ordered[TIMESTAMP_COL].to_list()
    train_rows: list[int] = []
    val_rows: list[int] = []
    test_rows: list[int] = []
    train_pos_set = set(train_positions)
    for row_idx, ts in enumerate(row_ts):
        p = pos[ts]
        if p in train_pos_set:
            train_rows.append(row_idx)
        elif p in val_positions:
            val_rows.append(row_idx)
        elif p in test_positions:
            test_rows.append(row_idx)

    def _ts(position: int | None) -> str | None:
        if position is None or position >= n:
            return None
        value = timestamps[position]
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    boundary = {
        "train_start": _ts(0),
        "train_end_exclusive": _ts(train_end),
        "validation_start": _ts(train_end),
        "validation_end_exclusive": _ts(val_end),
        "test_start": _ts(val_end),
        "test_end": _ts(n - 1),
    }

    return TemporalSplit(
        id_column=id_column,
        max_horizon=max_horizon,
        embargo=embargo,
        n_timestamps=n,
        train_index=tuple(train_rows),
        validation_index=tuple(val_rows),
        test_index=tuple(test_rows),
        purged_count=len(purged_positions),
        embargoed_count=len(embargoed_positions),
        boundary_timestamps=boundary,
    )


def assert_split_disjoint_and_purged(
    df: pl.DataFrame,
    split: TemporalSplit,
) -> None:
    """Fail closed if a split violates disjointness, purge, or embargo guarantees.

    Verifies (a) the three index sets are disjoint, (b) no training timestamp is within
    ``max_horizon`` bars before an evaluation timestamp, and (c) embargo >= max_horizon.
    """
    train = set(split.train_index)
    val = set(split.validation_index)
    test = set(split.test_index)
    if train & val or train & test or val & test:
        raise SplitDefinitionError("train/validation/test indices overlap")
    if split.embargo < split.max_horizon:
        raise SplitDefinitionError("embargo is smaller than max_horizon")

    ordered = df.sort([split.id_column, TIMESTAMP_COL], maintain_order=True)
    row_ts = ordered[TIMESTAMP_COL].to_list()
    timestamps = sorted(set(row_ts))
    pos = {ts: i for i, ts in enumerate(timestamps)}

    eval_positions = sorted({pos[row_ts[i]] for i in (val | test)})
    if not eval_positions:
        return
    first_eval = eval_positions[0]
    forbidden_floor = first_eval - split.embargo
    for i in train:
        p = pos[row_ts[i]]
        if p + split.max_horizon >= first_eval:
            raise SplitDefinitionError(
                "train row label window overlaps the evaluation block (purge violated)"
            )
        if p > forbidden_floor:
            raise SplitDefinitionError(
                "train row falls inside the embargo window before evaluation (embargo violated)"
            )


def split_summary(split: TemporalSplit) -> dict[str, Any]:
    """Serializable summary of a split definition for the manifest."""
    return {
        "id_column": split.id_column,
        "max_horizon": split.max_horizon,
        "embargo": split.embargo,
        "n_timestamps": split.n_timestamps,
        "n_train": len(split.train_index),
        "n_validation": len(split.validation_index),
        "n_test": len(split.test_index),
        "purged_count": split.purged_count,
        "embargoed_count": split.embargoed_count,
        "boundary_timestamps": split.boundary_timestamps,
    }


def split_definitions_for_manifest(splits: Sequence[TemporalSplit]) -> list[dict[str, Any]]:
    """Render multiple split definitions for inclusion in a dataset manifest."""
    return [split_summary(split) for split in splits]
