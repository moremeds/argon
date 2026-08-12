"""`build_feature_details` must never disagree with `build_features`.

The two live in one module and share `_f`/`_ttm` for exactly this reason: the
back of a card states the figures a ratio came from, so a back whose bars do not
reconcile with its own line is worse than no back at all.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.features import (
    FEATURE_INPUTS,
    build_feature_details,
    build_features,
)

# NVDA's real last TEN fiscal quarters, frozen 2026-08-12 from
# uw_scan.fundamental_statement_obs — every figure as UW reports it.
#
# TEN, not five, and that is load-bearing: `rev_growth` compares a TTM window
# against the TTM window ending four quarters earlier, so it needs EIGHT before
# it can produce a single number. A five-quarter fixture makes the rev_growth
# reconciliation vacuous — every period null, the assertion passes by saying
# nothing.
#
# period, revenue, gross_profit, op_income, net_income, ebitda,
#         equity, assets, debt, cash, ocf, capex
_RAW = [
    (
        "2024-01-31",
        22103,
        16791,
        13614,
        12285,
        14556,
        42978,
        65728,
        11056,
        7280,
        11499,
        254,
    ),
    (
        "2024-04-30",
        26044,
        20406,
        16909,
        14881,
        17753,
        49142,
        77072,
        10991,
        7587,
        15345,
        369,
    ),
    (
        "2024-07-31",
        30040,
        22574,
        18642,
        16599,
        19708,
        58157,
        85227,
        10015,
        8563,
        14488,
        977,
    ),
    (
        "2024-10-31",
        35082,
        26156,
        21869,
        19309,
        22855,
        65899,
        96013,
        10225,
        9107,
        17627,
        813,
    ),
    (
        "2025-01-31",
        39331,
        28723,
        24034,
        22091,
        25821,
        79327,
        111601,
        10270,
        8589,
        16629,
        1077,
    ),
    (
        "2025-04-30",
        44062,
        26668,
        21638,
        18775,
        22584,
        83843,
        125254,
        10285,
        15234,
        27414,
        1227,
    ),
    (
        "2025-07-31",
        46743,
        33853,
        28440,
        26422,
        31937,
        100131,
        140740,
        10598,
        11639,
        15365,
        1895,
    ),
    (
        "2025-10-31",
        57006,
        41849,
        36010,
        31910,
        38748,
        118897,
        161148,
        10822,
        11486,
        23751,
        1636,
    ),
    (
        "2026-01-31",
        68127,
        51093,
        44299,
        42960,
        51283,
        157293,
        206803,
        11412,
        10605,
        36188,
        1284,
    ),
    (
        "2026-04-30",
        81615,
        61157,
        53536,
        58321,
        71002,
        195474,
        259474,
        12814,
        13237,
        50344,
        1757,
    ),
]
_M = 1_000_000  # figures above are in millions; UW serves whole units as strings

_INC = {
    r[0]: {
        "total_revenue": str(r[1] * _M),
        "gross_profit": str(r[2] * _M),
        "cost_of_revenue": str((r[1] - r[2]) * _M),
        "operating_income": str(r[3] * _M),
        "net_income": str(r[4] * _M),
        "ebitda": str(r[5] * _M),
        "reported_currency": "USD",
    }
    for r in _RAW
}
_BS = {
    r[0]: {
        "total_shareholder_equity": str(r[6] * _M),
        "total_assets": str(r[7] * _M),
        "short_long_term_debt_total": str(r[8] * _M),
        "cash_and_cash_equivalents": str(r[9] * _M),
        "reported_currency": "USD",
    }
    for r in _RAW
}
_CF = {
    r[0]: {
        "operating_cashflow": str(r[10] * _M),
        # UW reports capex as a POSITIVE outflow for NVDA. `build_features`
        # takes abs() precisely because the sign is not dependable.
        "capital_expenditures": str(r[11] * _M),
        "reported_currency": "USD",
    }
    for r in _RAW
}
PANEL = {
    "NVDA": {
        "income-statements": _INC,
        "balance-sheets": _BS,
        "cash-flows": _CF,
        "filing_dates": {},
        "obs_ids": {},
    }
}


def _series(detail: dict, key: str) -> list[float | None]:
    for s in detail["series"]:
        if s["key"] == key:
            return s["values"]
    raise AssertionError(f"no series {key} in {[s['key'] for s in detail['series']]}")


def test_gross_margin_reconciles_bars_to_line():
    """The invariant, stated for the simplest feature: line == num/den, per period."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "gross_margin")
    gp, rev = _series(detail, "gross_profit"), _series(detail, "total_revenue")
    for i, r in enumerate(detail["ratio"]):
        if r is None:
            continue
        assert r == pytest.approx(gp[i] / rev[i], rel=1e-12)
    # Not vacuous: the last period must actually be populated.
    assert detail["ratio"][-1] == pytest.approx(61157000000 / 81615000000, rel=1e-12)


