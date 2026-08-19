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
    FINANCIALS,
    FINANCIALS_REFUSAL,
    LEVEL_ORDER,
    METHOD_NUMERATOR,
    MAX_BAND_WIDTH,
    MIN_HISTORY,
    TYPE_YIELD,
    WINDOW_QUARTERS,
    build_anchors,
    percentile,
    price_at_yield,
    quarter_inputs,
    rank_percentile,
    yield_at,
    yield_drift,
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


def test_a_level_that_cannot_be_inverted_takes_the_whole_band_with_it():
    """Net debt above the implied enterprise value drives the cheap end below
    zero, and that is fatal to the band rather than a gap inside it.

    This test asserted the opposite until 2026-08-12, when a real bank showed
    what the gap looked like on screen: JPM rendered `observe_mid` at 11.3
    against a spot of 297.8 with `buy_below` blank. The level was correctly
    withheld — rendering it as 0 would say "buy below $0" — but withholding an
    END leaves a band with no extent, and extent is the only claim a band makes.

    An interior gap is unreachable, which is why there is no separate case for
    one: price falls monotonically as the target yield rises and the five targets
    are ordered percentiles of one window, so any failure takes an end first.
    """
    out = _band(net_debt=1e6)
    assert out["anchors"] is None
    assert any("no price at this net debt" in r for r in out["confidence_reasons"])


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


def _wide_history(span: float, n: int = WINDOW_QUARTERS) -> list[float]:
    """A yield history log-spaced over `span`, so the width guard can be aimed.

    Synthetic, like `HISTORY` above and for the same reason: the point is the
    arithmetic of the guard, and a real filer's series cannot be dialled to sit
    a hair over a threshold. No price or ticker is invented — these are yields
    fed straight into the percentile math.
    """
    return [0.01 * span ** (i / (n - 1)) for i in range(n)]


def test_a_refusal_carries_the_window_it_refused_on():
    """`history_quarters: 0` on a refusal is a claim about COVERAGE, and for
    every gate below it is false.

    NVDA in production reads "0q" beside a refusal caused by twenty quarters of
    FCF yield spanning 17x. The data is there and its spread is the finding; the
    header sent readers to hunt a data gap that does not exist.
    """
    wide = _band(history=_wide_history(30.0))
    assert wide["anchors"] is None
    assert wide["history_quarters"] == WINDOW_QUARTERS

    # A bank's shape: net debt above the implied EV kills the cheap end.
    no_end = _band(net_debt=1e6)
    assert no_end["anchors"] is None
    assert no_end["history_quarters"] == WINDOW_QUARTERS

    short = _band(history=HISTORY[: MIN_HISTORY - 1])
    assert short["anchors"] is None
    assert short["history_quarters"] == MIN_HISTORY - 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fundamental": -10.0},
        {"suppressed": True},
        {"company_type": "nonsense"},
    ],
)
def test_a_refusal_taken_before_any_window_reports_no_quarters(kwargs):
    """The converse, and it is not symmetry for its own sake: these gates fire
    before a single quarter is read, so any count here would be invented."""
    assert _band(**kwargs)["history_quarters"] == 0


def test_the_width_refusal_never_prints_a_number_equal_to_its_own_limit():
    """A marginal refusal has to survive its own rounding.

    AVGO on 2026-08-18 spans 4.04x against a 4.0x limit and rendered "spans 4x —
    wider than the 4x limit", a sentence that refutes itself on the only line the
    reader gets. Fixed precision cannot solve this — one decimal
    saves AVGO and breaks the next name in — so the assertion is on the property,
    swept across the margin rather than checked at one point.
    """
    for span in (10.25, 10.4, 10.5, 11.0, 30.0, 100.0):
        out = _band(history=_wide_history(span))
        assert out["anchors"] is None
        (reason,) = [r for r in out["confidence_reasons"] if "spans" in r]
        printed = float(reason.split("spans ")[1].split("x")[0])
        assert printed > MAX_BAND_WIDTH, reason
        # And it still names the window it measured, not the constant: a name
        # refused on 14 usable quarters must not claim it looked at 20.
        assert f"own {WINDOW_QUARTERS}-quarter" in reason

    thin = _band(history=_wide_history(30.0, n=14))
    (reason,) = [r for r in thin["confidence_reasons"] if "spans" in r]
    assert "own 14-quarter" in reason


