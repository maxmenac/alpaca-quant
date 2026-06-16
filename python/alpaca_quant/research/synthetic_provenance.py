"""Phase 4F-0 local synthetic provenance fixtures (build data, not auditor).

This module constructs small, fully-local, deterministic "synthetic-but-realistic" provenance
tables so the existing Phase 4C/4D/4D-1 strict-mode chain can be exercised end-to-end:

  * as-reported (un-adjusted) bars carrying a per-row ``available_at`` (>= the bar timestamp),
  * a PIT universe table with ``valid_from`` / ``valid_to`` membership and a **delisted** symbol
    whose ``valid_to`` ends mid-dataset,
  * a date-bounded identity mapping with a **ticker change mid-window** under one stable
    ``permanent_id``,
  * explicit **corporate-action records** (a split and a dividend) so adjustment provenance is
    auditable from records rather than asserted by a bare flag,
  * a neutral pass-through feature (``bar_volume_raw``) declared in the Feature Registry and
    timezone-aligned to the bars.

It builds *both* designed paths: a CLEAN slice that should reach an honest OK, and DIRTY variants
that must stay SUSPECT/ineligible for one named reason each.

It computes NO features, alpha, signal, weight, strategy, model, optimizer, backtest, or order; it
reads no network/API/.env; it imputes nothing; it converts no timezones. It does NOT modify the
4C/4D/4D-1 inspection or verdict logic — it only feeds local fixtures into the existing chain.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import polars as pl

from alpaca_quant.research.data_contract import FeatureSpec
from alpaca_quant.research.feature_registry import (
    NEUTRAL_SAMPLE_DEFINITIONS,
    FeatureRegistry,
    build_registry,
)
from alpaca_quant.research.ml_dataset import (
    AssembledMLDataset,
    DatasetConfig,
    assemble_ml_dataset,
)
from alpaca_quant.research.targets import build_forward_return_labels

# Stable identifiers for the synthetic universe.
CLEAN_PERMANENT_ID = "PID-CLEAN"
CLEAN_TICKER_OLD = "CLNA"  # ticker before the mid-window rename
CLEAN_TICKER_NEW = "CLNB"  # same permanent_id after the rename
DELISTED_PERMANENT_ID = "PID-DLST"
DELISTED_TICKER = "DLST"

NEUTRAL_FEATURE = "bar_volume_raw"
LABEL_COLUMN = "label_forward_return_1d"
REFERENCE_VALUE_COLUMN = "cum_adjustment_factor"

# An honest, explicit declared status that is consistent with the corporate-action records we
# supply (the records ARE present and reconciled). The dirty variant overrides this to "partial".
CLEAN_CORPORATE_ACTIONS_STATUS = "full"
AMBIGUOUS_CORPORATE_ACTIONS_STATUS = "partial"


def _day(n: int) -> datetime:
    """UTC midnight on 2024-01-n. Deterministic; no clock, no randomness."""
    return datetime(2024, 1, n, tzinfo=UTC)


def _bars(
    symbol: str,
    permanent_id: str,
    closes: Sequence[float],
    *,
    start: int,
) -> pl.DataFrame:
    """As-reported (un-adjusted) bars for one ticker span.

    ``available_at`` is stamped equal to the bar timestamp (the weakest honest claim: a bar for
    time t is knowable no earlier than t), satisfying ``available_at >= timestamp``.
    """
    timestamps = [_day(start + i) for i in range(len(closes))]
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": timestamps,
            "open": [round(c * 0.99, 4) for c in closes],
            "high": [round(c * 1.01, 4) for c in closes],
            "low": [round(c * 0.98, 4) for c in closes],
            "close": list(closes),
            "volume": [1000.0 + 10.0 * i for i in range(n)],
            "available_at": timestamps,  # >= timestamp (equal); per-row provenance.
            "permanent_id": [permanent_id] * n,
        },
        schema_overrides={
            "timestamp": pl.Datetime(time_zone="UTC"),
            "available_at": pl.Datetime(time_zone="UTC"),
        },
    )


def clean_bars() -> pl.DataFrame:
    """As-reported bars for the clean permanent_id across its two ticker spans.

    CLNA covers days 2..6, then the same permanent_id trades as CLNB on days 7..11.
    """
    span_old = _bars(
        CLEAN_TICKER_OLD, CLEAN_PERMANENT_ID, [100.0, 102.0, 104.0, 106.0, 108.0], start=2
    )
    span_new = _bars(
        CLEAN_TICKER_NEW, CLEAN_PERMANENT_ID, [110.0, 112.0, 114.0, 116.0, 118.0], start=7
    )
    return pl.concat([span_old, span_new])


def delisted_bars() -> pl.DataFrame:
    """As-reported bars for a symbol that is delisted mid-window (valid_to = day 6)."""
    closes = [50.0, 49.0, 48.0, 47.0, 46.0, 45.0, 44.0, 43.0, 42.0, 41.0]
    return _bars(DELISTED_TICKER, DELISTED_PERMANENT_ID, closes, start=2)


def clean_universe() -> pl.DataFrame:
    """PIT universe for the clean permanent_id's two ticker spans (full membership)."""
    return pl.DataFrame(
        {
            "permanent_id": [CLEAN_PERMANENT_ID, CLEAN_PERMANENT_ID],
            "symbol": [CLEAN_TICKER_OLD, CLEAN_TICKER_NEW],
            "valid_from": [_day(2), _day(7)],
            "valid_to": [_day(6), _day(11)],
        },
        schema_overrides={
            "valid_from": pl.Datetime(time_zone="UTC"),
            "valid_to": pl.Datetime(time_zone="UTC"),
        },
    )


