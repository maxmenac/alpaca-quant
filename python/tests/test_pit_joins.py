"""Phase 4C PIT join tests. Synthetic only: no .env, network, API, or artifacts."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.pit_joins import (
    PERMANENT_ID_COL,
    UNIVERSE_IN,
    UNIVERSE_MISSING,
    UNIVERSE_OUT,
    UNIVERSE_STATUS_COL,
    PitJoinError,
    annotate_universe_membership,
    asof_join_reference,
    asof_join_summary,
    resolve_permanent_ids,
)


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _panel(symbol: str, days: list[int]) -> pl.DataFrame:
    return pl.DataFrame({"symbol": [symbol] * len(days), "timestamp": [_day(d) for d in days]})


# --- universe membership ---------------------------------------------------


def test_missing_universe_marks_all_no_universe_data() -> None:
    out = annotate_universe_membership(_panel("AAPL", [2, 3, 4]), None)
    assert out[UNIVERSE_STATUS_COL].to_list() == [UNIVERSE_MISSING] * 3


def test_delisted_symbol_in_until_valid_to_then_out() -> None:
    panel = _panel("OLD", [2, 3, 4, 5])
    universe = pl.DataFrame(
        {
            "symbol": ["OLD"],
            "valid_from": [_day(1)],
            "valid_to": [_day(3)],
        }
    )
    out = annotate_universe_membership(panel, universe).sort("timestamp")
    assert out[UNIVERSE_STATUS_COL].to_list() == [
        UNIVERSE_IN,
        UNIVERSE_IN,
        UNIVERSE_OUT,
        UNIVERSE_OUT,
    ]


def test_not_yet_listed_symbol_is_out_before_valid_from() -> None:
    panel = _panel("NEW", [2, 3, 4])
    universe = pl.DataFrame(
        {"symbol": ["NEW"], "valid_from": [_day(4)], "valid_to": [None]},
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    out = annotate_universe_membership(panel, universe).sort("timestamp")
    assert out[UNIVERSE_STATUS_COL].to_list() == [UNIVERSE_OUT, UNIVERSE_OUT, UNIVERSE_IN]


def test_open_ended_valid_to_is_allowed() -> None:
    panel = _panel("AAPL", [2, 3])
    universe = pl.DataFrame(
        {"symbol": ["AAPL"], "valid_from": [_day(1)], "valid_to": [None]},
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    out = annotate_universe_membership(panel, universe)
    assert out[UNIVERSE_STATUS_COL].to_list() == [UNIVERSE_IN, UNIVERSE_IN]


def test_universe_contradiction_raises() -> None:
    universe = pl.DataFrame(
        {"symbol": ["X"], "valid_from": [_day(5)], "valid_to": [_day(2)]}
    )
    with pytest.raises(PitJoinError):
        annotate_universe_membership(_panel("X", [3]), universe)


def test_universe_missing_columns_raises() -> None:
    universe = pl.DataFrame({"symbol": ["X"], "valid_from": [_day(1)]})
    with pytest.raises(PitJoinError):
        annotate_universe_membership(_panel("X", [2]), universe)


# --- as-of reference join --------------------------------------------------


def test_late_published_value_does_not_appear_before_available_at() -> None:
    panel = _panel("AAPL", [2, 3, 4, 5, 6])
    reference = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "available_at": [_day(5)],  # t+3 relative to first row at day 2
            "eps": [1.23],
        }
    )
    out = asof_join_reference(panel, reference, value_columns=["eps"]).sort("timestamp")
    eps = out["eps"].to_list()
    # days 2,3,4 -> None ; day 5,6 -> value
    assert eps == [None, None, None, 1.23, 1.23]


def test_restatement_preserves_value_known_as_of_t() -> None:
    panel = _panel("AAPL", [2, 4, 6])
    reference = pl.DataFrame(
        {
            "symbol": ["AAPL", "AAPL"],
            "available_at": [_day(1), _day(5)],  # original then restatement
            "eps": [1.0, 9.9],
        }
    )
    out = asof_join_reference(panel, reference, value_columns=["eps"]).sort("timestamp")
    # day 2,4 see original 1.0 (restatement not yet known); day 6 sees 9.9
    assert out["eps"].to_list() == [1.0, 1.0, 9.9]


def test_missing_available_at_fails_closed() -> None:
    panel = _panel("AAPL", [2])
    reference = pl.DataFrame({"symbol": ["AAPL"], "eps": [1.0]})
    with pytest.raises(PitJoinError):
        asof_join_reference(panel, reference, value_columns=["eps"])


def test_missing_available_at_fail_open_marks_null() -> None:
    panel = _panel("AAPL", [2, 3])
    reference = pl.DataFrame({"symbol": ["AAPL"], "eps": [1.0]})
    out = asof_join_reference(
        panel, reference, value_columns=["eps"], fail_on_missing_available_at=False
    )
    assert out["eps"].to_list() == [None, None]


def test_available_at_must_be_datetime() -> None:
    panel = _panel("AAPL", [2])
    reference = pl.DataFrame({"symbol": ["AAPL"], "available_at": ["2024-01-01"], "eps": [1.0]})
    with pytest.raises(PitJoinError):
        asof_join_reference(panel, reference, value_columns=["eps"])


def test_asof_summary_counts_matched_and_unmatched() -> None:
    panel = _panel("AAPL", [2, 3, 4])
    reference = pl.DataFrame({"symbol": ["AAPL"], "available_at": [_day(3)], "eps": [1.0]})
    out = asof_join_reference(panel, reference, value_columns=["eps"])
    summary = asof_join_summary(out, ["eps"])
    assert summary["columns"]["eps"]["matched"] == 2
    assert summary["columns"]["eps"]["unmatched"] == 1


# --- identity --------------------------------------------------------------


def test_identity_absent_falls_back_to_raw_id() -> None:
    out = resolve_permanent_ids(_panel("AAPL", [2, 3]), None)
    assert out[PERMANENT_ID_COL].to_list() == ["AAPL", "AAPL"]


def test_identity_maps_ticker_to_permanent_id_within_bounds() -> None:
    panel = _panel("FB", [2, 3])
    identity = pl.DataFrame(
        {
            "permanent_id": ["pid-1"],
            "symbol": ["FB"],
            "valid_from": [_day(1)],
            "valid_to": [_day(10)],
        }
    )
    out = resolve_permanent_ids(panel, identity)
    assert out[PERMANENT_ID_COL].to_list() == ["pid-1", "pid-1"]


def test_identity_does_not_merge_outside_date_bounds() -> None:
    panel = _panel("META", [2])
    identity = pl.DataFrame(
        {
            "permanent_id": ["pid-1"],
            "symbol": ["META"],
            "valid_from": [_day(5)],  # mapping only valid later
            "valid_to": [None],
        },
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    out = resolve_permanent_ids(panel, identity)
    # outside bounds -> falls back to raw ticker, never blindly merged
    assert out[PERMANENT_ID_COL].to_list() == ["META"]
