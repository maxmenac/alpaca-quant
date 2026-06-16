"""Phase 4F-0 dirty path: each variant stays SUSPECT/ineligible for ONE named reason.

Synthetic only: no .env, network, API, or committed artifacts. Proving green is reachable is
half the contract; these tests prove red/yellow is still correctly refused. Each fixture breaks
exactly one provenance guarantee and the assertion targets the SPECIFIC warning, not just
"not OK". The auditor is unchanged — only the fixtures differ.
"""

from datetime import UTC, datetime

import polars as pl

from alpaca_quant.research import synthetic_provenance as sp
from alpaca_quant.research.dataset_report import build_dataset_inspection_report
from alpaca_quant.research.feature_registry import (
    FeatureDefinition,
    build_registry,
)
from alpaca_quant.research.ml_dataset import ELIGIBILITY_REASON_COL, ELIGIBLE_COL


def _clock():
    return datetime(2026, 6, 16, tzinfo=UTC)


def _inspect(fixture, *, requested=(sp.NEUTRAL_FEATURE,), registry=None, clock=_clock):
    assembled = fixture.assemble(clock=clock)
    report = build_dataset_inspection_report(
        assembled.frame,
        manifest=assembled.manifest,
        registry=registry or sp.synthetic_registry(),
        requested_features=list(requested),
        clock=clock,
    )
    return assembled, report


def _codes(report) -> set[str]:
    return {w["code"] for w in report["warnings"]}


# --- delisted symbol -> out-of-universe / ineligible after valid_to ---------


def test_delisted_symbol_is_ineligible_after_valid_to() -> None:
    assembled = sp.delisted_fixture().assemble(clock=_clock)
    frame = assembled.frame
    after = frame.filter(pl.col("timestamp") > sp._day(6))
    assert after.height > 0
    assert after[ELIGIBLE_COL].any() is False
    assert set(after[ELIGIBILITY_REASON_COL].to_list()) == {"not_in_universe"}


# --- broken identity -> missing_symbol_identity -----------------------------


def test_broken_identity_flags_missing_symbol_identity() -> None:
    _, report = _inspect(sp.broken_identity_fixture())
    assert report["verdict"] == "SUSPECT"
    assert "missing_symbol_identity" in _codes(report)
    assert report["symbol_identity_coverage"]["identity_used"] is False


# --- missing available_at -> missing_available_at_semantics -----------------


def test_missing_available_at_flags_semantics() -> None:
    _, report = _inspect(sp.missing_available_at_fixture())
    assert report["verdict"] == "SUSPECT"
    assert "missing_available_at_semantics" in _codes(report)


# --- ambiguous adjustment declaration ---------------------------------------


def test_ambiguous_adjustment_declaration_flagged() -> None:
    assembled, report = _inspect(sp.ambiguous_adjustment_fixture())
    assert report["verdict"] == "SUSPECT"
    assert "ambiguous_adjustment_declaration" in _codes(report)
    # The declared value is carried through verbatim, never silently coerced clean.
    assert (
        assembled.manifest.declared_corporate_actions_status
        == sp.AMBIGUOUS_CORPORATE_ACTIONS_STATUS
    )


# --- feature/bar timezone mismatch ------------------------------------------


def test_timezone_mismatch_flagged_and_no_conversion() -> None:
    assembled, report = _inspect(sp.timezone_mismatch_fixture())
    assert report["verdict"] == "SUSPECT"
    assert "feature_timezone_mismatch" in _codes(report)
    # The auditor refused the join and converted nothing: the feature is absent, not mutated.
    assert sp.NEUTRAL_FEATURE not in assembled.frame.columns
    assert assembled.manifest.timezone_alignment["mismatch"] is True


# --- too short for the horizon ----------------------------------------------


def test_too_short_window_yields_zero_eligible() -> None:
    assembled = sp.too_short_fixture().assemble(clock=_clock)
    assert assembled.manifest.eligible_row_count == 0
    # The single bar has no prior cutoff and no forward label; both stay null (tail-null).
    frame = assembled.frame
    assert frame[sp.LABEL_COLUMN].null_count() == frame.height


# --- cross-cutting: REJECTED precedence over SUSPECT ------------------------


def test_rejected_condition_dominates_suspect() -> None:
    # A look-ahead feature definition is REJECTED; it must win over any SUSPECT condition.
    registry = build_registry(
        [
            *sp.synthetic_registry().definitions,
            FeatureDefinition(
                name="lookahead_volume_raw",
                family="mechanical_volume",
                description="Synthetic look-ahead column (declares uses_future_data).",
                dtype="float64",
                source="caller_provided",
                uses_future_data=True,
            ),
        ]
    )
    _, report = _inspect(
        sp.broken_identity_fixture(),
        requested=(sp.NEUTRAL_FEATURE, "lookahead_volume_raw"),
        registry=registry,
    )
    codes = _codes(report)
    assert "missing_symbol_identity" in codes  # a SUSPECT condition is present
    assert report["verdict"] == "REJECTED"  # but REJECTED dominates


# --- cross-cutting: determinism of the dirty verdict + warning set ----------


def test_dirty_warning_set_is_stable_and_sorted() -> None:
    _, a = _inspect(sp.ambiguous_adjustment_fixture())
    _, b = _inspect(sp.ambiguous_adjustment_fixture())
    codes_a = [w["code"] for w in a["warnings"]]
    codes_b = [w["code"] for w in b["warnings"]]
    assert codes_a == codes_b
    assert codes_a == sorted(codes_a)  # report sorts warnings deterministically
    assert a["verdict"] == b["verdict"] == "SUSPECT"
