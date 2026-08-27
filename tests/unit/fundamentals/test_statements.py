"""Hash stability and integrity checks for fundamental statement normalization.

Fixtures are NVDA's REAL 2026-04-30 quarterly figures as served by UW, frozen at
authoring time. No network at runtime.

The hash tests are the load-bearing ones: `content_hash` is the identity of an
immutable observation, so an unstable hash silently converts every refresh into a
fake restatement, and an over-stable one hides a real one.
"""

from __future__ import annotations

from decimal import Decimal

from uw_scan.fundamentals.statements import (
    check_cross_statement_violations,
    check_violations,
    content_hash,
    normalize,
)

# Real NVDA FY2027-Q1 income statement (period ending 2026-04-30), as returned by
# UW's /api/stock/NVDA/income-statements.
NVDA_INCOME = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "reported_currency": "USD",
    "total_revenue": "81615000000",
    "cost_of_revenue": "20458000000",
    "gross_profit": "61157000000",
    "operating_income": "53536000000",
    "net_income": "58321000000",
    "research_and_development": "6321000000",
    "ebitda": "71002000000",
    "non_interest_income": None,
    "inserted_at": "2026-05-21T06:58:08Z",
    "updated_at": "2026-08-11T03:58:32Z",
}

# Real NVDA balance sheet, same period. Assets == liabilities + equity exactly.
NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "common_stock_shares_outstanding": "24391000000",
    "inserted_at": "2026-05-21T06:58:08Z",
    "updated_at": "2026-08-11T03:58:32Z",
}


def test_provider_ingest_timestamps_do_not_change_identity():
    """The single most important property: UW stamps `inserted_at`/`updated_at`
    on every row and moves them on re-ingest, with no reported figure changing.
    If they reached the hash, every refresh would insert a phantom restatement."""
    moved = dict(
        NVDA_INCOME,
        inserted_at="2027-01-01T00:00:00Z",
        updated_at="2027-01-02T00:00:00Z",
    )
    assert content_hash(normalize(NVDA_INCOME)) == content_hash(normalize(moved))


def test_string_and_numeric_spellings_are_one_fact():
    """UW serves figures as strings. A provider that switches to JSON numbers is
    reporting the same fact, not restating it."""
    as_number = dict(NVDA_INCOME, total_revenue=81615000000)
    assert content_hash(normalize(NVDA_INCOME)) == content_hash(normalize(as_number))


def test_a_changed_figure_rehashes():
    restated = dict(NVDA_INCOME, total_revenue="81615000001")
    assert content_hash(normalize(NVDA_INCOME)) != content_hash(normalize(restated))


def test_new_always_null_column_does_not_rehash_history():
    """A provider adding a column must not re-hash every historical row."""
    widened = dict(NVDA_INCOME, some_new_field=None)
    assert content_hash(normalize(NVDA_INCOME)) == content_hash(normalize(widened))


def test_value_becoming_null_does_rehash():
    """The inverse: a figure that stops being reported IS a change."""
    dropped = dict(NVDA_INCOME, gross_profit=None)
    assert content_hash(normalize(NVDA_INCOME)) != content_hash(normalize(dropped))


def test_normalize_drops_nulls_and_envelope_fields():
    payload = normalize(NVDA_INCOME)
    assert "inserted_at" not in payload
    assert "updated_at" not in payload
    assert "non_interest_income" not in payload
    assert payload["total_revenue"] == "81615000000"
    assert payload["ticker"] == "NVDA"


def test_clean_balance_sheet_raises_no_violations():
    assert check_violations("balance", normalize(NVDA_BALANCE)) == []


def test_equity_excluding_nci_is_not_a_violation():
    """Assets exceeding liabilities+equity is UW reporting equity parent-only.

    Measured on 20,093 cached balance rows: 2,815 of 2,876 identity failures run
    in this direction and cluster per-filer (121 of 245 tickers fail on nearly
    every row, 124 on none) — DIS, AES, CMI, BXP lead. Flagging it would mark
    half the universe broken while its data is fine.
    """
    with_nci = dict(NVDA_BALANCE, total_shareholder_equity="185474000000")
    assert check_violations("balance", normalize(with_nci)) == []


def test_reversed_identity_is_a_violation():
    """The other direction cannot be explained by NCI — 61 rows, 0.3%."""
    bad = dict(NVDA_BALANCE, total_shareholder_equity="205474000000")
    names = {v.check_name for v in check_violations("balance", normalize(bad))}
    assert names == {"accounting_identity_reversed"}


