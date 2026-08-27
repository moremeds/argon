"""Underwriting features (spec §5-v): DIO, SBC/revenue, shares-outstanding YoY.

Descriptive display metrics for the node page's underwriting panel — pure
compute, same input shape as `build_features` in `features.py` (per ticker:
`{"income-statements": {period: row}, "balance-sheets": ..., "cash-flows":
...}`). Deliberately NOT part of `FEATURES` / the scored composite and never
will be by accident: appending to `FEATURES` moves every cross-sectional
z-score in the composite and would need an engine-version bump for what is a
display need, not a scoring need.

Split into its own module (fix round 1, 2026-08-28) once `features.py` grew
past its own <500-line target and this block was already a cohesive,
separately-purposed derivation — the repo's rule is to split by domain seam,
not by technical layer, and "descriptive underwriting metrics" is its own
seam from "scored fundamental composite inputs". Imports `_f` from
`features.py` rather than duplicating it, the same cross-module pattern
`valuation_math.py` already uses for `_f`/`_ttm`.

Raw-key probe outcome (2026-08-28, `option_wizard_local`,
`uw_scan.fundamental_statement_obs`, exhaustive — every `(statement, key)`
pair across all three statement types was checked, not a keyword sample):

    SELECT DISTINCT statement, k FROM uw_scan.fundamental_statement_obs,
           LATERAL jsonb_object_keys(raw_jsonb) k
     WHERE k ILIKE '%stock%' OR k ILIKE '%compensation%'
           OR k ILIKE '%dilut%' OR k ILIKE '%share%';

- SBC: `stock_based_compensation` on `cash_flow` — CONFIRMED, 419/420 tickers.
- Diluted/weighted-average share count: NOT FOUND under any name, on any
  statement. Income carries no share-count field of any kind (23 distinct
  keys total, checked exhaustively).

**Fix round 1 ruling:** a permanently-empty column is worse than a narrower
real one. `shares_outstanding_yoy` is sourced from `common_stock_shares_
outstanding` on `balance` — confirmed present for 420/420 tickers (the full
universe), and already a trusted field elsewhere in this codebase
(`valuation_math.py` reads it for EV; `validity.py` already validates it).
That field is BASIC period-end shares outstanding, not the diluted
weighted-average count the original spec wording named — a real, narrower
measure, not a proxy standing in for the wider one, which is why the word
"diluted" appears nowhere on this feature: it is named for exactly what it
measures. It captures net buyback/issuance activity (the period-end share
count moving) but NOT option/RSU/convertible overhang — a reader who needs
dilution overhang specifically must look elsewhere; this column answers a
narrower, honestly-labelled question.

The prior-period lookup (`_prior_period`) resolves by SORTED-PERIOD-LIST
INDEX, not by date arithmetic — the same convention `build_features` already
uses for `rev_growth`'s "TTM ending four quarters earlier" comparison. This
is not a 52/53-week-calendar workaround: `balance` and `income` period_end
values align exactly within one provider's own statement store (verified
100% aligned for AAPL and a 15-ticker sample) — that drift is a cross-vendor
(UW vs. SEC) concern handled elsewhere (`publication_evidence.py`'s ±7-day
join), not a within-UW cross-statement one. Index-based lookup is simply the
natural definition of "N sorted quarters back", and is what every other
TTM/YoY comparison in `features.py` already does.
"""

from __future__ import annotations

from typing import Any

from uw_scan.fundamentals.features import _f

DAYS_PER_QUARTER = 91.25


def _prior_period(periods: list[str], i: int, lookback: int = 4) -> str | None:
    """The sorted-period-list entry `lookback` slots AVAILABLE positions
    before `periods[i]` — index-based, matching `build_features`'
    `rev_growth` convention (see the module docstring).

    Returns None only when fewer than `lookback` periods precede index `i`
    at all — a gap at the START of the series. This does NOT guarantee a
    calendar-YoY span: a gap in the MIDDLE of `periods` (a missed quarter)
    silently yields `periods[i - lookback]`, which is `lookback` *available*
    quarters back, not `lookback` calendar quarters — a multi-year change
    can be labelled YoY. Index-based lookback is the deliberate, existing
    convention (`build_features`'s `rev_growth` makes the same trade), not a
    guarantee this function makes on its own.
    """
    if i < lookback:
        return None
    return periods[i - lookback]


def underwriting_features(
    uw: dict[str, Any],
) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per ticker, per period: DIO, SBC/revenue, shares-outstanding YoY.

    Descriptive display metrics — see the module docstring for why these are
    not in `FEATURES`/`build_features`. Same input shape as `build_features`,
    same `_f` helper, deliberately single-quarter (no TTM smoothing): DIO's
    numerator is a balance-sheet LEVEL at quarter end, so pairing it with that
    same quarter's COGS (x 91.25 days/quarter) preserves the quarter-end
    stocking signal; a TTM denominator would smooth away exactly the
    divergence this panel exists to show. SBC/revenue follows the same
    single-quarter basis so the two columns share a denominator period.
    """
    feats: dict[str, dict[str, dict[str, float | None]]] = {}
    for t, per in uw.items():
        inc, bs, cf = per["income-statements"], per["balance-sheets"], per["cash-flows"]
        periods = sorted(inc)
        pf: dict[str, dict[str, float | None]] = {}
        for i, p in enumerate(periods):
            inv = _f(bs.get(p), "inventory")
            cogs_q = _f(inc.get(p), "cost_of_revenue")
            sbc_q = _f(cf.get(p), "stock_based_compensation")
            rev_q = _f(inc.get(p), "total_revenue")

            prior_p = _prior_period(periods, i)
            shares_now = _f(bs.get(p), "common_stock_shares_outstanding")
            shares_prior = (
                _f(bs.get(prior_p), "common_stock_shares_outstanding")
                if prior_p
                else None
            )

            pf[p] = {
                "dio": (inv / cogs_q * DAYS_PER_QUARTER)
                if inv is not None and cogs_q
                else None,
                "sbc_to_revenue": (sbc_q / rev_q)
                if sbc_q is not None and rev_q
                else None,
                "shares_outstanding_yoy": (shares_now / shares_prior - 1)
                if shares_now is not None and shares_prior
                else None,
            }
        feats[t] = pf
    return feats
