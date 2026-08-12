"""Stage-3 valuation anchors: a price band from a name's OWN valuation history.

Pure compute, no I/O. Run `uv run python -m uw_scan.fundamentals.valuation` for
the self-check.

WHAT AN ANCHOR IS HERE
----------------------
Each level is the PRICE at which this company's valuation yield would sit at a
stated percentile of its own history:

    yield        = fundamental / EV,     EV = price * shares + net_debt
    EV_at_target = fundamental / target_yield
    price        = (EV_at_target - net_debt) / shares

High yield means cheap, so the percentiles run downward through the band:
`buy_below` is the 80th percentile of the name's own yield history (cheap),
`risk_above` the 20th (expensive). The levels are therefore monotone in price by
construction, and `_self_check` asserts it rather than trusting it.

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

from uw_scan.fundamentals.features import _f, _ttm

#: Percentile of the name's OWN yield history that defines each level. Cheap is a
#: HIGH yield, so these descend as the price levels ascend.
LEVELS: dict[str, float] = {
    "buy_below": 0.80,
    "observe_low": 0.65,
    "observe_mid": 0.50,
    "observe_high": 0.35,
    "risk_above": 0.20,
}

#: Ascending in price. The output contract every method shares (§5.3), and the
#: order `_self_check` and the storage CHECK constraint both enforce.
LEVEL_ORDER = ("buy_below", "observe_low", "observe_mid", "observe_high", "risk_above")

#: `company_type` -> the yield its band is built from. Values are the measured
#: signals; the comment on each is its market-neutral 2q IC.
TYPE_YIELD: dict[str, str] = {
    "chips_cyclical": "sales_to_ev",  # +0.0744 (t 5.77)
    "software_growth": "sales_to_ev",
    "high_risk_growth": "sales_to_ev",
    "platform_scale": "fcf_yield",  # +0.0457 (t 3.64)
    "power_infra": "ebitda_to_ev",  # +0.0446 (t 3.41)
}

#: Yields denominated in enterprise value rather than market cap. The distinction
#: is not cosmetic: inverting an EV yield back to a price has to subtract net debt,
#: and skipping that step misprices every levered name by exactly its net debt.
EV_DENOMINATED = frozenset({"sales_to_ev", "ebitda_to_ev"})

#: Quarters of a name's own history required before a percentile means anything.
#: Matches the research harness's warmup exactly — a band computed off fewer
#: points would be a band the measurement never covered.
MIN_HISTORY = 12

#: Below this the band is emitted with `confidence='low'`. The signal was measured
#: on names carrying 24+ observations.
THIN_HISTORY = 24

#: A filing older than this makes the numerator stale relative to the price the
#: band is being compared against.
STALE_DAYS = 140


def quarter_inputs(
    statements: dict[str, dict[str, Any]], periods: list[str], i: int
) -> dict[str, float | None]:
    """The figures one quarter's yield is built from.

    Numerators are TTM (four quarters, all-or-nothing — a three-quarter "TTM"
    understates by ~25% and is indistinguishable from a real decline). Balance
    sheet items are point-in-time stocks, taken at the quarter itself.
    """
    p = periods[i]
    inc, bs, cf = (
        statements.get("income-statements", {}),
        statements.get("balance-sheets", {}),
        statements.get("cash-flows", {}),
    )
    ocf = _ttm(cf, periods, i, "operating_cashflow")
    capex = _ttm(cf, periods, i, "capital_expenditures")
    debt = _f(bs.get(p), "short_long_term_debt_total")
    cash = _f(bs.get(p), "cash_and_cash_equivalents")
    return {
        "total_revenue": _ttm(inc, periods, i, "total_revenue"),
        "ebitda": _ttm(inc, periods, i, "ebitda"),
        # capex is signed inconsistently by the provider; abs() makes FCF the
        # same quantity regardless of which convention arrived.
        "fcf": (ocf - abs(capex)) if None not in (ocf, capex) else None,
        "shares": _f(bs.get(p), "common_stock_shares_outstanding"),
        "net_debt": (debt or 0.0) - (cash or 0.0),
    }


#: The numerator each method divides. Kept beside TYPE_YIELD so adding a method
#: is one entry in each, and a missing pair fails loudly at the lookup.
METHOD_NUMERATOR = {
    "sales_to_ev": "total_revenue",
    "ebitda_to_ev": "ebitda",
    "fcf_yield": "fcf",
}


def yield_at(
    method: str, inputs: dict[str, float | None], price: float | None
) -> float | None:
    """One quarter's valuation yield at a given share price.

    None whenever any leg is missing or the denominator is non-positive. A
    net-cash name can carry EV <= 0, which would flip the yield's sign and rank
    it as infinitely cheap — those quarters are dropped from the history rather
    than allowed to define its top percentile.
    """
    num = inputs.get(METHOD_NUMERATOR[method])
    shares = inputs.get("shares")
    if num is None or not shares or shares <= 0 or price is None or price <= 0:
        return None
    denom = price * shares
    if method in EV_DENOMINATED:
        denom += inputs.get("net_debt") or 0.0
    return (num / denom) if denom > 0 else None


def percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated order statistic. `sorted_vals` must be ascending."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = p * (len(sorted_vals) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def rank_percentile(sorted_vals: list[float], value: float) -> float:
    """Fraction of history at or below `value` — where spot sits in its own range."""
    if not sorted_vals:
        raise ValueError("empty")
    return sum(1 for v in sorted_vals if v <= value) / len(sorted_vals)


def price_at_yield(
    *, target_yield: float, fundamental: float, net_debt: float, shares: float
) -> float | None:
    """Invert a yield back to the share price that would produce it.

    None when the target yield is non-positive (the inversion diverges through
    zero and would emit a wildly large or negative "price"), or when the implied
    price is itself non-positive — which is a real answer for a name whose net
    debt already exceeds the enterprise value the target implies, but not a
    tradeable level, so it is withheld rather than drawn.
    """
    if target_yield <= 0 or shares <= 0:
        return None
    price = (fundamental / target_yield - net_debt) / shares
    return price if price > 0 else None


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
    method = TYPE_YIELD.get(company_type)
    reasons: list[str] = []
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
    clean = sorted(v for v in history if v is not None and math.isfinite(v))
    if len(clean) < MIN_HISTORY:
        return _no_anchor(
            ticker,
            company_type,
            method,
            [f"only {len(clean)} quarters of own history, need {MIN_HISTORY}"],
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
            f"{len(clean)} quarters of history, below the {THIN_HISTORY} the signal was measured on"
        )
    if knowledge_age_days is not None and knowledge_age_days > STALE_DAYS:
        reasons.append(
            f"latest filing is {knowledge_age_days} days old, so the numerator lags the price"
        )
    if any(v is None for v in anchors.values()):
        missing = sorted(k for k, v in anchors.items() if v is None)
        reasons.append(f"levels not invertible at this net debt: {', '.join(missing)}")

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
    ticker: str, company_type: str, method: str | None, reasons: list[str]
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_type": company_type,
        "method": method,
        "anchors": None,
        "spot": None,
        "spot_percentile": None,
        "history_quarters": 0,
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

    # buy_below sits at the 80th percentile of the yield history.
    y80 = percentile(hist, 0.80)
    assert abs(a["buy_below"] - (1000.0 / y80) / 100.0) < 1e-9

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

    # Every refusal path names itself rather than returning an empty band.
    for kwargs, want in (
        ({"history": hist[:5]}, "own history"),
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