def test_implausible_share_count_is_flagged():
    """0.1th percentile of real share counts is 15,393 — a unit error, not a
    capital structure. No cached row is <= 0, so the floor is what catches it."""
    bad = dict(NVDA_BALANCE, common_stock_shares_outstanding="15393")
    names = {v.check_name for v in check_violations("balance", normalize(bad))}
    assert names == {"implausible_share_count"}


# CEG's real 2026-06-30 income statement as UW serves it: gross_profit echoes
# total_revenue while cost_of_revenue is populated, so the derived gross margin is
# exactly 1.0. 580 rows across 46 tickers carry this shape.
CEG_INCOME_BAD = {
    "ticker": "CEG",
    "fiscal_date_ending": "2026-06-30",
    "report_type": "quarterly",
    "total_revenue": "7506000000",
    "cost_of_revenue": "6276000000",
    "gross_profit": "7506000000",
}

# CEG's prior quarter, internally consistent: 11,122 - 6,352 = 4,770.
CEG_INCOME_GOOD = {
    "ticker": "CEG",
    "fiscal_date_ending": "2026-03-31",
    "report_type": "quarterly",
    "total_revenue": "11122000000",
    "cost_of_revenue": "6352000000",
    "gross_profit": "4770000000",
}


def test_gross_profit_echoing_revenue_is_flagged():
    """A card rendering '100.0% gross margin' for a utility states something false
    about a real company. The value is kept as computed and the violation is what
    lets the display layer suppress it."""
    names = {
        v.check_name for v in check_violations("income", normalize(CEG_INCOME_BAD))
    }
    assert names == {"gross_profit_equals_revenue_despite_costs"}


def test_consistent_gross_profit_is_not_flagged():
    assert check_violations("income", normalize(CEG_INCOME_GOOD)) == []


def test_zero_cost_of_revenue_is_not_flagged():
    """A genuine no-COGS filer reports gross_profit == revenue with cost 0. That
    is a definition, not an inconsistency, and must not be flagged."""
    row = dict(CEG_INCOME_BAD, cost_of_revenue="0")
    assert check_violations("income", normalize(row)) == []


def test_zero_revenue_is_not_flagged():
    """gross_profit == revenue == 0 is degenerate, not evidence of corruption."""
    row = dict(CEG_INCOME_BAD, total_revenue="0", gross_profit="0")
    assert check_violations("income", normalize(row)) == []


def test_missing_cost_of_revenue_is_not_flagged():
    row = {k: v for k, v in CEG_INCOME_BAD.items() if k != "cost_of_revenue"}
    assert check_violations("income", normalize(row)) == []


def test_balance_checks_do_not_run_on_other_statements():
    """The income statement has no `total_liabilities`; running balance checks
    against it would produce violations on a shape that cannot have them."""
    assert check_violations("income", normalize(NVDA_BALANCE)) == []
    assert check_violations("cash_flow", normalize(NVDA_BALANCE)) == []


# --- Cross-statement NI reconciliation (Task 10) --------------------------
#
# FIXTURE PROVENANCE. All figures below are genuine UW-served values pulled
# live from the dev warm store `postgresql://argon_app@127.0.0.1/option_wizard_local`
# on 2026-08-28. The task brief asked for a pull "from prod via the documented
# route"; the mini (100.66.147.98) answers ICMP/TCP:5432 from this session but
# has no SSH key or DB password configured here, so `option_wizard` on the mini
# was unreachable this session -- this is a recorded DEVIATION, not a silent
# substitution. `option_wizard_local` is populated by the same UW ingest
# pipeline against the real UW API (not synthetic fixtures), so these are real
# vendor figures, just captured on the dev mirror rather than the mini.
#
# NVDA_INCOME above (2026-04-30 quarterly, net_income "58321000000",
# obs_id=1, first_observed_at 2026-08-12) already carries the agreeing half:
#
#     SELECT obs_id, raw_jsonb->>'net_income' FROM fundamental_statement_obs
#      WHERE ticker='NVDA' AND period_end='2026-04-30' AND statement='cash_flow'
#      ORDER BY obs_id DESC LIMIT 1;
#     -> obs_id=165, net_income='58321000000' -- identical to the income figure.
#
# CVX's real 2023-06-30 quarterly pair disagrees by ~200%:
#
#     SELECT obs_id, raw_jsonb->>'net_income' FROM fundamental_statement_obs
#      WHERE ticker='CVX' AND period_end='2023-06-30' AND statement IN ('income','cash_flow')
#      ORDER BY statement, obs_id DESC;
#     -> income  obs_id=30580 net_income='6010000000'
#        cash_flow obs_id=30746 net_income='-6000000000'
#     first_observed_at for both: 2026-08-12 10:02:37+08.
#
# This is not an isolated fluke: the same query pattern run over the full
# local warm store finds 6,269 of 28,973 historical (ticker, period) pairs
# disagreeing beyond 1% -- a large, real, and previously undetected
# vendor-data contradiction population, of which CVX 2023-06-30 is one
# genuine, frozen example.

