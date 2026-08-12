"""Stage-3 anchor bands.

The band is the one block on the card licensed to be prescriptive, so the
properties that keep it honest are the ones worth pinning:

- it ascends in price, because an inverted band tells the reader to buy high;
- a level that cannot be inverted is a GAP, never a zero;
- a band whose inputs are in a different currency from its quote is REFUSED,
  because a wrong band looks exactly like a right one.

Figures are TSM's real 2026-06-30 shape (TWD statements, USD ADR quote) and a
synthetic 40-quarter history where the percentile arithmetic is checkable by hand.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.valuation import (
    LEVEL_ORDER,
    WINDOW_QUARTERS,
    METHOD_NUMERATOR,
    MIN_HISTORY,
    TYPE_YIELD,
    build_anchors,
    percentile,
    price_at_yield,
    quarter_inputs,
    rank_percentile,
    yield_at,
)

# 0.02 .. 0.80 in even steps: the 80th percentile is 0.66, the 50th 0.41.
HISTORY = [round(0.02 * i, 4) for i in range(1, 41)]


def _band(**kw):
    base = {
        "ticker": "AAA",
        "company_type": "chips_cyclical",
        "history": HISTORY,
        "fundamental": 1000.0,
        "net_debt": 0.0,
        "shares": 100.0,
        "spot": 50.0,
        "knowledge_age_days": 30,
    }
    return build_anchors(**{**base, **kw})


def test_the_band_ascends_in_price():
    """An out-of-order band is not a bad number, it is an inverted
    recommendation — `buy_below` above `risk_above` says buy high."""
    prices = [_band()["anchors"][k] for k in LEVEL_ORDER]
    assert all(p is not None for p in prices)
    assert prices == sorted(prices)


def test_buy_below_is_the_80th_percentile_of_the_trailing_window():
    """The whole method in one assertion — and the window is why it is not the
    full history: multiples here re-rate structurally, so a full-history 80th
    percentile is a multiple from a regime that has gone."""
    expected = (1000.0 / percentile(HISTORY[-WINDOW_QUARTERS:], 0.80)) / 100.0
    assert _band()["anchors"]["buy_below"] == pytest.approx(expected)
    # ... and demonstrably NOT the full-history percentile, which this fixture
    # makes a very different number.
    full = (1000.0 / percentile(HISTORY, 0.80)) / 100.0
    assert _band()["anchors"]["buy_below"] != pytest.approx(full)


def test_the_window_is_the_most_recent_quarters_not_the_largest_values():
    """Slicing after the sort would build the band from a name's cheapest era
    whenever its multiple had re-rated — the exact failure the window fixes."""
    rising = _band()["anchors"]["buy_below"]
    falling = _band(history=list(reversed(HISTORY)))["anchors"]["buy_below"]
    assert rising != pytest.approx(falling)


def test_net_debt_shifts_an_ev_band_and_leaves_a_market_cap_band_alone():
    """Skipping the net-debt term misprices every levered name by exactly its
    net debt, and the error is invisible on screen."""
    ev = _band(net_debt=500.0)["anchors"]["observe_mid"]
    assert ev == pytest.approx(_band()["anchors"]["observe_mid"] - 5.0)

    # platform_scale routes to fcf_yield, which is denominated in market cap.
    mc = _band(company_type="platform_scale", net_debt=500.0)
    assert mc["method"] == "fcf_yield"
    assert mc["anchors"]["observe_mid"] == pytest.approx(
        _band()["anchors"]["observe_mid"]
    )


def test_a_twd_balance_sheet_against_a_usd_quote_is_refused():
    """TSM's real 2026-06-30 shape. Revenue 4.45e12 is NT$ while the 2.10e12
    market cap is US$, so enterprise value comes out at -5.5e10 — and the five
    levels still printed as plausible share prices ($443-574) before the guard.

    This is the case the guard exists for: the failure is silent by default.
    """
    out = _band(fundamental=4.45e12, net_debt=-2.152e12, shares=5.186e9, spot=404.4)
    assert out["anchors"] is None
    assert out["confidence"] == "none"
    assert any("different currencies" in r for r in out["confidence_reasons"])


def test_a_market_cap_method_is_not_refused_by_net_cash():
    """The guard is scoped to EV-denominated methods. `fcf_yield` never adds net
    debt, so a net-cash name is perfectly anchorable there and must not be
    swept up by a guard aimed at a different failure."""
    out = _band(company_type="platform_scale", net_debt=-2.152e12, shares=5.186e9)
    assert out["anchors"] is not None


def test_a_level_that_cannot_be_inverted_is_a_gap_not_a_zero():
    """Net debt above the implied enterprise value drives the cheap end below
    zero. Rendering that as 0 would put "buy below $0" on the card."""
    out = _band(net_debt=1e6)
    assert out["anchors"]["buy_below"] is None
    assert any("not invertible" in r for r in out["confidence_reasons"])


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"history": HISTORY[: MIN_HISTORY - 1]}, "quarters are usable"),
        ({"fundamental": -10.0}, "not positive"),
        ({"suppressed": True}, "data-quality"),
        ({"company_type": "nonsense"}, "unknown company_type"),
    ],
)
def test_every_refusal_names_itself(kwargs, expected):
    """A silent empty band reads as "no view on this company", which is a claim
    about the company rather than about our coverage."""
    out = _band(**kwargs)
    assert out["anchors"] is None
    assert any(expected in r for r in out["confidence_reasons"])


def test_spot_percentile_is_monotone_in_price():
    """High = cheap, because every method is a yield. A reversed sign here would
    invert the card's headline sentence while every number stayed plausible."""
    cheap = _band(spot=10.0)["spot_percentile"]
    rich = _band(spot=500.0)["spot_percentile"]
    assert cheap > rich


