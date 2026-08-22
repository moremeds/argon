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

import hashlib
import json
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

#: The route for a name nothing has classified. NOT a sixth company type — it is
#: the absence of one, and it is spelled out on the card rather than hidden.
#:
#: It exists because the classification input does not: 174 of the 257 names in
#: the ranked universe have no sector in this database at all, and the five types
#: above are an AI-supply-chain taxonomy with no bucket for a bank or a hospital
#: even where a sector is known. Leaving those names unrouted showed nothing to a
#: reader; routing them through an invented type would show a confident band built
#: from a guess.
#:
#: What licenses the default is that the measurement was never per-type. The probe
#: pooled all 247 scored tickers of THIS universe and found `sales_to_ev` at
#: +0.0744 — the strongest of the five yields, and stronger than either
#: type-specific route below. So an unclassified name gets the yield the evidence
#: actually covers, and `build_anchors` caps its confidence at `medium` and says
#: which assumption it is standing on.
UNCLASSIFIED = "unclassified"

#: Deposit- and funding-financed balance sheets: banks, brokers, consumer
#: lenders, and the asset-management and payment names that share their sector.
#:
#: This type deliberately has NO entry in `TYPE_YIELD`, and the absence is the
#: decision. Every yield here is denominated in enterprise value, and
#: `EV = market cap + net debt` treats net debt as a CLAIM ON operating assets.
#: For a deposit-funded firm funding IS the business, and the vendor `debt` field
#: does not carry deposits at all — so `debt - cash` measures neither leverage nor
#: anything else stable, and inverting a yield through it yields a price that
#: means nothing.
#:
#: Measured 2026-08-19 over the 11 financials then in the panel
#: (`docs/research/2026-08-19-valuation-refusal-anatomy/`): `net_debt/market_cap`
#: ran -0.07 (COF) to 1.73 (GS), straddling the whole non-financial distribution
#: (p50 0.05, p99 4.72, max 21.61). Five of the eleven were handed a
#: `medium`-confidence band and six refused — the SAME business model reaching
#: both outcomes, decided by which side of a numeric guard the name landed on.
#: That spread is also why no `net_debt` threshold can stand in for the label: one
#: catching GS/BAC/WFC/JPM also catches EIX, EXC, AES, BXP and ARE, whose EV
#: yields are legitimate, while missing COF, BLK, SOFI and AXP entirely.
#:
#: Any name landing in this type is refused, asset-light ones included, and that
#: is the intended direction of error: a refusal says "no band", a wrong band
#: says "buy below 268.92".
#:
#: The way out is not an exception to this rule. Every method that breaks here is
#: EV-denominated; `fcf_yield` divides by MARKET CAP and never reads `net_debt`
#: (see `EV_DENOMINATED`), so a name routed to `platform_scale` is priced by
#: something this refusal never covered. PYPL is routed that way for exactly that
#: reason — `TICKER_TO_TYPE` in the anchors job carries the measurement. A
#: per-name correction with no such argument belongs in a `manual` assignment,
#: which `assign` already protects from reseeding.
FINANCIALS = "financials"

#: Stated on the card verbatim. A refusal that only said "no band" would read as
#: missing data, and someone would eventually "fix" it by routing the type to a
#: yield — which is precisely the bug this replaces.
FINANCIALS_REFUSAL = (
    "no valuation band for a deposit-funded balance sheet: every method here "
    "prices a company through its enterprise value, and for a bank, broker or "
    "lender the funding is the business rather than a claim against it, so "
    "enterprise value is not a meaningful denominator"
)

#: `company_type` -> the yield its band is built from. Values are the measured
#: signals; the comment on each is its market-neutral 2q IC.
TYPE_YIELD: dict[str, str] = {
    "chips_cyclical": "sales_to_ev",  # +0.0744 (t 5.77)
    "software_growth": "sales_to_ev",
    "high_risk_growth": "sales_to_ev",
    "platform_scale": "fcf_yield",  # +0.0457 (t 3.64)
    "power_infra": "ebitda_to_ev",  # +0.0446 (t 3.41)
    # Pooled-universe default. Same yield as the three types above, for the
    # reason stated on UNCLASSIFIED: it is the pooled result, not a claim that
    # this name resembles a semiconductor company.
    UNCLASSIFIED: "sales_to_ev",
}

#: Yields denominated in enterprise value rather than market cap. The distinction
#: is not cosmetic: inverting an EV yield back to a price has to subtract net debt,
#: and skipping that step misprices every levered name by exactly its net debt.
EV_DENOMINATED = frozenset({"sales_to_ev", "ebitda_to_ev"})