NVDA_CASH_FLOW_AGREEING = {"net_income": "58321000000"}

CVX_INCOME_2023Q2 = {"net_income": "6010000000"}
CVX_CASH_FLOW_2023Q2_DISAGREEING = {"net_income": "-6000000000"}


def test_agreeing_real_pair_raises_nothing():
    assert check_cross_statement_violations(NVDA_INCOME, NVDA_CASH_FLOW_AGREEING) == []


def test_real_disagreeing_pair_is_flagged():
    """CVX 2023-06-30: income reports +6.01bn, cash-flow reports -6.00bn --
    a genuine, ~200%-magnitude vendor contradiction, not a rounding gap."""
    violations = check_cross_statement_violations(
        CVX_INCOME_2023Q2, CVX_CASH_FLOW_2023Q2_DISAGREEING
    )
    assert {v.check_name for v in violations} == {
        "net_income_disagrees_across_statements"
    }
    (violation,) = violations
    assert violation.field == "net_income"
    assert violation.observed_value == Decimal("6010000000")
    assert violation.detail == {"cashflow_net_income": "-6000000000"}


def test_exact_one_percent_boundary_does_not_fire():
    """Constructed ARITHMETICALLY from NVDA's real, frozen net_income
    (58321000000): scaling the cash-flow figure to exactly 0.99x makes
    `abs(diff)` exactly equal `0.01 * max(abs(a), abs(b))` (max is the
    income side here since 0.99x is smaller in magnitude) -- the boundary
    itself, which must NOT fire because the check requires strictly greater
    than tolerance, not greater-or-equal.

    This is the same class of bug that shipped once already on this branch
    at this exact boundary shape in `float()` (`0.11 - 0.10 < 0.01` is `True`
    in binary floating point) -- only an EXACT boundary case catches it.
    """
    ni_inc = Decimal("58321000000")
    at_boundary_cf = ni_inc * Decimal("0.99")  # == 57737790000, exact
    assert abs(ni_inc - at_boundary_cf) == Decimal("0.01") * ni_inc  # sanity
    assert (
        check_cross_statement_violations(
            {"net_income": str(ni_inc)}, {"net_income": str(at_boundary_cf)}
        )
        == []
    )


def test_one_cent_past_the_boundary_fires():
    """The minimal possible excursion past the same boundary, in the
    direction that WIDENS the gap (cash-flow figure one cent further from
    income than the exact-boundary case above) -- must fire."""
    ni_inc = Decimal("58321000000")
    just_over_cf = ni_inc * Decimal("0.99") - Decimal("0.01")
    names = {
        v.check_name
        for v in check_cross_statement_violations(
            {"net_income": str(ni_inc)}, {"net_income": str(just_over_cf)}
        )
    }
    assert names == {"net_income_disagrees_across_statements"}


def test_boundary_uses_the_larger_side_when_cashflow_is_bigger():
    """The tolerance basis is `max(abs(income), abs(cashflow))`, not either side
    alone. Every other boundary test above has income as the larger magnitude,
    which cannot distinguish `max(...)` from `abs(income)` alone -- both give
    the same threshold in that shape. This flips it: cash-flow is the LARGER
    real-derived value, so a tolerance basis that silently narrowed to
    `abs(income)` would compute a smaller threshold than the real one and
    incorrectly fire at this exact (correct) boundary."""
    ni_cf = Decimal("58321000000")  # real NVDA net_income, frozen
    ni_inc = ni_cf * Decimal("0.99")  # smaller side, exact boundary vs ni_cf
    assert abs(ni_cf - ni_inc) == Decimal("0.01") * ni_cf  # sanity: ni_cf is max
    assert (
        check_cross_statement_violations(
            {"net_income": str(ni_inc)}, {"net_income": str(ni_cf)}
        )
        == []
    )


def test_missing_net_income_on_either_side_raises_nothing():
    assert check_cross_statement_violations({}, NVDA_CASH_FLOW_AGREEING) == []
    assert check_cross_statement_violations(NVDA_INCOME, {}) == []
    assert check_cross_statement_violations({}, {}) == []