def test_spot_at_the_median_level_reads_as_the_median_percentile():
    """Cross-check between the two independent paths: the levels come from
    inverting percentiles to prices, the marker from ranking the current yield.
    They must agree, or the marker and the ladder tell different stories."""
    mid = _band()["anchors"]["observe_mid"]
    assert _band(spot=mid)["spot_percentile"] == pytest.approx(0.5, abs=0.03)


def test_high_risk_growth_is_downgraded_regardless_of_data_quality():
    """Spec §5.3 makes this mandatory for the type: the band is genuinely wide
    and has to be stated as wide even on a perfect input set."""
    out = _band(company_type="high_risk_growth")
    assert out["confidence"] == "low"
    assert out["anchors"] is not None


def test_a_stale_filing_downgrades_and_says_by_how_much():
    out = _band(knowledge_age_days=400)
    assert out["confidence"] == "medium"
    assert any("400 days old" in r for r in out["confidence_reasons"])


def test_every_routed_company_type_has_a_numerator():
    """A type routed to a method with no numerator would raise a KeyError deep
    in the job rather than refusing cleanly."""
    assert set(TYPE_YIELD.values()) <= set(METHOD_NUMERATOR)


def test_percentile_and_rank_are_inverses_at_the_ends():
    assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert rank_percentile([1.0, 2.0, 3.0, 4.0], 4.0) == 1.0
    assert (
        price_at_yield(target_yield=0.0, fundamental=1.0, net_debt=0.0, shares=1.0)
        is None
    )


def test_ttm_numerators_are_all_or_nothing():
    """A three-quarter "TTM" understates by ~25% and is indistinguishable from a
    real decline, which would then define a bogus percentile of own history."""
    periods = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    full = {
        "income-statements": dict.fromkeys(periods, {"total_revenue": "100"}),
        "balance-sheets": {"2025-12-31": {"common_stock_shares_outstanding": "10"}},
        "cash-flows": {},
    }
    assert quarter_inputs(full, periods, 3)["total_revenue"] == 400.0
    # One quarter short of four: no TTM at all rather than a partial sum.
    assert quarter_inputs(full, periods, 2)["total_revenue"] is None


def test_a_missing_price_yields_nothing_rather_than_a_default():
    periods = ["2025-12-31"]
    stmts = {
        "income-statements": {"2025-12-31": {"total_revenue": "100"}},
        "balance-sheets": {"2025-12-31": {"common_stock_shares_outstanding": "10"}},
        "cash-flows": {},
    }
    qi = quarter_inputs(stmts, periods, 0)
    assert yield_at("sales_to_ev", qi, None) is None
    assert yield_at("sales_to_ev", qi, 0.0) is None