#: TRAILING quarters the percentiles are drawn from. Five years.
#:
#: Not the full history, and the reason is measured. Valuation multiples in this
#: universe are strongly non-stationary: ASML's `sales_to_ev` median fell from
#: 0.5089 in its oldest quarter-quartile to 0.0926 in its newest — a 5.5x
#: structural re-rating — and NVDA's `fcf_yield` 2.8x. A full-history 80th
#: percentile is therefore a multiple from a regime that has gone, and inverting
#: it put ASML's `buy_below` at 255.7 against a spot of 1518: not a conservative
#: level but an unreachable one, which is no information at all.
#:
#: It also fixes a second, unrelated break. TSLA's free cash flow was negative in
#: 36 of its 65 quarters, so most full-history percentiles of `fcf_yield` sit at
#: or below zero and have NO price inversion — its band rendered with three of
#: five levels missing. Across the trailing 20 quarters, 0 of 20 are negative.
#:
#: The window is measured, not assumed. Re-running the validation probe over
#: (expanding, 40q, 20q, 12q) keeps the effect at every width — `sales_to_ev`
#: goes 0.0744 (t 5.77) / 0.0642 / 0.0604 (t 5.45) / 0.0639 — so a trailing
#: window costs little signal and buys a reachable band. 20 over 12 because a
#: percentile wants points to resolve: 12 gives a slightly higher t and a much
#: coarser distribution.
#: Trace: docs/research/2026-08-12-fundamental-valuation-timeseries/.
WINDOW_QUARTERS = 20

#: Quarters required WITHIN the window before a percentile means anything.
#: Matches the research harness's warmup exactly — a band computed off fewer
#: points would be a band the measurement never covered.
MIN_HISTORY = 12

#: Below this the band is emitted with `confidence='medium'`. With a 20-quarter
#: window a full history is 20, so this flags names that cannot fill it.
THIN_HISTORY = 20

#: A filing older than this makes the numerator stale relative to the price the
#: band is being compared against.
STALE_DAYS = 140

#: `risk_above / buy_below` beyond this is refused rather than drawn.
#:
#: A band is a decision surface, and one spanning 72x is not one no matter how
#: correctly each level was computed — which is the whole lesson of the
#: full-history window: every number was right and the set was useless.
#:
#: Measured over the 50 banded names at 20 quarters: median width 1.73x, and the
#: tail is not a smooth continuum but a different population — NBIS 72x, MSTR 47x,
#: APLD 17x, DIS 7.0x. Those are names whose own five-year valuation range still
#: straddles a business transformation (Yandex -> Nebius, a bitcoin treasury), so
#: the honest answer is that their own history cannot anchor a price, not a band
#: with 72x between its ends. 4.0 sits in the empty part of the distribution:
#: it refuses 7 of 50 and touches nothing between 2.5x and 5x except DIS.
MAX_BAND_WIDTH = 4.0


#: Bumped whenever a STRUCTURAL rule changes — a guard added or removed, a level
#: redefined. Threshold moves do not need it: the constants above are hashed
#: directly, so changing one already produces a new identity.
#:
#: rev 4: the yield window is priced from the lake's SILVER tier, on today's
#: split basis, instead of raw bronze closes. Nothing in this module moved, but
#: every historical yield the percentiles are drawn from did: the provider
#: restates share counts onto today's split basis while bronze stores closes
#: raw, so a quarter before a split was yielding a number wrong by the split
#: factor. Not bumping this would be the exact failure the
#: docstring below describes — the corrected band collides with the wrong one on
#: `(ticker, as_of, engine_version, inputs_hash)` and `DO NOTHING` keeps BKNG's
#: $4,702.64 `buy_below` against its $208.25 spot. The inputs hashed here
#: (`fundamental`, `net_debt`, `shares`, `history_n`) are all unchanged by the
#: fix, so the identity cannot see it any other way.
#: rev 3: a refusal reports the window it refused ON rather than a hardcoded 0,
#: and the width refusal describes the window's measured SHAPE instead of
#: asserting instability it never tested for.
#: No guard moved, but what a refusal ROW says about coverage did, and the same
#: inputs under the old rule collide with the corrected row on the identity key —
#: `DO NOTHING` would keep the wrong one for the rest of the day.
#: rev 2: refuse a band with a missing end (`buy_below` / `risk_above` not
#: invertible). rev 1: the original five-level construction.
ANCHOR_RULES_REV = 4