# The invariant, written out per feature. Spec §5 requires this for EVERY
# feature, not just the easy one: each formula here is transcribed from
# `build_features`, so a typo in either surfaces as a failure rather than as a
# back side that quietly disagrees with its own front.
# Each lambda is transcribed from `build_features` VERBATIM, including where its
# own guards are inconsistent — `gross_margin` and `op_margin` and `roe` and
# `fcf_margin` test their numerator with `is not None`, while `rev_growth` and
# `asset_turnover` test theirs for truthiness, so a zero TTM revenue yields None
# there rather than a ratio.
#
# That inconsistency is NOT corrected here, and the reason matters: this oracle's
# job is to reproduce the implementation under test, not to improve it. An
# "idealised" oracle disagrees with correct output and fails on the first
# zero-revenue quarter — a real state for a pre-revenue biotech. If the guards
# should be unified, that is a change to `build_features` with its own test,
# because it would move published validation numbers.
RECONCILE = {
    "rev_growth": lambda s: [
        None if not a or not b else a / b - 1
        for a, b in zip(s["total_revenue_ttm"], s["rev_ttm_prev"], strict=True)
    ],
    "gross_margin": lambda s: [
        None if a is None or not b else a / b
        for a, b in zip(s["gross_profit"], s["total_revenue"], strict=True)
    ],
    "op_margin": lambda s: [
        None if a is None or not b else a / b
        for a, b in zip(s["operating_income"], s["total_revenue"], strict=True)
    ],
    "fcf_margin": lambda s: [
        None if None in (o, c) or not r else (o - abs(c)) / r
        for o, c, r in zip(
            s["operating_cashflow_ttm"],
            s["capital_expenditures_ttm"],
            s["total_revenue_ttm"],
            strict=True,
        )
    ],
    "roe": lambda s: [
        None if n is None or not e or e <= 0 else n / e
        for n, e in zip(s["net_income_ttm"], s["total_shareholder_equity"], strict=True)
    ],
    "neg_net_debt_ebitda": lambda s: [
        None if None in (d, c, e) or not e or e <= 0 else -((d - c) / e)
        for d, c, e in zip(
            s["short_long_term_debt_total"],
            s["cash_and_cash_equivalents"],
            s["ebitda_ttm"],
            strict=True,
        )
    ],
    "asset_turnover": lambda s: [
        None if not r or not a else r / a
        for r, a in zip(s["total_revenue_ttm"], s["total_assets"], strict=True)
    ],
}


@pytest.mark.parametrize("feature", sorted(FEATURE_INPUTS))
def test_every_feature_reconciles_its_bars_to_its_line(feature):
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == feature)
    inputs = {s["key"]: s["values"] for s in detail["series"] if s["role"] == "input"}
    expected = RECONCILE[feature](inputs)
    assert len(expected) == len(detail["ratio"])
    for i, (got, want) in enumerate(zip(detail["ratio"], expected, strict=True)):
        if want is None:
            assert got is None, (feature, i)
        else:
            assert got == pytest.approx(want, rel=1e-12), (feature, i)
    # Not vacuous: at least one period must actually reconcile to a number.
    assert any(r is not None for r in detail["ratio"]), feature


def test_all_seven_features_are_present():
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    assert {f["feature"] for f in out["features"]} >= set(FEATURE_INPUTS)


def test_details_agree_with_build_features():
    """The anti-drift assertion. If someone edits one formula, this fails.

    Scoped to FEATURE_INPUTS on purpose: `build_features` holds the seven SCORED
    features and nothing else, so iterating every entry in the detail response
    would `KeyError` on the descriptive `revenue_earnings` card the moment Task 7
    lands.
    """
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    feats = build_features(PANEL)["NVDA"]
    for detail in out["features"]:
        if detail["feature"] not in FEATURE_INPUTS:
            continue
        for i, period in enumerate(out["period_ends"]):
            expected = feats[period][detail["feature"]]
            got = detail["ratio"][i]
            if expected is None:
                assert got is None, (detail["feature"], period)
            else:
                assert got == pytest.approx(expected, rel=1e-12), (
                    detail["feature"],
                    period,
                )


def test_ttm_features_are_none_before_four_quarters():
    """`_ttm` yields None until four quarters exist; the detail must not paper
    over that with a partial sum."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "roe")
    assert detail["basis"] == "mixed"
    assert detail["ratio"][:3] == [None, None, None]
    assert detail["ratio"][-1] is not None


def test_currency_is_reported_not_assumed():
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    assert out["reported_currency"] == "USD"


def test_quarters_limit_takes_the_most_recent():
    out = build_feature_details(PANEL["NVDA"], quarters=2)
    assert out["period_ends"] == ["2026-01-31", "2026-04-30"]


def test_revenue_earnings_is_descriptive_and_carries_no_ratio():
    """The eighth card enters no score, so it has no ratio to reconcile. It must
    still be a first-class entry rather than something the UI assembles by hand,
    or its TTM sums would be a second implementation of `_ttm`."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "revenue_earnings")
    assert detail["basis"] == "ttm"
    assert detail["unit"] == "currency"
    assert all(r is None for r in detail["ratio"])
    assert {s["key"] for s in detail["series"]} == {
        "total_revenue_ttm",
        "net_income_ttm",
        "fcf_ttm",
    }
    # Real NVDA TTM revenue over the last four frozen quarters.
    rev = next(s for s in detail["series"] if s["key"] == "total_revenue_ttm")
    assert rev["values"][-1] == pytest.approx(
        46743000000 + 57006000000 + 68127000000 + 81615000000
    )
    assert rev["values"][0] is None  # fewer than four quarters available


def test_revenue_earnings_is_not_in_feature_inputs():
    """It must never join the scored set: the composite's measured verdicts cover
    exactly the seven in FEATURE_INPUTS."""
    assert "revenue_earnings" not in FEATURE_INPUTS
