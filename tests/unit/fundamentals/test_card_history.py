"""Trajectory and percentile assembly for the fundamental card.

Two properties carry the honesty of the charts:

- a quarter whose input was flagged becomes a `null` in place, so the renderer
  draws a gap instead of interpolating a smooth line through a figure we do not
  believe;
- disbelieved values are removed from the comparison PANEL, not only from the
  subject, or every name would be ranked against the very rows the card refuses
  to display.

Figures are CEG's real gross margins around the flagged 2026-06-30 quarter.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.fundamentals.card import build_history, build_percentiles

BAD = "gross_profit_equals_revenue_despite_costs"


def _row(day: int, gm, obs_ids, ticker="CEG", **kw):
    base = {
        "as_of": date(2026, 1, day),
        "period_end": date(2026, 1, day),
        "knowledge_date": date(2026, 1, day),
        "filing_date_known": True,
        "composite": Decimal("0.1"),
        "ticker": ticker,
        "rev_growth": Decimal("0.2"),
        "gross_margin": None if gm is None else Decimal(str(gm)),
        "op_margin": Decimal("0.08"),
        "fcf_margin": Decimal("0.01"),
        "roe": Decimal("0.11"),
        "neg_net_debt_ebitda": Decimal("-2.7"),
        "asset_turnover": Decimal("0.32"),
        "source_obs_ids": obs_ids,
    }
    return {**base, **kw}


def test_a_flagged_quarter_becomes_a_gap_in_place():
    """`null` in position, not a dropped point: dropping would shift every later
    quarter left and misdate the whole line."""
    series = [
        _row(1, "0.238", [1]),
        _row(2, "0.428", [2]),
        _row(3, "1.0", [3]),  # the echoed quarter
    ]
    hist = build_history(series, {3: {"gross_profit": [BAD]}})

    assert hist["features"]["gross_margin"] == [0.238, 0.428, None]
    assert hist["dates"] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    # Same length as every other feature, so one x-axis serves all seven.
    assert len(hist["features"]["op_margin"]) == 3


def test_a_flag_in_one_quarter_does_not_blank_the_whole_series():
    """The failure this guards: aggregating violations across observations would
    kill an entire line because one 2019 row was bad."""
    series = [_row(1, "0.238", [1]), _row(2, "1.0", [2]), _row(3, "0.31", [3])]
    gm = build_history(series, {2: {"gross_profit": [BAD]}})["features"]["gross_margin"]
    assert gm == [0.238, None, 0.31]


def test_only_the_features_consuming_the_flagged_field_gap():
    series = [_row(1, "1.0", [1])]
    hist = build_history(series, {1: {"gross_profit": [BAD]}})
    assert hist["features"]["gross_margin"] == [None]
    assert hist["features"]["op_margin"] == [0.08]


def test_empty_series_is_an_empty_history_not_a_crash():
    hist = build_history([], {})
    assert hist["dates"] == []
    assert hist["features"]["gross_margin"] == []


def test_disbelieved_values_are_removed_from_the_panel_itself():
    """Otherwise the top of the gross-margin distribution is built from the ~46
    tickers whose value reads exactly 1.0 for the reason the card rejects."""
    cross = [
        _row(1, "0.10", [1], ticker="AAA"),
        _row(1, "0.20", [2], ticker="BBB"),
        _row(1, "1.00", [3], ticker="CCC"),  # echoed, must not count
        _row(1, "0.30", [4], ticker="DDD"),
    ]
    pct = build_percentiles(cross, {3: {"gross_profit": [BAD]}}, "DDD")

    gm = pct["values"]["gross_margin"]
    # Ranked against 3 believable values (0.10, 0.20, 0.30), not 4 — DDD is top.
    assert gm == {"percentile": 1.0, "n": 3}
    # panel_size counts the names in the bucket; `n` counts usable values.
    assert pct["panel_size"] == 4


def test_a_suppressed_subject_has_no_percentile():
    """Its own value was excluded, so there is nothing to locate."""
    cross = [
        _row(1, "0.10", [1], ticker="AAA"),
        _row(1, "1.00", [2], ticker="CCC"),
    ]
    pct = build_percentiles(cross, {2: {"gross_profit": [BAD]}}, "CCC")
    assert pct["values"]["gross_margin"] is None
    # Its other features are unaffected.
    assert pct["values"]["op_margin"] is not None


def test_denominator_differs_per_feature_and_is_reported():
    """A name missing `roe` is absent from that panel while present in the
    others; a percentile whose denominator is unnamed is not a fact."""
    cross = [
        _row(1, "0.10", [1], ticker="AAA", roe=None),
        _row(1, "0.20", [2], ticker="BBB"),
        _row(1, "0.30", [3], ticker="CCC"),
    ]
    pct = build_percentiles(cross, {}, "CCC")
    assert pct["values"]["gross_margin"]["n"] == 3
    assert pct["values"]["roe"]["n"] == 2


def test_percentile_is_fraction_at_or_below():
    cross = [
        _row(1, str(v / 100), [i], ticker=f"T{i}")
        for i, v in enumerate(range(10, 60, 10))
    ]
    pct = build_percentiles(cross, {}, "T0")
    assert pct["values"]["gross_margin"]["percentile"] == pytest.approx(0.2)
    pct_top = build_percentiles(cross, {}, "T4")
    assert pct_top["values"]["gross_margin"]["percentile"] == pytest.approx(1.0)


def test_a_ticker_absent_from_the_bucket_gets_no_percentiles():
    cross = [_row(1, "0.10", [1], ticker="AAA")]
    pct = build_percentiles(cross, {}, "ZZZZ")
    assert all(v is None for v in pct["values"].values())
    assert pct["panel_size"] == 1


def test_composite_is_never_suppressed_by_a_feature_flag():
    """The composite is a stored scalar, not re-derived here. Nulling it on a
    feature violation would silently invent a different scoring rule."""
    cross = [_row(1, "1.00", [1], ticker="CCC"), _row(1, "0.10", [2], ticker="AAA")]
    pct = build_percentiles(cross, {1: {"gross_profit": [BAD]}}, "CCC")
    assert pct["values"]["gross_margin"] is None
    assert pct["values"]["composite"] is not None
