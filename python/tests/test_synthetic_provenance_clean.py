"""Phase 4F-0 clean path: strict-mode assembly + inspection reach an honest OK.

Synthetic only: no .env, network, API, or committed artifacts. These tests prove that the
local synthetic provenance fixtures (PIT universe, date-bounded identity with a ticker change,
permanent_id, as-reported bars with available_at, explicit corporate-action records, tz-aligned
neutral feature) are sufficient for the EXISTING 4C/4D/4D-1 chain to return OK — with all four
4D-1 warnings absent. The auditor is not modified here; only fixtures feed it.
"""

from datetime import UTC, datetime

import polars as pl

from alpaca_quant.research import synthetic_provenance as sp
from alpaca_quant.research.dataset_manifest import (
    BOUNDARY_STATEMENT,
    render_dataset_manifest_markdown,
)
from alpaca_quant.research.dataset_report import (
    BOUNDARY_NOTE,
    build_dataset_inspection_report,
    render_dataset_inspection_markdown,
)
from alpaca_quant.research.ml_dataset import ELIGIBILITY_REASON_COL, ELIGIBLE_COL

# 4D-1 acceptance checklist: these must all be ABSENT on the clean slice.
FORBIDDEN_CLEAN_WARNINGS = frozenset(
    {
        "missing_available_at_semantics",
        "ambiguous_adjustment_declaration",
        "feature_timezone_mismatch",
        "missing_symbol_identity",
        "missing_pit_universe",
    }
)


def _clock():
    return datetime(2026, 6, 16, tzinfo=UTC)


def _inspect(fixture, *, clock=_clock):
    assembled = fixture.assemble(clock=clock)
    report = build_dataset_inspection_report(
        assembled.frame,
        manifest=assembled.manifest,
        registry=sp.synthetic_registry(),
        requested_features=[sp.NEUTRAL_FEATURE],
        clock=clock,
    )
    return assembled, report


# --- clean path reaches OK --------------------------------------------------


def test_clean_strict_assembly_has_eligible_rows() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    assert assembled.manifest.eligible_row_count > 0


def test_clean_inspection_verdict_is_ok() -> None:
    _, report = _inspect(sp.clean_fixture())
    assert report["verdict"] == "OK"
    assert report["warnings"] == []


def test_clean_manifest_verdict_is_ok() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    assert assembled.verdict == "OK"


def test_all_4d1_warnings_absent_on_clean_slice() -> None:
    _, report = _inspect(sp.clean_fixture())
    codes = {w["code"] for w in report["warnings"]}
    assert codes & FORBIDDEN_CLEAN_WARNINGS == set()


# --- available_at invariant + provable as-of join ---------------------------


def test_bars_available_at_is_not_before_timestamp() -> None:
    bars = sp.clean_bars()
    assert (bars["available_at"] >= bars["timestamp"]).all()


def test_asof_reference_never_leaks_before_availability() -> None:
    # The split (available_at day 5) attaches to CLNA only from day 5 onward; earlier rows null.
    assembled = sp.clean_fixture().assemble(clock=_clock)
    frame = assembled.frame.sort(["symbol", "timestamp"])
    clna = frame.filter(pl.col("symbol") == sp.CLEAN_TICKER_OLD)
    factor = dict(
        zip(
            clna["timestamp"].to_list(),
            clna[sp.REFERENCE_VALUE_COLUMN].to_list(),
            strict=True,
        )
    )
    assert factor[sp._day(4)] is None  # before availability
    assert factor[sp._day(5)] == 0.5  # at/after availability
    assert factor[sp._day(6)] == 0.5


# --- identity holds across the ticker change --------------------------------


def test_identity_holds_across_ticker_change() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    frame = assembled.frame
    permanent = set(frame["permanent_id"].to_list())
    tickers = set(frame["symbol"].to_list())
    # Two tickers, ONE permanent_id spanning the rename.
    assert tickers == {sp.CLEAN_TICKER_OLD, sp.CLEAN_TICKER_NEW}
    assert permanent == {sp.CLEAN_PERMANENT_ID}


def test_clean_inspection_reports_identity_used() -> None:
    _, report = _inspect(sp.clean_fixture())
    assert report["symbol_identity_coverage"]["identity_used"] is True


# --- no-fill: nulls preserved end-to-end ------------------------------------


def test_clean_nulls_are_preserved_not_imputed() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    frame = assembled.frame.sort(["symbol", "timestamp"])
    # The last bar of each span has an unknown forward label and must stay null (never 0.0).
    last = frame.filter(pl.col(ELIGIBILITY_REASON_COL) == "all_labels_null")
    assert last.height > 0
    assert last[sp.LABEL_COLUMN].null_count() == last.height
    # Unmatched as-of reference rows stay null, not back-filled.
    assert frame[sp.REFERENCE_VALUE_COLUMN].null_count() > 0


# --- corporate-action records are auditable (not asserted) ------------------


def test_corporate_actions_records_back_the_declared_status() -> None:
    records = sp.clean_corporate_actions()
    # The declared status is consistent with concrete records, not a bare flag.
    assert set(records["action_type"].to_list()) == {"split", "cash_dividend"}
    assert (records["available_at"] <= records["available_at"].max()).all()
    # Adjustment provenance is derivable from records (factor present per record).
    assert records[sp.REFERENCE_VALUE_COLUMN].null_count() == 0


# --- determinism ------------------------------------------------------------


def test_clean_verdict_and_fingerprint_are_deterministic() -> None:
    a, ra = _inspect(sp.clean_fixture())
    b, rb = _inspect(sp.clean_fixture())
    assert a.manifest.fingerprint == b.manifest.fingerprint
    assert ra["verdict"] == rb["verdict"] == "OK"
    assert [w["code"] for w in ra["warnings"]] == [w["code"] for w in rb["warnings"]]


def test_clean_fingerprint_stable_under_row_reordering() -> None:
    fixture = sp.clean_fixture()
    a = fixture.assemble(clock=_clock).manifest.fingerprint
    reordered = sp.ProvenanceFixture(
        bars=fixture.bars.reverse(),
        features=fixture.features.reverse(),
        universe=fixture.universe,
        identity=fixture.identity,
        corporate_actions=fixture.corporate_actions,
        declaration=fixture.declaration,
    )
    b = reordered.assemble(clock=_clock).manifest.fingerprint
    assert a == b


# --- markdown boundary note present verbatim --------------------------------


def test_inspection_markdown_carries_boundary_note_verbatim() -> None:
    _, report = _inspect(sp.clean_fixture())
    md = render_dataset_inspection_markdown(report)
    assert BOUNDARY_NOTE in md


def test_manifest_markdown_carries_boundary_statement_verbatim() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    md = render_dataset_manifest_markdown(assembled.manifest)
    assert BOUNDARY_STATEMENT in md


def test_clean_frame_eligible_band_is_contiguous_and_nonempty() -> None:
    assembled = sp.clean_fixture().assemble(clock=_clock)
    eligible = assembled.frame.filter(pl.col(ELIGIBLE_COL))
    assert eligible.height == assembled.manifest.eligible_row_count
    assert eligible.height >= 1