def test_yield_drift_separates_a_one_way_walk_from_a_swing():
    """The measurement the width refusal now leans on.

    A monotone series must read +/-1 and an oscillation near 0, or the sentence
    it drives is worse than no sentence: it would assert a regime shift over a
    name that simply swings.
    """
    rising = [0.01 * (i + 1) for i in range(20)]
    assert yield_drift(rising) == pytest.approx(1.0)
    assert yield_drift(rising[::-1]) == pytest.approx(-1.0)
    # Alternating high/low: no trend at all — and the case that caught a real
    # defect. Ties took a stable sort's order rather than the average rank, which
    # manufactured +0.57 out of a series with no trend in it.
    assert abs(yield_drift([0.05, 0.15] * 10)) < 0.15
    assert yield_drift([0.05]) == 0.0
    assert yield_drift([0.05] * 20) == 0.0


def test_the_width_refusal_describes_the_window_rather_than_asserting_instability():
    """It used to end "too unstable to anchor a price to" — a CAUSE it never
    measured, and the wrong one for most names it fires on.

    Measured over the 246-name panel on 2026-08-18, 7 of 13 width refusals are
    one-way walks: AVGO -0.90, LRCX -0.85, MSTR -0.83 as the multiple expanded,
    DIS +0.81 and NFLX +0.66 as the fundamental outgrew the price. Those windows
    are the opposite of unstable — they straddle two regimes.
    """
    # Yield falling monotonically = the multiple expanded through the window.
    expanding = _band(history=[0.30 * 0.85**i for i in range(WINDOW_QUARTERS)])
    (reason,) = [r for r in expanding["confidence_reasons"] if "spans" in r]
    assert "too unstable" not in reason
    assert "walking one way" in reason
    assert "the multiple expanded through it" in reason
    assert "rho -" in reason

    # Same window reversed: the fundamental outgrew the price instead.
    outgrew = _band(history=[0.30 * 0.85**i for i in range(WINDOW_QUARTERS)][::-1])
    (reason,) = [r for r in outgrew["confidence_reasons"] if "spans" in r]
    assert "the fundamental outgrew the price through it" in reason
    assert "rho +" in reason


def test_a_genuinely_unsettled_window_is_not_called_a_regime_shift():
    """The converse, and the reason the description is measured rather than
    assumed: ACRE spans 5.3x at rho -0.07 and APLD 17.3x at -0.25. Calling those
    a regime shift would invent a story the data does not tell."""
    swinging = _band(history=[0.05, 0.45] * (WINDOW_QUARTERS // 2))
    (reason,) = [r for r in swinging["confidence_reasons"] if "spans" in r]
    assert "swinging both ways" in reason
    assert "valuation regimes" not in reason


# --------------------------------------------------------------------------
# Deposit-funded balance sheets
# --------------------------------------------------------------------------


def test_a_financial_is_refused_even_when_every_input_is_perfect():
    """The refusal is about the METHOD, not the data.

    `_band()`'s inputs produce a clean ascending band for every other type, and
    they still must not produce one here: what is missing is not history, price
    or a numerator but a denominator that means anything. Asserting on good
    inputs is the point — a test built on bad inputs would pass for the wrong
    reason and keep passing if the guard were deleted.
    """
    out = _band(company_type=FINANCIALS)
    assert out["anchors"] is None
    assert out["spot_percentile"] is None


def test_the_financial_refusal_explains_itself_rather_than_reading_as_a_bug():
    """It must not fall through to "unknown company_type financials".

    That string describes a routing table with a hole in it, and the obvious fix
    for a hole is to fill it — which is exactly the bug this replaces. The reason
    on screen has to say the omission is deliberate and why.
    """
    reasons = _band(company_type=FINANCIALS)["confidence_reasons"]
    assert FINANCIALS_REFUSAL in reasons
    assert not any("unknown company_type" in r for r in reasons)


def test_financials_has_no_yield_and_that_is_what_makes_it_refuse():
    """The guard and the routing table must not be able to disagree.

    If a later edit adds a `financials` entry to TYPE_YIELD, the explicit branch
    above would still refuse and the table would silently claim otherwise. This
    pins the single source of truth: the absence IS the decision.
    """
    assert FINANCIALS not in TYPE_YIELD


def test_a_bank_shaped_balance_sheet_no_longer_depends_on_net_debt_to_refuse():
    """Measured 2026-08-19: `net_debt/market_cap` over the 11 financials in the
    panel ran -0.07 (COF) to 1.73 (GS) — straddling the non-financial
    distribution — so five got a band and six refused on the same business
    model. Routing by type has to make that spread irrelevant.
    """
    # COF's real shape: net CASH on the vendor's `debt - cash`, which is what let
    # it through the old net-debt guard and onto the card with a band.
    net_cash = _band(company_type=FINANCIALS, net_debt=-4.0e9)
    # GS's real shape: net debt large enough to collapse the band's cheap end.
    net_debt = _band(company_type=FINANCIALS, net_debt=1e6)
    for out in (net_cash, net_debt):
        assert out["anchors"] is None
        assert FINANCIALS_REFUSAL in out["confidence_reasons"]
