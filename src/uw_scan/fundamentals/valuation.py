"""Stage-3 valuation anchors: a price band from a name's OWN valuation history.

Pure compute, no I/O. Run `uv run python -m uw_scan.fundamentals.valuation` for
the self-check.

WHAT AN ANCHOR IS HERE
----------------------
Each level is the PRICE at which this company's valuation yield would sit at a
stated percentile of its own RECENT history — the trailing `WINDOW_QUARTERS`:

    yield        = fundamental / EV,     EV = price * shares + net_debt
    EV_at_target = fundamental / target_yield
    price        = (EV_at_target - net_debt) / shares

High yield means cheap, so the percentiles run downward through the band:
`buy_below` is the 80th percentile of the name's own yield window (cheap),
`risk_above` the 20th (expensive). The levels are therefore monotone in price by
construction, and `_self_check` asserts it rather than trusting it.

The window is trailing, not the full history, and that is load-bearing rather
than a tuning choice — see `WINDOW_QUARTERS` for the two failures it fixes and
the probe that says the signal survives it.

THIS IS A DELIBERATE NARROWING OF SPEC §5.3, AND THE REASON IS THE MEASUREMENT
------------------------------------------------------------------------------
The spec describes richer per-type methods — "through-cycle EV/Sales with
peak/trough margin normalization" for `chips_cyclical`, "EV/Sales banded by
Rule-of-40" for `software_growth`. Those were written in 2026-08-10, before any
of it was measured.

What was measured (2026-08-12, `docs/research/2026-08-12-fundamental-valuation-timeseries/VERDICT.md`)
is the plain own-history percentile of a plain valuation yield: `sales_to_ev` at
market-neutral 2q IC **+0.0744 (t 5.77)**, rising to +0.0826 when a pure-reversal
control is held constant. Margin normalization and Rule-of-40 banding are
unvalidated transforms that would sit ON TOP of a validated one, and every one of
them would move the number the card shows away from the number the evidence
covers. So `company_type` selects WHICH yield, and nothing else:

    chips_cyclical / software_growth / high_risk_growth -> sales_to_ev   (+0.0744)
    platform_scale                                      -> fcf_yield     (+0.0457)
    power_infra                                         -> ebitda_to_ev  (+0.0446)

That mapping is §5.3's own anchor-basis column, kept intact. Only the modelling
layer on top of it is dropped, and it can be added back the moment a probe
licenses it.

WHAT IS NOT BUILT, AND WHY NOT
------------------------------
§7 also lists a base/bear/bull x 1y/3y scenario grid. Producing one requires
forecasting revenue or FCF several years out, and nothing in this repo validates
any growth model. A grid of invented forward figures rendered beside measured
anchors would read as equally supported. Omitted until something licenses it.

THE BAND IS OWN-HISTORY, NEVER CROSS-SECTIONAL
----------------------------------------------
Load-bearing, because the same word carries opposite signs in this universe.
Ranking a name against OTHER names on value is INVERTED here (`book_to_price` IC
-0.0365, t -2.32): a cross-sectional `buy_below` would point at the half of the
panel that then underperforms. Ranking a name against ITS OWN history is the
result above. Any future edit that reaches for a peer distribution to build this
band is reintroducing a measured-negative signal under a measured-positive name.
"""
from __future__ import annotations

import math
from typing import Any

from uw_scan.fundamentals.valuation_math import (
    METHOD_NUMERATOR,
    _over,
    _shape,
    anchor_inputs_hash,
    percentile,
    price_at_yield,
    quarter_inputs,
    rank_percentile,
    yield_at,
    yield_drift,
)
from uw_scan.fundamentals.valuation_policy import (
    ANCHOR_RULES_REV,
    DRIFT_LEAN,
    DRIFT_MONOTONE,
    EV_DENOMINATED,
    FINANCIALS,
    FINANCIALS_REFUSAL,
    LEVEL_ORDER,
    LEVELS,
    MAX_BAND_WIDTH,
    MIN_HISTORY,
    STALE_DAYS,
    THIN_HISTORY,
    TYPE_YIELD,
    UNCLASSIFIED,
    WINDOW_QUARTERS,
)

