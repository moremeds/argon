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

`uw_scan.fundamentals.underwriting` holds a SEPARATE, purely descriptive
derivation (spec §5-v): DIO, SBC/revenue, shares-outstanding YoY. It imports
`_f` from here (the same pattern `valuation_math.py` already uses) and does
not join `FEATURES` and never will by accident — appending to `FEATURES`
moves every cross-sectional z-score in the composite and would need an
engine-version bump for what is a display need, not a scoring need. Split
into its own module rather than grown here once this file passed its own
<500-line target and the underwriting block was already a cohesive,
separately-purposed derivation (fix round 1, 2026-08-28).
"""

from __future__ import annotations

from collections.abc import Mapping
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
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: non-numeric statement cell → None
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


# Fields worth showing that are NOT inputs to the ratio. They render dimmed and
# labelled `context`, and are excluded from the reconciliation invariant by
# construction — only role="input" series participate in it.
FEATURE_CONTEXT: dict[str, tuple[str, ...]] = {
    "gross_margin": ("cost_of_revenue",),
    "op_margin": ("research_and_development", "selling_general_and_administrative"),
}

_LABELS: dict[str, str] = {
    "total_revenue": "revenue",
    "gross_profit": "gross profit",
    "cost_of_revenue": "cost of revenue",
    "operating_income": "operating income",
    "research_and_development": "R&D",
    "selling_general_and_administrative": "SG&A",
    "operating_cashflow": "operating cash flow",
    "capital_expenditures": "capex",
    "net_income": "net income",
    "total_shareholder_equity": "shareholder equity",
    "short_long_term_debt_total": "total debt",
    "cash_and_cash_equivalents": "cash",
    "ebitda": "EBITDA",
    "total_assets": "total assets",
    "rev_ttm_prev": "revenue TTM, 4q earlier",
}

# Statement each raw field is read from, so a series resolves without guessing.
_SOURCE: dict[str, str] = {
    "total_revenue": "income",
    "gross_profit": "income",
    "cost_of_revenue": "income",
    "operating_income": "income",
    "research_and_development": "income",
    "selling_general_and_administrative": "income",
    "net_income": "income",
    "ebitda": "income",
    "operating_cashflow": "cash_flow",
    "capital_expenditures": "cash_flow",
    "total_shareholder_equity": "balance",
    "total_assets": "balance",
    "short_long_term_debt_total": "balance",
    "cash_and_cash_equivalents": "balance",
}

# Fields summed over four quarters rather than read per quarter. Mirrors the
# `_ttm(...)` calls in `build_features`; edit the two together.
_TTM_FIELDS: dict[str, frozenset[str]] = {
    "rev_growth": frozenset({"total_revenue"}),
    "gross_margin": frozenset(),
    "op_margin": frozenset(),
    "fcf_margin": frozenset(
        {"operating_cashflow", "capital_expenditures", "total_revenue"}
    ),
    "roe": frozenset({"net_income"}),
    "neg_net_debt_ebitda": frozenset({"ebitda"}),
    "asset_turnover": frozenset({"total_revenue"}),
}


def feature_basis(feature: str) -> str:
    """ "ttm" | "quarterly" | "mixed", DERIVED rather than hand-listed.

    An earlier draft carried a `FEATURE_BASIS` dict alongside `_TTM_FIELDS`. Two
    hand-maintained maps describing one fact drift; this one cannot. Adding a
    field to `_TTM_FIELDS` now moves the label automatically, which is the
    behaviour you want when the arithmetic is what changed.
    """
    ttm = _TTM_FIELDS[feature]
    total = len(FEATURE_INPUTS[feature])
    if len(ttm) == total:
        return "ttm"
    if not ttm:
        return "quarterly"
    return "mixed"


def build_feature_details(uw: Mapping[str, Any], quarters: int = 20) -> dict[str, Any]:
    """Per feature: the component series its ratio is computed from, plus the ratio.

    Serves the card's back side. Lives beside `build_features` and reuses `_f`
    and `_ttm` deliberately — the back states the figures behind the front's
    number, so the two must be one definition rather than two that agree today.

    `uw` is ONE ticker's entry from `FundamentalObsRepository.statement_panel`.
    """
    inc = uw["income-statements"]
    bs = uw["balance-sheets"]
    cf = uw["cash-flows"]
    by_source = {"income": inc, "balance": bs, "cash_flow": cf}

    all_periods = sorted(inc)
    keep = all_periods[-quarters:] if quarters > 0 else all_periods
    offset = len(all_periods) - len(keep)

    currency = None
    for p in reversed(all_periods):
        currency = _f_str(inc.get(p), "reported_currency")
        if currency:
            break

    def value(field: str, feature: str, i_all: int) -> float | None:
        src = by_source[_SOURCE[field]]
        if field in _TTM_FIELDS[feature]:
            return _ttm(src, all_periods, i_all, field)
        return _f(src.get(all_periods[i_all]), field)

    ratios = build_features({"_": uw})["_"]

    features: list[dict[str, Any]] = []
    for feature, fields in FEATURE_INPUTS.items():
        series: list[dict[str, Any]] = []
        for field in fields:
            # The SAME field is quarterly under one feature and a four-quarter
            # sum under another — `total_revenue` is per-quarter for
            # `gross_margin` and TTM for `asset_turnover`, figures differing by
            # ~4x. So the KEY carries the basis, not just the label: a series
            # keyed `total_revenue` holding a TTM sum is mislabelled data, and a
            # consumer joining on that key would be silently wrong.
            is_ttm = field in _TTM_FIELDS[feature]
            series.append(
                {
                    "key": f"{field}_ttm" if is_ttm else field,
                    "label": _LABELS.get(field, field) + (" TTM" if is_ttm else ""),
                    "role": "input",
                    "unit": "currency",
                    "values": [
                        value(field, feature, offset + i) for i in range(len(keep))
                    ],
                }
            )
        if feature == "rev_growth":
            # The denominator is the SAME field four quarters back, so it needs a
            # distinct key or it would collide with the numerator's series.
            series.append(
                {
                    "key": "rev_ttm_prev",
                    "label": _LABELS["rev_ttm_prev"],
                    "role": "input",
                    "unit": "currency",
                    "values": [
                        _ttm(inc, all_periods, offset + i - 4, "total_revenue")
                        if offset + i >= 7
                        else None
                        for i in range(len(keep))
                    ],
                }
            )
        for field in FEATURE_CONTEXT.get(feature, ()):
            series.append(
                {
                    "key": field,
                    "label": _LABELS.get(field, field),
                    "role": "context",
                    "unit": "currency",
                    "values": [
                        _f(
                            by_source[_SOURCE[field]].get(all_periods[offset + i]),
                            field,
                        )
                        for i in range(len(keep))
                    ],
                }
            )
        features.append(
            {
                "feature": feature,
                "basis": feature_basis(feature),
                "unit": FEATURE_UNITS[feature],
                "series": series,
                "ratio": [ratios[p][feature] for p in keep],
            }
        )

    # The eighth card. Descriptive: it enters no composite and has no ratio, so
    # `ratio` is all-None rather than absent — one shape for every entry keeps
    # the client from special-casing it.
    def _ttm_series(src: dict, field: str) -> list[float | None]:
        return [_ttm(src, all_periods, offset + i, field) for i in range(len(keep))]

    ocf = _ttm_series(cf, "operating_cashflow")
    capex = _ttm_series(cf, "capital_expenditures")
    features.append(
        {
            "feature": "revenue_earnings",
            "basis": "ttm",
            "unit": "currency",
            "series": [
                {
                    "key": "total_revenue_ttm",
                    "label": "revenue TTM",
                    "role": "input",
                    "unit": "currency",
                    "values": _ttm_series(inc, "total_revenue"),
                },
                {
                    "key": "net_income_ttm",
                    "label": "net income TTM",
                    "role": "input",
                    "unit": "currency",
                    "values": _ttm_series(inc, "net_income"),
                },
                {
                    "key": "fcf_ttm",
                    "label": "free cash flow TTM",
                    "role": "input",
                    "unit": "currency",
                    "values": [
                        None if o is None or c is None else o - abs(c)
                        for o, c in zip(ocf, capex, strict=True)
                    ],
                },
            ],
            "ratio": [None] * len(keep),
        }
    )

    return {
        "period_ends": list(keep),
        "reported_currency": currency,
        "features": features,
    }


def _f_str(row: dict | None, key: str) -> str | None:
    if not row:
        return None
    v = row.get(key)
    return str(v) if v not in (None, "") else None
