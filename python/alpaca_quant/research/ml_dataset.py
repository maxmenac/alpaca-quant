"""Phase 4C ML dataset assembly: PIT-safe join of features + Phase 4A labels.

This module answers ONE question: "can we assemble X and y without silently leaking future
information?" It does NOT train a model, fit/transform, run CV, generate signals/alpha/weights,
construct portfolios, optimize, backtest, place orders, read .env, or touch any network/API.

Features are carried through unchanged (never recomputed). Rows are flagged eligible/ineligible
with explicit reasons — never silently dropped, filled, imputed, or globally scaled.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from alpaca_quant.research.data_contract import (
    DataContractError,
    FeatureSpec,
    assert_features_acceptable,
    feature_availability_summary,
    normalize_feature_specs,
)
from alpaca_quant.research.dataset_manifest import (
    DatasetManifest,
    build_dataset_manifest,
)
from alpaca_quant.research.pit_joins import (
    PERMANENT_ID_COL,
    UNIVERSE_IN,
    UNIVERSE_MISSING,
    UNIVERSE_STATUS_COL,
    annotate_universe_membership,
    asof_join_reference,
    asof_join_summary,
    resolve_permanent_ids,
)
from alpaca_quant.research.targets import SYMBOL_COL, TIMESTAMP_COL, TargetManifest

FEATURE_CUTOFF_COL = "feature_cutoff_time"
MAX_LABEL_HORIZON_COL = "max_label_horizon"
ELIGIBLE_COL = "eligible"
ELIGIBILITY_REASON_COL = "eligibility_reason"

# Eligibility reasons (one per ineligible row; eligible rows carry REASON_ELIGIBLE).
REASON_ELIGIBLE = "eligible"
REASON_NOT_IN_UNIVERSE = "not_in_universe"
REASON_NO_UNIVERSE_DATA = "no_universe_data"
REASON_ALL_LABELS_NULL = "all_labels_null"
REASON_INSUFFICIENT_FEATURE_HISTORY = "insufficient_feature_history"

_HORIZON_SUFFIX = re.compile(r"_(\d+)d$")


class MLDatasetError(RuntimeError):
    """Raised when an ML dataset cannot be assembled under the 4C anti-leakage contract."""


@dataclass(frozen=True)
class DatasetConfig:
    """Deterministic knobs for assembly. No randomness, no fitting, no scaling."""

    feature_lag_bars: int = 1
    synthetic_no_universe: bool = False
    fail_on_missing_available_at: bool = True
    max_feature_null_fraction: float = 0.5
    max_label_null_fraction: float = 0.9

    def __post_init__(self) -> None:
        if isinstance(self.feature_lag_bars, bool) or self.feature_lag_bars < 1:
            raise MLDatasetError("feature_lag_bars must be an integer >= 1")
        for name in ("max_feature_null_fraction", "max_label_null_fraction"):
            value = getattr(self, name)
            if not 0.0 <= float(value) <= 1.0:
                raise MLDatasetError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class AssembledMLDataset:
    """Assembled dataset frame plus its lineage/eligibility manifest."""

    frame: pl.DataFrame
    manifest: DatasetManifest
    suspect_features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verdict(self) -> str:
        return self.manifest.verdict


def _validate_panel(df: pl.DataFrame, *, id_column: str, label: str) -> None:
    if id_column not in df.columns or TIMESTAMP_COL not in df.columns:
        raise MLDatasetError(f"{label} must contain {id_column!r} and {TIMESTAMP_COL!r}")
    if not df.schema[TIMESTAMP_COL].is_temporal():
        raise MLDatasetError(f"{label} timestamp must be a date or datetime type")
    if df[TIMESTAMP_COL].null_count() > 0:
        raise MLDatasetError(f"{label} timestamp must not contain nulls")
    if df[id_column].null_count() > 0:
        raise MLDatasetError(f"{label} {id_column} must not contain nulls")
    if df.select([id_column, TIMESTAMP_COL]).is_duplicated().any():
        raise MLDatasetError(f"{label} contains duplicate {id_column}/timestamp rows")


def _resolve_horizon(column: str, label_horizons: Mapping[str, int] | None) -> int:
    if label_horizons is not None and column in label_horizons:
        horizon = label_horizons[column]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise MLDatasetError(f"label horizon for {column!r} must be an integer >= 1")
        return horizon
    match = _HORIZON_SUFFIX.search(column)
    if match:
        return int(match.group(1))
    return 1


def assemble_ml_dataset(
    *,
    labels: pl.DataFrame,
    features: pl.DataFrame,
    feature_specs: Sequence[FeatureSpec | str | Mapping[str, Any]],
    label_columns: Sequence[str],
    target_manifest: TargetManifest | Mapping[str, Any] | None = None,
    label_horizons: Mapping[str, int] | None = None,
    universe: pl.DataFrame | None = None,
    identity: pl.DataFrame | None = None,
    reference: pl.DataFrame | None = None,
    reference_value_columns: Sequence[str] = (),
    id_column: str = SYMBOL_COL,
    config: DatasetConfig | None = None,
    config_payload: Mapping[str, Any] | None = None,
    data_declaration: Mapping[str, Any] | None = None,
    clock: Any | None = None,
) -> AssembledMLDataset:
    """Assemble a PIT-safe ``(features, labels)`` panel with eligibility + lineage.

    Returns the stably-sorted dataset frame and a manifest with null accounting, universe
    coverage, as-of summary, and a deterministic fingerprint. Rows are flagged, never dropped.
    """
    resolved_config = config or DatasetConfig()
    specs = normalize_feature_specs(feature_specs)
    suspect_features = tuple(assert_features_acceptable(specs))

    if not label_columns:
        raise MLDatasetError("at least one label column is required")
    label_columns = list(dict.fromkeys(label_columns))

    _validate_panel(labels, id_column=id_column, label="labels panel")
    _validate_panel(features, id_column=id_column, label="features panel")

    missing_labels = [column for column in label_columns if column not in labels.columns]
    if missing_labels:
        raise MLDatasetError(f"labels panel is missing declared label columns: {missing_labels}")

    required_features = [spec.name for spec in specs if spec.required]
    missing_features = [name for name in required_features if name not in features.columns]
    if missing_features:
        raise MLDatasetError(f"features panel is missing required columns: {missing_features}")
    feature_columns = [spec.name for spec in specs if spec.name in features.columns]

    # 1. Spine = labels panel; carry features through unchanged via an inner-by-key left join.
    feature_view = features.select([id_column, TIMESTAMP_COL, *feature_columns])
    spine = labels.select(
        [id_column, TIMESTAMP_COL, *label_columns]
    ).join(feature_view, on=[id_column, TIMESTAMP_COL], how="left")

    # 2. Symbol identity -> permanent_id lineage (date-bounded; no blind ticker merge).
    spine = resolve_permanent_ids(spine, identity, id_column=id_column)

    # 3. PIT universe membership / anti-survivorship.
    spine = annotate_universe_membership(spine, universe, id_column=id_column)

    # 4. As-of reference join (available_at <= timestamp), restatement-preserving.
    asof_columns = list(reference_value_columns)
    if reference is not None:
        if not asof_columns:
            raise MLDatasetError("reference_value_columns is required when reference is provided")
        spine = asof_join_reference(
            spine,
            reference,
            value_columns=asof_columns,
            id_column=id_column,
            fail_on_missing_available_at=resolved_config.fail_on_missing_available_at,
        )

    ordered = spine.sort([id_column, TIMESTAMP_COL], maintain_order=True)

    # 5. Feature cutoff (lagged strictly before timestamp = label entry) and label horizon.
    horizons = {column: _resolve_horizon(column, label_horizons) for column in label_columns}
    max_horizon = max(horizons.values())
    ordered = ordered.with_columns(
        pl.col(TIMESTAMP_COL)
        .shift(resolved_config.feature_lag_bars)
        .over(id_column)
        .alias(FEATURE_CUTOFF_COL),
        pl.lit(max_horizon).alias(MAX_LABEL_HORIZON_COL),
    )

    # 6. Eligibility — explicit reasons, no silent drops.
    any_label_non_null = pl.any_horizontal(
        [pl.col(column).is_not_null() for column in label_columns]
    )
    universe_ok = pl.col(UNIVERSE_STATUS_COL) == UNIVERSE_IN
    if resolved_config.synthetic_no_universe:
        universe_ok = universe_ok | (pl.col(UNIVERSE_STATUS_COL) == UNIVERSE_MISSING)

    # feature_cutoff is the prior bar (lag >= 1), so non-null cutoff is strictly < timestamp.
    reason = (
        pl.when(pl.col(FEATURE_CUTOFF_COL).is_null())
        .then(pl.lit(REASON_INSUFFICIENT_FEATURE_HISTORY))
        .when(~universe_ok & (pl.col(UNIVERSE_STATUS_COL) == UNIVERSE_MISSING))
        .then(pl.lit(REASON_NO_UNIVERSE_DATA))
        .when(~universe_ok)
        .then(pl.lit(REASON_NOT_IN_UNIVERSE))
        .when(~any_label_non_null)
        .then(pl.lit(REASON_ALL_LABELS_NULL))
        .otherwise(pl.lit(REASON_ELIGIBLE))
    )
    ordered = ordered.with_columns(reason.alias(ELIGIBILITY_REASON_COL))
    ordered = ordered.with_columns(
        (pl.col(ELIGIBILITY_REASON_COL) == REASON_ELIGIBLE).alias(ELIGIBLE_COL)
    )

    # Re-order columns for stability: keys, features, labels, then metadata.
    metadata_cols = [
        PERMANENT_ID_COL,
        UNIVERSE_STATUS_COL,
        FEATURE_CUTOFF_COL,
        MAX_LABEL_HORIZON_COL,
        ELIGIBLE_COL,
        ELIGIBILITY_REASON_COL,
    ]
    leading = [id_column, TIMESTAMP_COL]
    tail = [c for c in ordered.columns if c not in {*leading, *metadata_cols}]
    frame = ordered.select([*leading, *tail, *metadata_cols])

    manifest = build_dataset_manifest(
        frame,
        id_column=id_column,
        feature_specs=specs,
        feature_columns=feature_columns,
        label_columns=label_columns,
        label_horizons=horizons,
        reference_value_columns=asof_columns,
        target_manifest=target_manifest,
        universe_provided=universe is not None,
        identity_provided=identity is not None,
        suspect_features=suspect_features,
        synthetic_no_universe=resolved_config.synthetic_no_universe,
        max_feature_null_fraction=resolved_config.max_feature_null_fraction,
        max_label_null_fraction=resolved_config.max_label_null_fraction,
        availability_summary=feature_availability_summary(specs),
        asof_summary=asof_join_summary(frame, asof_columns),
        config_payload=config_payload,
        data_declaration=data_declaration,
        clock=clock,
    )
    return AssembledMLDataset(
        frame=frame, manifest=manifest, suspect_features=suspect_features
    )


__all__ = [
    "AssembledMLDataset",
    "DatasetConfig",
    "MLDatasetError",
    "assemble_ml_dataset",
    "FEATURE_CUTOFF_COL",
    "MAX_LABEL_HORIZON_COL",
    "ELIGIBLE_COL",
    "ELIGIBILITY_REASON_COL",
    "DataContractError",
]
