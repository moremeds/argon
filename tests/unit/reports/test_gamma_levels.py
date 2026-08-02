"""Side-guard on dealer gamma levels.

The values below are REAL degenerate observations from uw_scan.gex_snapshots for SPX
(2026-07-25 and 2026-07-28, local dev DB) — the exact rows that motivated the guard.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.gamma_levels import apply_side_guard, resolve_levels


def test_wall_below_spot_is_dropped_not_drawn() -> None:
    """SPX 2026-07-28: argon computed call_wall == put_wall == 7000 with spot 7383.
    A 'resistance' line 383 points under spot is a false statement, so it must not
    reach the chart."""
    call, put, dropped = apply_side_guard(
        spot=7383.0, call_wall=7000.0, put_wall=7000.0
    )
    assert call is None
    assert put == 7000.0  # a put wall BELOW spot is structurally fine — kept
    assert dropped == ["call_wall"]


def test_put_wall_above_spot_is_dropped() -> None:
    call, put, dropped = apply_side_guard(
        spot=7383.0, call_wall=7500.0, put_wall=7450.0
    )
    assert call == 7500.0
    assert put is None
    assert dropped == ["put_wall"]


def test_valid_pair_survives_untouched() -> None:
    call, put, dropped = apply_side_guard(
        spot=7443.0, call_wall=7600.0, put_wall=7400.0
    )
    assert (call, put, dropped) == (7600.0, 7400.0, [])


def test_no_spot_means_no_walls() -> None:
    """Without a spot the sides are unknowable — refuse both rather than guess."""
    call, put, dropped = apply_side_guard(spot=None, call_wall=7600.0, put_wall=7400.0)
    assert call is None and put is None
    assert dropped == ["call_wall", "put_wall"]


def test_uw_row_wins_over_gex_snapshot() -> None:
    levels = resolve_levels(
        uw_row={
            "market_date": date(2026, 7, 28),
            "call_wall": 7500.0,
            "put_wall": 7300.0,
            "gamma_flip": 7450.0,
            "spot": 7383.0,
        },
        gex_row={
            "data_date": date(2026, 7, 28),
            "call_wall": 7000.0,
            "put_wall": 7000.0,
            "gamma_flip": 7525.0,
            "spot": 7383.0,
        },
    )
    assert levels.source == "uw_gex_levels_daily"
    assert levels.call_wall == 7500.0
    assert levels.gamma_flip == 7450.0
    assert levels.dropped == []


def test_falls_back_to_snapshot_and_still_guards() -> None:
    levels = resolve_levels(
        uw_row=None,
        gex_row={
            "data_date": date(2026, 7, 28),
            "call_wall": 7000.0,
            "put_wall": 7000.0,
            "gamma_flip": 7525.0,
            "spot": 7383.0,
        },
    )
    assert levels.source == "gex_snapshots"
    assert levels.call_wall is None
    assert levels.dropped == ["call_wall"]
    # gamma flip is exempt from the guard and survives above spot
    assert levels.gamma_flip == 7525.0
    assert levels.empty is False


def test_no_rows_at_all_is_empty_not_an_error() -> None:
    levels = resolve_levels(uw_row=None, gex_row=None)
    assert levels.empty is True
    assert levels.source is None


def test_decimal_columns_survive_the_coercion() -> None:
    """uw_gex_levels_daily is NUMERIC, so psycopg hands back Decimal. The guard has
    to compare those, not silently drop every level as unparseable."""
    levels = resolve_levels(
        uw_row={
            "market_date": date(2026, 7, 28),
            "call_wall": Decimal("7500.0"),
            "put_wall": Decimal("7300.0"),
            "gamma_flip": Decimal("7450.0"),
            "spot": Decimal("7383.0"),
        },
        gex_row=None,
    )
    assert (levels.call_wall, levels.put_wall, levels.gamma_flip) == (
        7500.0,
        7300.0,
        7450.0,
    )
    assert levels.dropped == []


def test_anchor_close_substitutes_for_a_missing_spot() -> None:
    levels = resolve_levels(
        uw_row={
            "market_date": date(2026, 7, 28),
            "call_wall": 7500.0,
            "put_wall": 7300.0,
            "gamma_flip": None,
            "spot": None,
        },
        gex_row=None,
        chart_spot=7383.0,
    )
    assert levels.spot == 7383.0
    assert (levels.call_wall, levels.put_wall) == (7500.0, 7300.0)


def test_guard_uses_the_chart_price_not_the_rows_own_spot() -> None:
    """The level row is internally consistent — call wall 100 above ITS spot — but the
    market has since moved above the wall. Judged against the row's own spot both walls
    survive and the chart draws 'resistance' underneath price, which is the false line
    this module exists to prevent. Judged against the price actually plotted, the call
    wall goes."""
    row = {
        "market_date": date(2026, 7, 22),
        "call_wall": 7500.0,
        "put_wall": 7300.0,
        "gamma_flip": 7450.0,
        "spot": 7400.0,
    }
    stale = resolve_levels(uw_row=row, gex_row=None, chart_spot=7600.0)
    assert stale.call_wall is None
    assert stale.dropped == ["call_wall"]
    assert stale.spot == 7600.0

    # Same row, chart drawn where it was captured: nothing is dropped.
    same_day = resolve_levels(uw_row=row, gex_row=None, chart_spot=7400.0)
    assert same_day.call_wall == 7500.0
    assert same_day.dropped == []
