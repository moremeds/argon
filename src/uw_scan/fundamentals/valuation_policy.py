"""Valuation routing and refusal policy — which method a company type gets, and
when no band may be drawn. Pure constants and text; nothing here computes.

Split out of `valuation.py` under M2.1's module-size budget and re-exported from
it, so no import site changed.

WHY POLICY IS ITS OWN MODULE
----------------------------
These are the parts a reviewer argues about: which yield a type routes to, how
wide a band may be before it says nothing, how stale an input may be. Sitting
beside 200 lines of percentile arithmetic made the arithmetic look like policy
and the policy look like implementation detail.
"""

from __future__ import annotations

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


#: |rho| bands for describing a yield window. Graded rather than binary on
#: purpose: NBIS sits at -0.67 and WFC at -0.68, so a single cut at the
#: conventional 0.7 would print "swings both ways" over two of the strongest
#: leans in the panel. Nothing here gates anything — these words only choose how
#: a sentence reads, and the rho is printed beside them either way.
DRIFT_MONOTONE = 0.7
DRIFT_LEAN = 0.4