def anchor_inputs_hash(
    *,
    company_type: str,
    engine: str,
    fundamental: float | None,
    net_debt: float | None,
    shares: float | None,
    history_n: int,
) -> str:
    """Identity of ONE band: its inputs, its routing, and the rules that made it.

    Anchors cannot reuse `scoring.inputs_hash`. That function hashes the seven
    scoring FEATURES by name, and a band's inputs are none of them — so every
    anchor row was hashing an all-null feature map and reducing to a function of
    `company_type` and `engine` alone. Measured 2026-08-12: a run that computed
    233 bands wrote 0 rows, because the identity could not see that the numbers
    had changed. That is the silent-and-confident failure the schema comment
    claims this key prevents, sitting inside the key itself.
    METHOD RULES ARE PART OF THE IDENTITY, and that is the second half of the
    bug. The same inputs under a NEW rule are a different result — the
    missing-end guard turns JPM from a three-level band into a refusal without
    touching a single input — and `ON CONFLICT DO NOTHING` would drop the
    correction and keep the wrong row. Hashing the thresholds and the rules
    revision means a rule change appends the corrected row instead.
    """
    payload = {
        "company_type": company_type,
        "engine": engine,
        "inputs": {
            k: (None if v is None else f"{float(v):.10g}")
            for k, v in (
                ("fundamental", fundamental),
                ("net_debt", net_debt),
                ("shares", shares),
                ("history_n", history_n),
            )
        },
        "rules": {
            "rev": ANCHOR_RULES_REV,
            "levels": LEVELS,
            "window": WINDOW_QUARTERS,
            "min_history": MIN_HISTORY,
            "thin_history": THIN_HISTORY,
            "stale_days": STALE_DAYS,
            "max_band_width": MAX_BAND_WIDTH,
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


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


def yield_drift(window: list[float]) -> float:
    """Rank correlation of a yield window against time. -1 walks down, +1 up.

    The width gate cannot tell two very different shapes apart, and it states the
    wrong one. A band spans 17x either because the yield SWINGS — no settled
    valuation, refusing is right and "too unstable" is the true word — or because
    it WALKS one way and stays there, which is a window straddling two regimes
    and the opposite of unstable.

    Measured over the 246-name local panel on 2026-08-18
    (`docs/research/2026-08-18-valuation-band-refusal/WIDTH_ANATOMY.md`), both
    shapes appear among the refused: AVGO -0.90, LRCX -0.85, MSTR -0.83 walked
    down (the multiple expanded), NVDA +0.68 and NFLX +0.66 walked up (the
    fundamental outgrew the price), ACRE -0.07 and APLD -0.25 genuinely swing.

    This does NOT license moving the threshold, and the same probe is why: the
    monotone share is 38% among refused names against 36% among those that pass,
    and a Mann-Whitney on rho gives p=0.16. Shape does not separate wide bands
    from narrow ones as a population. It separates them ONE NAME AT A TIME, which
    is the only claim the refusal line needs to make.

    TIES TAKE THE AVERAGE RANK, and skipping that is not a rounding detail. A
    stable sort hands the earlier index the lower rank inside a tie group, which
    manufactures an upward trend out of nothing: a perfectly alternating series
    scored +0.57 before this, and the sentence it drives would have called that
    window a one-way regime shift.

    The index side has no ties by construction, so with the value side corrected
    this is the Pearson correlation of the two rank vectors.
    """
    n = len(window)
    if n < 2:
        return 0.0
    order = sorted(range(n), key=lambda i: window[i])
    rank = [0.0] * n
    start = 0
    while start < n:
        stop = start
        while stop + 1 < n and window[order[stop + 1]] == window[order[start]]:
            stop += 1
        shared = (start + stop) / 2
        for position in range(start, stop + 1):
            rank[order[position]] = shared
        start = stop + 1
    mean = (n - 1) / 2
    den = sum((i - mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    num = sum((i - mean) * (rank[i] - mean) for i in range(n))
    spread = sum((r - mean) ** 2 for r in rank)
    if spread == 0:
        return 0.0
    return num / (den * spread) ** 0.5


#: |rho| bands for describing a yield window. Graded rather than binary on
#: purpose: NBIS sits at -0.67 and WFC at -0.68, so a single cut at the
#: conventional 0.7 would print "swings both ways" over two of the strongest
#: leans in the panel. Nothing here gates anything — these words only choose how
#: a sentence reads, and the rho is printed beside them either way.
DRIFT_MONOTONE = 0.7
DRIFT_LEAN = 0.4


def _shape(window: list[float]) -> str:
    """How the refusal describes the window it is refusing, in measured terms."""
    rho = yield_drift(window)
    if abs(rho) < DRIFT_LEAN:
        return f"swinging both ways with no one-way drift (rho {rho:+.2f})"
    direction = (
        "the multiple expanded through it"
        if rho < 0
        else "the fundamental outgrew the price through it"
    )
    walk = "walking one way" if abs(rho) >= DRIFT_MONOTONE else "leaning one way"
    return (
        f"{walk} rather than swinging (rho {rho:+.2f}) — the window covers two "
        f"valuation regimes, not one, because {direction}"
    )


def _over(value: float, limit: float) -> str:
    """Format a ratio at the coarsest precision that still reads ABOVE `limit`.

    A marginal refusal has to survive its own rounding. AVGO on 2026-08-18 spans
    4.04x against a 4.0x limit, and `:.0f` rendered it "spans 4x — too unstable
    to anchor a price to": a sentence that refutes itself, on the only line the
    reader has to go on. One decimal fixes AVGO and breaks the next name in at
    4.004x, so the precision follows the number rather than being guessed once.
    """
    for places in (1, 2, 3):
        text = f"{value:.{places}f}"
        if float(text) > limit:
            return text
    return f"{value:.3f}"


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