def delisted_universe() -> pl.DataFrame:
    """PIT universe including the delisted symbol whose valid_to ends mid-dataset (day 6)."""
    return pl.DataFrame(
        {
            "permanent_id": [DELISTED_PERMANENT_ID],
            "symbol": [DELISTED_TICKER],
            "valid_from": [_day(2)],
            "valid_to": [_day(6)],
        },
        schema_overrides={
            "valid_from": pl.Datetime(time_zone="UTC"),
            "valid_to": pl.Datetime(time_zone="UTC"),
        },
    )


def clean_identity() -> pl.DataFrame:
    """Date-bounded identity: one permanent_id, two ticker spans (a mid-window ticker change)."""
    return pl.DataFrame(
        {
            "permanent_id": [CLEAN_PERMANENT_ID, CLEAN_PERMANENT_ID],
            "symbol": [CLEAN_TICKER_OLD, CLEAN_TICKER_NEW],
            "valid_from": [_day(2), _day(7)],
            "valid_to": [_day(6), _day(11)],
        },
        schema_overrides={
            "valid_from": pl.Datetime(time_zone="UTC"),
            "valid_to": pl.Datetime(time_zone="UTC"),
        },
    )


def clean_corporate_actions() -> pl.DataFrame:
    """Explicit, auditable corporate-action records tied to permanent_id + effective date.

    A 2:1 split on CLNA (effective day 5) and a cash dividend on CLNB (effective day 9). The
    ``cum_adjustment_factor`` plus ``available_at`` (= the effective/ex date) let the existing
    as-of join attach adjustment provenance WITHOUT us back-adjusting any bar. Adjustment safety
    is therefore checkable from these records, not asserted by a flag.
    """
    return pl.DataFrame(
        {
            "permanent_id": [CLEAN_PERMANENT_ID, CLEAN_PERMANENT_ID],
            "symbol": [CLEAN_TICKER_OLD, CLEAN_TICKER_NEW],
            "action_type": ["split", "cash_dividend"],
            "effective_date": [_day(5), _day(9)],
            "ratio": [2.0, None],
            "cash_amount": [None, 0.50],
            REFERENCE_VALUE_COLUMN: [0.5, 0.99],
            "available_at": [_day(5), _day(9)],
        },
        schema_overrides={
            "effective_date": pl.Datetime(time_zone="UTC"),
            "available_at": pl.Datetime(time_zone="UTC"),
        },
    )


