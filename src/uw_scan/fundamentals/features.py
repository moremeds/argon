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

`underwriting_features` below is a SEPARATE, purely descriptive derivation
(spec §5-v): DIO, SBC/revenue, diluted-share YoY. It does not join `FEATURES`
and never will by accident — appending to `FEATURES` moves every cross-
sectional z-score in the composite and would need an engine-version bump for
what is a display need, not a scoring need. See the block above
`underwriting_features` for the raw-key probe outcome (SBC confirmed present,
diluted share count confirmed ABSENT under any name).
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


# ---------------------------------------------------------------------------
# Underwriting features (spec §5-v) — descriptive only, NOT in FEATURES.
# ---------------------------------------------------------------------------
#
# Raw-key probe, run 2026-08-28 against `option_wizard_local`
# (`uw_scan.fundamental_statement_obs`, real ingested UW payloads):
#
#   SELECT DISTINCT statement, k FROM uw_scan.fundamental_statement_obs,
#          LATERAL jsonb_object_keys(raw_jsonb) k
#    WHERE k ILIKE '%stock%' OR k ILIKE '%compensation%'
#          OR k ILIKE '%dilut%' OR k ILIKE '%share%';
#
# Result:
#   balance    | common_stock_shares_outstanding   (already used by build_features)
#   balance    | common_stock
#   balance    | treasury_stock
#   cash_flow  | dividend_payout_common_stock
#   cash_flow  | stock_based_compensation           <- SBC, CONFIRMED (419 tickers)
#
# No key matching `%dilut%` exists anywhere, on any statement. The income
# statement carries 23 distinct keys total (checked exhaustively) and NONE of
# them is a share count of any kind — no diluted average shares, no basic
# average shares, no EPS. The only share-count field anywhere in the ingested
# statements is `common_stock_shares_outstanding` on `balance`, and that is a
# POINT-IN-TIME shares-outstanding snapshot, not the weighted-average diluted
# count the spec's `share_count_yoy` formula names — a materially different
# quantity (no weighting for buybacks/issuance timing within the quarter).
# Rendering it under the `share_count_yoy` label would be exactly the "proxied
# instead of stated absence" failure this task forbids.
#
# So: `diluted_average_shares` (read from income, per the spec's own naming)
# is looked up honestly below and is absent from EVERY row in the real store.
# `share_count_yoy` therefore evaluates to None for every ticker/period today.
# The absence must render on the node page's limits block as "diluted share
# count not present in the ingested statements" — never as a silent zero,
# never substituted from `common_stock_shares_outstanding`, and never sourced
# from `massive_fundamentals.share_count_delta` (a second vendor; spec §4).
DAYS_PER_QUARTER = 91.25


def _prior_period(periods: list[str], i: int, lookback: int = 4) -> str | None:
    """The sorted-period-list entry `lookback` slots before `periods[i]`.

    Index arithmetic on the SORTED quarterly period list — the same convention
    `build_features` already uses for `rev_growth`'s "TTM ending four quarters
    earlier" comparison (`periods[i - 4]`) — never date arithmetic. A filer's
    fiscal quarter end drifts across a 52/53-week calendar (this repo's SEC
    join elsewhere needs a +/-7 day match for exactly that reason), so
    "period_end minus ~365 days" is not guaranteed to land on an entry that
    exists, and can silently land on the WRONG one when it does. Counting
    sorted-quarter slots instead has no such failure mode as long as the
    periods present are consecutive quarters, the same assumption every other
    TTM/YoY comparison in this module already makes.

    Returns None when fewer than `lookback` periods precede index `i` — a
    genuine gap must yield None, never a wrong-span ratio.
    """
    if i < lookback:
        return None
    return periods[i - lookback]


def underwriting_features(
    uw: dict[str, Any],
) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per ticker, per period: DIO, SBC/revenue, diluted-share YoY.

    Descriptive display metrics — see the block above for why these are not
    in `FEATURES`/`build_features`. Same input shape as `build_features`, same
    `_f` helper, deliberately single-quarter (no TTM smoothing): DIO's
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
            shares_now = _f(inc.get(p), "diluted_average_shares")
            shares_prior = (
                _f(inc.get(prior_p), "diluted_average_shares") if prior_p else None
            )

            pf[p] = {
                "dio": (inv / cogs_q * DAYS_PER_QUARTER)
                if inv is not None and cogs_q
                else None,
                "sbc_to_revenue": (sbc_q / rev_q)
                if sbc_q is not None and rev_q
                else None,
                "share_count_yoy": (shares_now / shares_prior - 1)
                if shares_now is not None and shares_prior
                else None,
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