# Re-exported so `from uw_scan.fundamentals.valuation import X` keeps working for
# every X this module ever exported. M2.1 moved code, not the public surface.
__all__ = [
    "ANCHOR_RULES_REV",
    "DRIFT_LEAN",
    "DRIFT_MONOTONE",
    "EV_DENOMINATED",
    "FINANCIALS",
    "FINANCIALS_REFUSAL",
    "LEVELS",
    "LEVEL_ORDER",
    "MAX_BAND_WIDTH",
    "METHOD_NUMERATOR",
    "MIN_HISTORY",
    "STALE_DAYS",
    "THIN_HISTORY",
    "TYPE_YIELD",
    "UNCLASSIFIED",
    "WINDOW_QUARTERS",
    "anchor_inputs_hash",
    "build_anchors",
    "percentile",
    "price_at_yield",
    "quarter_inputs",
    "rank_percentile",
    "yield_at",
    "yield_drift",
]


def build_anchors(
    *,
    ticker: str,
    company_type: str,
    history: list[float],
    fundamental: float,
    net_debt: float,
    shares: float,
    spot: float | None,
    knowledge_age_days: int | None,
    suppressed: bool = False,
) -> dict[str, Any]:
    """The five levels for one name, plus where spot sits and why to doubt it.

    `history` is that ticker's own yield observations, one per quarter, each
    computed at its own knowledge date — the same series the validation measured.
    Order does not matter; it is sorted here.

    Always returns a dict. An unanchorable name gets `anchors: None` with a
    populated `confidence_reasons`, never a silent empty band: the card's job is
    to say what it lacks, and a missing block reads as "nothing to say".
    """
    reasons: list[str] = []
    if company_type == FINANCIALS:
        # Before the TYPE_YIELD lookup, and with its own reason: falling through
        # to "unknown company_type financials" would read as a routing bug and
        # invite someone to close it by adding a yield.
        return _no_anchor(ticker, company_type, None, [FINANCIALS_REFUSAL])
    method = TYPE_YIELD.get(company_type)
    if method is None:
        return _no_anchor(
            ticker, company_type, None, [f"unknown company_type {company_type}"]
        )
    if suppressed:
        return _no_anchor(
            ticker, company_type, method, ["numerator failed a data-quality check"]
        )
    if fundamental <= 0:
        # A negative numerator has no defensible price inversion: every level
        # would flip sign with it. Common for fcf_yield, never for sales_to_ev.
        return _no_anchor(
            ticker, company_type, method, [f"{method} numerator is not positive"]
        )
    # Take the trailing window BEFORE sorting: `history` arrives oldest-first, so
    # slicing after the sort would keep the twenty largest yields rather than the
    # twenty most recent, silently building the band from a name's cheapest era.
    recent = [v for v in history if v is not None and math.isfinite(v)]
    window = recent[-WINDOW_QUARTERS:]
    clean = sorted(window)
    if len(clean) < MIN_HISTORY:
        return _no_anchor(
            ticker,
            company_type,
            method,
            [
                f"only {len(clean)} of the last {WINDOW_QUARTERS} quarters are "
                f"usable, need {MIN_HISTORY}"
            ],
            history_quarters=len(clean),
        )

    ev_based = method in EV_DENOMINATED
    nd = net_debt if ev_based else 0.0

    # CURRENCY CONSISTENCY, and it is not a theoretical guard.
    #
    # Enterprise value adds a market cap (price x shares) to a balance-sheet
    # figure. Those must be in the same currency, and for a foreign issuer they
    # are not: TSM files in TWD while its ADR trades in USD, so on 2026-08-12 it
    # produced revenue 4.45e12 (NT$) against a 2.10e12 market cap (US$) and an
    # enterprise value of MINUS 5.5e10. The five levels still came out looking
    # like plausible share prices ($443-574) — a wrong band reads exactly like a
    # right one, which is what makes this worth refusing rather than flagging.
    #
    # A non-positive EV at the CURRENT price is the cheapest general detector: it
    # catches any unit or currency mismatch without needing an FX table or a list
    # of foreign filers. A genuine net-cash-above-market-cap company is vanishingly
    # rare and equally unanchorable by this method, so refusing it costs nothing.
    if ev_based and spot is not None and spot > 0 and shares > 0:
        if spot * shares + nd <= 0:
            return _no_anchor(
                ticker,
                company_type,
                method,
                [
                    "enterprise value is not positive at the current price — the "
                    "statements and the quote are most likely in different "
                    "currencies (foreign issuer / ADR)"
                ],
                history_quarters=len(clean),
            )

    anchors: dict[str, float | None] = {}
    for level, p in LEVELS.items():
        anchors[level] = price_at_yield(
            target_yield=percentile(clean, p),
            fundamental=fundamental,
            net_debt=nd,
            shares=shares,
        )

    if len(clean) < THIN_HISTORY:
        reasons.append(
            f"only {len(clean)} usable quarters in the trailing "
            f"{WINDOW_QUARTERS}-quarter window"
        )
    if knowledge_age_days is not None and knowledge_age_days > STALE_DAYS:
        reasons.append(
            f"latest filing is {knowledge_age_days} days old, so the numerator lags the price"
        )
    # No per-level "not invertible" reason, because an INTERIOR gap cannot occur.
    # Price falls monotonically as the target yield rises, and the five targets
    # are ordered percentiles of one sorted window, so the levels are ordered in
    # price. Whichever failure bites — a non-positive target yield, or net debt
    # above the implied enterprise value — it takes an END first and works
    # inward. Any missing level therefore implies a missing end, which the guard
    # below refuses outright. A branch describing an unreachable state reads as
    # handled coverage and is worse than its absence.

    # A BAND MUST HAVE BOTH ENDS, and this check is what the width guard below
    # was silently missing: it reads `if lo and hi`, so a band with no cheap end
    # skipped the width test entirely and rendered whatever was left.
    #
    # JPM on 2026-08-12 is the case. Its `buy_below` did not invert — a bank's
    # funding sits in `short_long_term_debt_total`, so net debt exceeds the
    # enterprise value its own cheapest multiple implies and the price goes
    # negative — while `observe_mid` came out at 11.3 against a spot of 297.8.
    # Three of five levels, one of them at 4% of the price, and nothing on screen
    # said the band had no bottom.
    #
    # Refuse rather than draw. An interior gap is a gap; a missing END is a band
    # whose extent is unknown, and extent is the only thing a band asserts.
    lo, hi = anchors["buy_below"], anchors["risk_above"]
    if lo is None or hi is None:
        end = "cheap" if lo is None else "expensive"
        return _no_anchor(
            ticker,
            company_type,
            method,
            [
                f"the {end} end of the band has no price at this net debt, so the "
                "band has no extent — usually a company whose debt dominates its "
                "enterprise value, where the equity is too thin a slice for the "
                "inversion to be stable"
            ],
            history_quarters=len(clean),
        )
    if lo > 0 and hi / lo > MAX_BAND_WIDTH:
        return _no_anchor(
            ticker,
            company_type,
            method,
            [
                # No "too unstable to anchor a price to". That named a CAUSE the
                # gate never measured, and for most refused names it is the
                # opposite of what the window does — see `yield_drift`.
                f"own {len(clean)}-quarter valuation range spans "
                f"{_over(hi / lo, MAX_BAND_WIDTH)}x, wider than the "
                f"{MAX_BAND_WIDTH:.0f}x limit: {_shape(window)}"
            ],
            history_quarters=len(clean),
        )

    # Where spot sits: computed from the CURRENT yield against the same history,
    # not by comparing spot to the levels. The two agree by construction, and
    # deriving it from the yield keeps one source of truth when a level is None.
    spot_pct = None
    if spot is not None and spot > 0 and shares > 0:
        ev_now = spot * shares + nd
        if ev_now > 0:
            spot_pct = rank_percentile(clean, fundamental / ev_now)

    confidence = "high"
    if len(clean) < THIN_HISTORY or (
        knowledge_age_days is not None and knowledge_age_days > STALE_DAYS
    ):
        confidence = "medium"
    if company_type == UNCLASSIFIED:
        # Never `high`. The band's math is the measured one, but the choice of
        # WHICH yield rests on a pooled average rather than on anything known
        # about this company — and the reader has no other way to tell.
        confidence = "medium"
        reasons.append(
            "no sector on file for this name, so the band uses the "
            "pooled-universe default (revenue / enterprise value) rather than a "
            "method chosen for its business"
        )
    if company_type == "high_risk_growth":
        # §5.3 makes this downgrade mandatory for the type, independent of data
        # quality: the band is genuinely wide and must be stated as wide.
        confidence = "low"
        reasons.append("high_risk_growth always carries a wide band")

    return {
        "ticker": ticker,
        "company_type": company_type,
        "method": method,
        "anchors": anchors,
        "spot": spot,
        "spot_percentile": spot_pct,
        "history_quarters": len(clean),
        "confidence": confidence,
        "confidence_reasons": reasons,
    }