def _features_from_bars(bars: pl.DataFrame) -> pl.DataFrame:
    """Neutral pass-through feature panel (raw bar volume), timezone-aligned to the bars."""
    return bars.select(["symbol", "timestamp", pl.col("volume").alias(NEUTRAL_FEATURE)])


def synthetic_registry() -> FeatureRegistry:
    """The neutral feature registry (declared metadata only; nothing is computed)."""
    return build_registry(NEUTRAL_SAMPLE_DEFINITIONS)


def neutral_feature_spec() -> FeatureSpec:
    """The 4C data-contract spec for the neutral pass-through feature, sourced from the registry."""
    return synthetic_registry().get(NEUTRAL_FEATURE).to_feature_spec()


@dataclass(frozen=True)
class ProvenanceFixture:
    """A coherent local fixture bundle that the existing strict-mode chain can assemble.

    Construction is deterministic; ``replace``-based mutators below break exactly one provenance
    guarantee at a time so each dirty path maps to a single named reason.
    """

    bars: pl.DataFrame
    features: pl.DataFrame
    universe: pl.DataFrame | None
    identity: pl.DataFrame | None
    corporate_actions: pl.DataFrame | None
    declaration: Mapping[str, Any]
    label_columns: tuple[str, ...] = (LABEL_COLUMN,)
    synthetic_no_universe: bool = False

    @property
    def reference(self) -> pl.DataFrame | None:
        """Corporate-action records projected into an as-of reference (available_at + value)."""
        if self.corporate_actions is None:
            return None
        return self.corporate_actions.select(
            ["symbol", "available_at", REFERENCE_VALUE_COLUMN]
        )

    @property
    def reference_value_columns(self) -> tuple[str, ...]:
        return () if self.corporate_actions is None else (REFERENCE_VALUE_COLUMN,)

    def labels(self) -> pl.DataFrame:
        return build_forward_return_labels(
            self.bars.select(["symbol", "timestamp", "close"]), horizon=1
        )

    def assemble(self, *, clock: Any | None = None) -> AssembledMLDataset:
        """Run the EXISTING strict-mode 4C assembly on this fixture (auditor unchanged)."""
        return assemble_ml_dataset(
            labels=self.labels(),
            features=self.features,
            feature_specs=[neutral_feature_spec()],
            label_columns=list(self.label_columns),
            universe=self.universe,
            identity=self.identity,
            reference=self.reference,
            reference_value_columns=list(self.reference_value_columns),
            config=DatasetConfig(synthetic_no_universe=self.synthetic_no_universe),
            data_declaration=dict(self.declaration),
            clock=clock,
        )


def clean_fixture() -> ProvenanceFixture:
    """The clean path: full membership, stable identity, available_at, records, aligned feature."""
    bars = clean_bars()
    return ProvenanceFixture(
        bars=bars,
        features=_features_from_bars(bars),
        universe=clean_universe(),
        identity=clean_identity(),
        corporate_actions=clean_corporate_actions(),
        declaration={"corporate_actions_status": CLEAN_CORPORATE_ACTIONS_STATUS},
    )


# --- Dirty variants: each breaks exactly ONE provenance guarantee -----------------------------


