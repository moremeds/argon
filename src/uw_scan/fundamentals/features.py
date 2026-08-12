"""Raw feature derivation from normalized statement payloads. Pure compute.

**This is the validated math, and it lives here so that production and research
cannot drift apart.** `scripts/research/fundamental_signal_validation.py` imports
these definitions rather than owning them; the move was verified by re-running the
wide validation and confirming `validation_wide.json` byte-identical. Any change
here changes a published result, so it needs the same check.

The seven features are the measured inputs behind §5.2's subscores. Four have a
confirmed direction, two (`gross_margin`, `op_margin`) measured INVERTED and carry
no direction claim, and `roe` was tested but is named by no rubric row. The
composite that was validated weights all seven equally — see
`docs/research/2026-08-12-fundamental-weighting-probe/DECISION.md`.
"""

from __future__ import annotations

from typing import Any

FEATURES = [
    "rev_growth",
    "gross_margin",
    "op_margin",
    "fcf_margin",
    "roe",
    "neg_net_debt_ebitda",
    "asset_turnover",
]

# US filers must file a 10-Q within 40-45 days of quarter end. Conservative:
# erring LATE cannot manufacture signal, erring early would.
FALLBACK_LAG_DAYS = 45

# Which raw statement fields each feature is computed FROM. Mirrors the arithmetic
# in `build_features` below — the two must be edited together.
#
# This exists so a rendering surface can refuse a figure whose *input* was flagged
# by an integrity check. Without it a violation on `gross_profit` is recorded and
# then rendered anyway, because the violation names a provider field while the card
# shows a derived feature.
FEATURE_INPUTS: dict[str, tuple[str, ...]] = {
    "rev_growth": ("total_revenue",),
    "gross_margin": ("gross_profit", "total_revenue"),
    "op_margin": ("operating_income", "total_revenue"),
    "fcf_margin": ("operating_cashflow", "capital_expenditures", "total_revenue"),
    "roe": ("net_income", "total_shareholder_equity"),
    "neg_net_debt_ebitda": (
        "short_long_term_debt_total",
        "cash_and_cash_equivalents",
        "ebitda",
    ),
    "asset_turnover": ("total_revenue", "total_assets"),
}

# Whether "higher is better" is a claim we are entitled to make.
#
# Four features measured with a confirmed direction. `gross_margin` and `op_margin`
# measured INVERTED in the 2026-08-12 validation — high-margin names underperformed —
# so no direction is claimed for them, and `roe` is named by no rubric row at all.
# A card that ramps all seven the same way asserts three directions the research
# refused, which is why this rides with the data rather than living in the UI.
FEATURE_DIRECTION: dict[str, str | None] = {
    "rev_growth": "higher_better",
    "gross_margin": None,
    "op_margin": None,
    "fcf_margin": "higher_better",
    "roe": None,
    "neg_net_debt_ebitda": "higher_better",
    "asset_turnover": "higher_better",
}

# "ratio" renders as a percentage; "turns" is a multiple and does not.
FEATURE_UNITS: dict[str, str] = {
    "rev_growth": "ratio",
    "gross_margin": "ratio",
    "op_margin": "ratio",
    "fcf_margin": "ratio",
    "roe": "ratio",
    "neg_net_debt_ebitda": "turns",
    "asset_turnover": "turns",
}


def _f(row: dict | None, key: str) -> float | None:
    if not row:
        return None
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ttm(series: dict[str, dict], periods: list[str], i: int, key: str) -> float | None:
    """Trailing four quarters. None unless all four are present — a 3-quarter
    'TTM' silently understates by ~25% and would be indistinguishable from a
    genuine decline."""
    if i < 3:
        return None
    vals = [_f(series.get(p), key) for p in periods[i - 3 : i + 1]]
    return sum(vals) if all(v is not None for v in vals) else None


def build_features(uw: dict[str, Any]) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per ticker, per period: the raw inputs behind §5.2's subscores."""
    feats: dict[str, dict[str, dict[str, float | None]]] = {}
    for t, per in uw.items():
        inc, bs, cf = per["income-statements"], per["balance-sheets"], per["cash-flows"]
        periods = sorted(inc)
        pf: dict[str, dict[str, float | None]] = {}
        for i, p in enumerate(periods):
            rev_ttm = _ttm(inc, periods, i, "total_revenue")
            rev_ttm_prev = (
                _ttm(inc, periods, i - 4, "total_revenue") if i >= 7 else None
            )
            ocf_ttm = _ttm(cf, periods, i, "operating_cashflow")
            capex_ttm = _ttm(cf, periods, i, "capital_expenditures")
            ebitda_ttm = _ttm(inc, periods, i, "ebitda")
            ni_ttm = _ttm(inc, periods, i, "net_income")
            b = bs.get(p)

            gp, rev_q = _f(inc.get(p), "gross_profit"), _f(inc.get(p), "total_revenue")
            oi = _f(inc.get(p), "operating_income")
            cash, debt = (
                _f(b, "cash_and_cash_equivalents"),
                _f(b, "short_long_term_debt_total"),
            )
            equity, assets = _f(b, "total_shareholder_equity"), _f(b, "total_assets")

            fcf = (
                (ocf_ttm - abs(capex_ttm)) if None not in (ocf_ttm, capex_ttm) else None
            )
            pf[p] = {
                # growth
                "rev_growth": (rev_ttm / rev_ttm_prev - 1)
                if rev_ttm and rev_ttm_prev and rev_ttm_prev > 0
                else None,
                # profitability — NO DIRECTION CLAIMED, both measured inverted
                "gross_margin": (gp / rev_q) if gp is not None and rev_q else None,
                "op_margin": (oi / rev_q) if oi is not None and rev_q else None,
                # capital efficiency
                "fcf_margin": (fcf / rev_ttm) if fcf is not None and rev_ttm else None,
                "roe": (ni_ttm / equity)
                if ni_ttm is not None and equity and equity > 0
                else None,
                # balance sheet (sign flipped so higher is always better)
                "neg_net_debt_ebitda": (-((debt - cash) / ebitda_ttm))
                if None not in (debt, cash, ebitda_ttm)
                and ebitda_ttm
                and ebitda_ttm > 0
                else None,
                "asset_turnover": (rev_ttm / assets) if rev_ttm and assets else None,
            }
        feats[t] = pf
    return feats