def _no_anchor(
    ticker: str,
    company_type: str,
    method: str | None,
    reasons: list[str],
    *,
    history_quarters: int = 0,
) -> dict[str, Any]:
    """A refusal, carrying the window it refused ON.

    `history_quarters` is the count of usable quarters behind the decision, not a
    coverage flag, and hardcoding it to 0 made every refusal claim the opposite of
    what happened. NVDA's band is refused because twenty quarters of FCF yield
    span 17x — the data is there and the spread is the finding — but the card
    header rendered "0q", which reads as "nothing ingested for this name" and
    sends a reader to look for a data gap that does not exist.

    It stays 0 only where no window was ever taken: an unknown company type, a
    suppressed or non-positive numerator. Those refuse before any history is
    read, and a count there would be invented.
    """
    return {
        "ticker": ticker,
        "company_type": company_type,
        "method": method,
        "anchors": None,
        "spot": None,
        "spot_percentile": None,
        "history_quarters": history_quarters,
        "confidence": "none",
        "confidence_reasons": reasons,
    }


def _self_check() -> None:
    hist = [0.02 * i for i in range(1, 41)]  # 0.02 .. 0.80, 40 quarters

    assert abs(percentile([1.0, 2.0, 3.0], 0.5) - 2.0) < 1e-12
    assert abs(percentile([1.0, 2.0], 0.5) - 1.5) < 1e-12
    assert rank_percentile([1.0, 2.0, 3.0, 4.0], 2.0) == 0.5

    # Unlevered: EV == market cap, so the inversion is a plain division.
    out = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=hist,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    a = out["anchors"]
    prices = [a[k] for k in LEVEL_ORDER]
    assert all(p is not None for p in prices), a
    assert prices == sorted(prices), f"band must ascend in price: {prices}"
    assert out["confidence"] == "high", out
    assert out["method"] == "sales_to_ev"

    # buy_below sits at the 80th percentile of the TRAILING WINDOW, not of the
    # full history — and `hist` ascends, so the two differ by a lot here.
    y80 = percentile(hist[-WINDOW_QUARTERS:], 0.80)
    assert abs(a["buy_below"] - (1000.0 / y80) / 100.0) < 1e-9
    assert out["history_quarters"] == WINDOW_QUARTERS

    # The window is the MOST RECENT quarters, not the largest values. Slicing
    # after the sort would build the band from the name's cheapest era whenever
    # its multiple had re-rated, which is the failure this window exists to fix.
    falling = list(reversed(hist))  # richest first, cheapest last
    fell = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=falling,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    assert fell["anchors"]["buy_below"] != a["buy_below"], (
        "reversing the series must change the band, or the slice is order-blind"
    )
    # `percentile` takes an ASCENDING list, and this slice is descending.
    assert (
        abs(
            fell["anchors"]["buy_below"]
            - (1000.0 / percentile(sorted(falling[-WINDOW_QUARTERS:]), 0.80)) / 100.0
        )
        < 1e-9
    )

    # Net debt shifts an EV-denominated band DOWN by exactly net_debt/shares.
    lev = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=hist,
        fundamental=1000.0,
        net_debt=500.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    assert abs(lev["anchors"]["observe_mid"] - (a["observe_mid"] - 5.0)) < 1e-9

    # ... and leaves a market-cap-denominated band untouched.
    mc = build_anchors(
        ticker="AAA",
        company_type="platform_scale",
        history=hist,
        fundamental=1000.0,
        net_debt=500.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    assert mc["method"] == "fcf_yield"
    assert abs(mc["anchors"]["observe_mid"] - a["observe_mid"]) < 1e-9

    # Spot percentile is monotone: a lower price is a cheaper name.
    cheap = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=hist,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=10.0,
        knowledge_age_days=30,
    )
    rich = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=hist,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=500.0,
        knowledge_age_days=30,
    )
    assert cheap["spot_percentile"] > rich["spot_percentile"], (
        cheap["spot_percentile"],
        rich["spot_percentile"],
    )

    # An unclassified name bands on the pooled default and NEVER reads `high`.
    unc = build_anchors(
        ticker="AAA",
        company_type=UNCLASSIFIED,
        history=hist,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    assert unc["method"] == "sales_to_ev", unc
    assert unc["anchors"]["buy_below"] == a["buy_below"], "same math, same band"
    assert unc["confidence"] == "medium", unc
    assert any("pooled-universe default" in r for r in unc["confidence_reasons"])

    # The identity of a band covers its inputs AND the rules that made it. The
    # shipped bug was the opposite: anchor rows hashed `scoring.inputs_hash`,
    # which reads the seven scoring FEATURES by name, so a band — which has none
    # of them — reduced to a function of company_type and engine, and a corrected
    # result collided with the wrong row it was meant to replace.
    base_hash = dict(
        company_type="chips_cyclical",
        engine="v1_equal",
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        history_n=20,
    )
    h = anchor_inputs_hash(**base_hash)
    assert h == anchor_inputs_hash(**base_hash), "must be deterministic"
    for field, other in (
        ("fundamental", 1001.0),
        ("net_debt", 1.0),
        ("shares", 101.0),
        ("history_n", 19),
        ("company_type", UNCLASSIFIED),
        ("engine", "v2"),
    ):
        assert anchor_inputs_hash(**{**base_hash, field: other}) != h, field

    # Every refusal path names itself rather than returning an empty band.
    for kwargs, want in (
        ({"history": hist[:5]}, "quarters are usable"),
        ({"fundamental": -10.0}, "not positive"),
        ({"suppressed": True}, "data-quality"),
        ({"company_type": "nonsense"}, "unknown company_type"),
        # The real TSM shape: TWD statements against a USD ADR quote, which
        # drives enterprise value negative while every level still looks like a
        # plausible share price.
        (
            {
                "net_debt": -2.152e12,
                "fundamental": 4.45e12,
                "shares": 5.186e9,
                "spot": 404.4,
            },
            "different currencies",
        ),
    ):
        base = {
            "ticker": "AAA",
            "company_type": "chips_cyclical",
            "history": hist,
            "fundamental": 1000.0,
            "net_debt": 0.0,
            "shares": 100.0,
            "spot": 50.0,
            "knowledge_age_days": 30,
        }
        r = build_anchors(**{**base, **kwargs})
        assert r["anchors"] is None and r["confidence"] == "none", (kwargs, r)
        assert any(want in x for x in r["confidence_reasons"]), (kwargs, r)

    # Downgrades are mechanical and stack their reasons.
    thin = build_anchors(
        ticker="AAA",
        company_type="chips_cyclical",
        history=hist[:16],
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=400,
    )
    assert thin["confidence"] == "medium"
    assert len(thin["confidence_reasons"]) == 2, thin["confidence_reasons"]

    risky = build_anchors(
        ticker="AAA",
        company_type="high_risk_growth",
        history=hist,
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        spot=50.0,
        knowledge_age_days=30,
    )
    assert risky["confidence"] == "low", risky

    # --- yield construction, the leg that feeds `history` ---
    stmts = {
        "income-statements": dict.fromkeys(
            ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"),
            {"total_revenue": "100", "ebitda": "20"},
        ),
        "balance-sheets": {
            "2025-12-31": {
                "common_stock_shares_outstanding": "100",
                "short_long_term_debt_total": "200",
                "cash_and_cash_equivalents": "50",
            }
        },
        "cash-flows": dict.fromkeys(
            ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"),
            {"operating_cashflow": "30", "capital_expenditures": "-5"},
        ),
    }
    per = sorted(stmts["income-statements"])
    qi = quarter_inputs(stmts, per, 3)
    assert qi["total_revenue"] == 400.0 and qi["ebitda"] == 80.0, qi
    assert qi["fcf"] == 100.0, qi  # capex sign-normalized
    assert qi["net_debt"] == 150.0, qi

    # EV = 10*100 + 150 = 1150; market cap = 1000.
    assert abs(yield_at("sales_to_ev", qi, 10.0) - 400 / 1150) < 1e-12
    assert abs(yield_at("fcf_yield", qi, 10.0) - 100 / 1000) < 1e-12

    # A net-cash name whose EV goes negative drops out rather than ranking as
    # infinitely cheap; the market-cap yield is unaffected.
    rich = {**qi, "net_debt": -5000.0}
    assert yield_at("sales_to_ev", rich, 10.0) is None
    assert yield_at("fcf_yield", rich, 10.0) is not None
    assert yield_at("sales_to_ev", qi, None) is None

    # A yield built at a lower price is a higher yield: cheaper.
    assert yield_at("sales_to_ev", qi, 5.0) > yield_at("sales_to_ev", qi, 50.0)

    # Every routed method has a numerator, and vice versa.
    assert set(TYPE_YIELD.values()) <= set(METHOD_NUMERATOR)

    print("valuation self-check ok")


if __name__ == "__main__":
    _self_check()