def delisted_fixture() -> ProvenanceFixture:
    """Delisted symbol → out-of-universe (ineligible) after valid_to (day 6)."""
    bars = delisted_bars()
    return ProvenanceFixture(
        bars=bars,
        features=_features_from_bars(bars),
        universe=delisted_universe(),
        identity=pl.DataFrame(
            {
                "permanent_id": [DELISTED_PERMANENT_ID],
                "symbol": [DELISTED_TICKER],
                "valid_from": [_day(2)],
                "valid_to": [_day(11)],
            },
            schema_overrides={
                "valid_from": pl.Datetime(time_zone="UTC"),
                "valid_to": pl.Datetime(time_zone="UTC"),
            },
        ),
        corporate_actions=clean_corporate_actions(),
        declaration={"corporate_actions_status": CLEAN_CORPORATE_ACTIONS_STATUS},
    )


def broken_identity_fixture() -> ProvenanceFixture:
    """Identity table withheld → permanent_id falls back to raw id → missing_symbol_identity."""
    return replace(clean_fixture(), identity=None)


def missing_available_at_fixture() -> ProvenanceFixture:
    """No corporate-action reference and no available_at column → missing_available_at_semantics."""
    return replace(clean_fixture(), corporate_actions=None)


def ambiguous_adjustment_fixture() -> ProvenanceFixture:
    """Declared corporate_actions_status='partial' → ambiguous_adjustment_declaration."""
    return replace(
        clean_fixture(),
        declaration={"corporate_actions_status": AMBIGUOUS_CORPORATE_ACTIONS_STATUS},
    )


def timezone_mismatch_fixture() -> ProvenanceFixture:
    """Feature panel declared in a different timezone than the bars → feature_timezone_mismatch.

    The bars are NOT touched; only the feature panel's declared timezone differs. The auditor
    refuses the join and converts nothing (we never call tz_convert in an inspection path).
    """
    fixture = clean_fixture()
    foreign = fixture.features.with_columns(
        pl.col("timestamp").dt.convert_time_zone("Europe/Copenhagen")
    )
    return replace(fixture, features=foreign)


def too_short_fixture() -> ProvenanceFixture:
    """A window too short for lag-1 cutoff + horizon → 0 eligible / tail-null."""
    bars = _bars("SHRT", "PID-SHRT", [10.0], start=2)
    return ProvenanceFixture(
        bars=bars,
        features=_features_from_bars(bars),
        universe=pl.DataFrame(
            {
                "permanent_id": ["PID-SHRT"],
                "symbol": ["SHRT"],
                "valid_from": [_day(2)],
                "valid_to": [_day(2)],
            },
            schema_overrides={
                "valid_from": pl.Datetime(time_zone="UTC"),
                "valid_to": pl.Datetime(time_zone="UTC"),
            },
        ),
        identity=pl.DataFrame(
            {
                "permanent_id": ["PID-SHRT"],
                "symbol": ["SHRT"],
                "valid_from": [_day(2)],
                "valid_to": [_day(2)],
            },
            schema_overrides={
                "valid_from": pl.Datetime(time_zone="UTC"),
                "valid_to": pl.Datetime(time_zone="UTC"),
            },
        ),
        corporate_actions=None,
        declaration={"corporate_actions_status": CLEAN_CORPORATE_ACTIONS_STATUS},
    )


__all__ = [
    "AMBIGUOUS_CORPORATE_ACTIONS_STATUS",
    "CLEAN_CORPORATE_ACTIONS_STATUS",
    "CLEAN_PERMANENT_ID",
    "CLEAN_TICKER_NEW",
    "CLEAN_TICKER_OLD",
    "DELISTED_PERMANENT_ID",
    "DELISTED_TICKER",
    "LABEL_COLUMN",
    "NEUTRAL_FEATURE",
    "REFERENCE_VALUE_COLUMN",
    "ProvenanceFixture",
    "ambiguous_adjustment_fixture",
    "broken_identity_fixture",
    "clean_bars",
    "clean_corporate_actions",
    "clean_fixture",
    "clean_identity",
    "clean_universe",
    "delisted_bars",
    "delisted_fixture",
    "delisted_universe",
    "missing_available_at_fixture",
    "neutral_feature_spec",
    "synthetic_registry",
    "timezone_mismatch_fixture",
    "too_short_fixture",
]
