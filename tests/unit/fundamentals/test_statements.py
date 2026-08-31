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
    NiBasisDifference,
    check_net_income_sign_flip,
    check_violations,
    content_hash,
    net_income_basis_difference,
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


# --- Cross-statement NI checks (Task 10, fix round 1) ----------------------
#
# FIXTURE PROVENANCE. All figures below are genuine UW-served values pulled
# live from the dev warm store `postgresql://argon_app@127.0.0.1/option_wizard_local`
# on 2026-08-28 (this session -- the mini, 100.66.147.98, answers ICMP/TCP:5432
# but has no SSH key or DB password configured here, so `option_wizard` on the
# mini was unreachable; `option_wizard_local` is populated by the same UW
# ingest pipeline against the real UW API, so these are real vendor figures,
# just captured on the dev mirror).
#
# The check shipped in the first round of this task
# (`check_cross_statement_violations`, `net_income_disagrees_across_statements`)
# fired on 6,269 of 28,973 historical (ticker, period) pairs by comparing raw
# net_income with no sign/magnitude distinction. Reviewed and rejected: 3,153
# of those matched the income statement's OWN `net_income_from_continuing_operations`
# line, and the residual population is overwhelmingly noncontrolling interests
# and discontinued operations (ASC 230 opens the cash-flow statement from
# consolidated NI including NCI; the income statement's headline is
# post-NCI/post-discontinued-ops) -- a real, correct accounting difference,
# not a vendor defect. Replaced with two functions:
#
#   `check_net_income_sign_flip` -- fires ONLY on a literal sign inversion at
#   matching magnitude (opposite sign, <=1% magnitude gap). Measured on the
#   full local warm store: 5 of 28,973 pairs (0.017%) -- CVX 2023-03-31,
#   CVX 2023-06-30, GE 2022-09-30, IREN 2022-06-30, UMC 2010-09-30. This is a
#   VIOLATION, persisted via `record_violations`.
#
#   `net_income_basis_difference` -- descriptive only, never persisted, fires
#   when cash-flow NI matches NEITHER income NI line and it is not a sign
#   flip. NOT routed through `record_violations`.
#
# CVX's real 2023-06-30 quarterly pair (a genuine sign-flip defect):
#
#     SELECT obs_id, raw_jsonb->>'net_income' FROM fundamental_statement_obs
#      WHERE ticker='CVX' AND period_end='2023-06-30' AND statement IN ('income','cash_flow')
#      ORDER BY statement, obs_id DESC;
#     -> income  obs_id=30580 net_income='6010000000'
#        cash_flow obs_id=30746 net_income='-6000000000'
#     first_observed_at for both: 2026-08-12 10:02:37+08.
#     Magnitude gap: |6010000000 - 6000000000| = 10000000; tolerance
#     0.01*6010000000 = 60100000 -- well within it, opposite sign -> fires.
#
# GE's real 2022-09-30 quarterly pair (a second, independent sign-flip
# defect -- different ticker, different mechanism: GE's OWN continuing-ops
# line is negative there, so this is not explainable via that line either):
#
#     -> income  net_income='161000000',
#        net_income_from_continuing_operations='-76000000'
#        cash_flow net_income='-160000000'
#
# VZ's real 2010-09-30 quarterly pair -- Verizon's OWN disclosed NCI split
# (Vodafone's 45% of Verizon Wireless), the worked example this check's
# redesign is built around. BOTH figures are correct; this must NEVER be a
# violation, and IS a basis difference:
#
#     -> income  obs_id=62195 net_income='881000000',
#        net_income_from_continuing_operations='0'
#        cash_flow obs_id=62361 net_income='2698000000'
#        (881,000,000 + 1,817,000,000 NCI = 2,698,000,000 -- Verizon's own
#        disclosed split.)
#
# Boeing's real 2017-03-31 quarterly pair -- cash-flow matches the income
# statement's OWN `net_income_from_continuing_operations` line exactly, not
# its headline. This must be neither a violation nor a basis difference:
#
#     -> income  net_income='1579000000',
#        net_income_from_continuing_operations='1451000000'
#        cash_flow net_income='1451000000'

NVDA_CASH_FLOW_AGREEING = {"net_income": "58321000000"}

CVX_INCOME_2023Q2 = {"net_income": "6010000000"}
CVX_CASH_FLOW_2023Q2_SIGN_FLIPPED = {"net_income": "-6000000000"}

GE_INCOME_2022Q3 = {
    "net_income": "161000000",
    "net_income_from_continuing_operations": "-76000000",
}
GE_CASH_FLOW_2022Q3_SIGN_FLIPPED = {"net_income": "-160000000"}

VZ_INCOME_2010Q3 = {
    "net_income": "881000000",
    "net_income_from_continuing_operations": "0",
}
VZ_CASH_FLOW_2010Q3_NCI = {"net_income": "2698000000"}

BA_INCOME_2017Q1 = {
    "net_income": "1579000000",
    "net_income_from_continuing_operations": "1451000000",
}
BA_CASH_FLOW_2017Q1_MATCHES_CONTINUING_OPS = {"net_income": "1451000000"}


def test_agreeing_real_pair_raises_nothing():
    assert check_net_income_sign_flip(NVDA_INCOME, NVDA_CASH_FLOW_AGREEING) == []
    assert net_income_basis_difference(NVDA_INCOME, NVDA_CASH_FLOW_AGREEING) is None


def test_real_sign_flip_defect_is_a_violation():
    """CVX 2023-06-30: income +6.01bn, cash-flow -6.00bn -- matching magnitude
    (0.17% gap), opposite sign. A genuine vendor defect, not an accounting
    difference; this is the ONLY class persisted via `record_violations`."""
    violations = check_net_income_sign_flip(
        CVX_INCOME_2023Q2, CVX_CASH_FLOW_2023Q2_SIGN_FLIPPED
    )
    assert {v.check_name for v in violations} == {
        "net_income_sign_flipped_across_statements"
    }
    (violation,) = violations
    assert violation.field == "net_income"
    assert violation.observed_value == Decimal("6010000000")
    assert violation.detail == {"cashflow_net_income": "-6000000000"}
    # A genuine defect is never also reported as a descriptive basis gap.
    assert (
        net_income_basis_difference(
            CVX_INCOME_2023Q2, CVX_CASH_FLOW_2023Q2_SIGN_FLIPPED
        )
        is None
    )


def test_second_independent_real_sign_flip_defect():
    """GE 2022-09-30: a second, independently-verified sign-flip defect on a
    different ticker where the income statement's OWN continuing-ops line is
    ALSO negative -- ruling out 'it secretly matches continuing ops' as an
    alternate explanation for this one."""
    names = {
        v.check_name
        for v in check_net_income_sign_flip(
            GE_INCOME_2022Q3, GE_CASH_FLOW_2022Q3_SIGN_FLIPPED
        )
    }
    assert names == {"net_income_sign_flipped_across_statements"}


def test_real_nci_pair_is_never_a_violation_but_is_a_basis_difference():
    """VZ 2010-09-30: Verizon's own disclosed NCI split (881M + 1,817M
    Vodafone NCI = 2,698M). Same sign, large magnitude gap explained by a
    real accounting fact Argon cannot compute (no NCI field stored) --
    must never reach `record_violations`, and must surface descriptively."""
    assert check_net_income_sign_flip(VZ_INCOME_2010Q3, VZ_CASH_FLOW_2010Q3_NCI) == []
    gap = net_income_basis_difference(VZ_INCOME_2010Q3, VZ_CASH_FLOW_2010Q3_NCI)
    assert gap == NiBasisDifference(Decimal("881000000"), Decimal("2698000000"))


def test_real_continuing_ops_match_is_neither_violation_nor_basis_difference():
    """Boeing 2017-03-31: cash-flow matches `net_income_from_continuing_operations`
    (1,451,000,000) exactly, not the headline (1,579,000,000). The narrowed
    check's whole point is to recognize this and stay silent."""
    assert (
        check_net_income_sign_flip(
            BA_INCOME_2017Q1, BA_CASH_FLOW_2017Q1_MATCHES_CONTINUING_OPS
        )
        == []
    )
    assert (
        net_income_basis_difference(
            BA_INCOME_2017Q1, BA_CASH_FLOW_2017Q1_MATCHES_CONTINUING_OPS
        )
        is None
    )


def test_exact_sign_flip_magnitude_boundary_fires():
    """Constructed ARITHMETICALLY from NVDA's real, frozen net_income
    (58321000000): a sign-flipped cash-flow figure at exactly 0.99x the
    income magnitude makes the magnitude gap EXACTLY equal
    `0.01 * max(abs(a), abs(b))` (max is the income side here) -- the
    boundary itself. The check's `> tolerance` bails OUT of firing only when
    STRICTLY past it, so an exact-equality gap still counts as "matching
    magnitude" and fires.

    This is the same class of bug that shipped once already on this branch
    at this exact boundary shape in `float()` (`0.11 - 0.10 < 0.01` is `True`
    in binary floating point) -- only an EXACT boundary case catches it.
    """
    ni_inc = Decimal("58321000000")
    at_boundary_cf_magnitude = ni_inc * Decimal("0.99")  # == 57737790000, exact
    assert abs(ni_inc - at_boundary_cf_magnitude) == Decimal("0.01") * ni_inc  # sanity
    names = {
        v.check_name
        for v in check_net_income_sign_flip(
            {"net_income": str(ni_inc)},
            {"net_income": str(-at_boundary_cf_magnitude)},
        )
    }
    assert names == {"net_income_sign_flipped_across_statements"}


def test_one_cent_past_the_magnitude_boundary_does_not_fire():
    """The minimal possible excursion past the same boundary, in the
    direction that WIDENS the magnitude gap (cash-flow magnitude one cent
    further from income than the exact-boundary case above) -- the pair no
    longer looks like a literal sign inversion, so it must NOT fire as a
    violation (it becomes a candidate for `net_income_basis_difference`
    instead, since the sign is still flipped but the magnitude no longer
    matches)."""
    ni_inc = Decimal("58321000000")
    just_over_cf_magnitude = ni_inc * Decimal("0.99") - Decimal("0.01")
    assert (
        check_net_income_sign_flip(
            {"net_income": str(ni_inc)},
            {"net_income": str(-just_over_cf_magnitude)},
        )
        == []
    )


def test_magnitude_boundary_uses_the_larger_side_when_cashflow_is_bigger():
    """The tolerance basis is `max(abs(income), abs(cashflow))`, not either
    side alone. The boundary tests above have income as the larger
    magnitude, which cannot distinguish `max(...)` from `abs(income)` alone.
    This flips it: cash-flow is the LARGER real-derived magnitude, so a
    tolerance basis that silently narrowed to `abs(income)` would compute a
    smaller threshold than the real one and incorrectly stop firing at this
    exact (correct) boundary."""
    ni_cf_magnitude = Decimal("58321000000")  # real NVDA net_income, frozen
    ni_inc = ni_cf_magnitude * Decimal("0.99")  # smaller side, exact boundary
    assert (
        abs(ni_cf_magnitude - ni_inc) == Decimal("0.01") * ni_cf_magnitude
    )  # sanity: cf is max
    names = {
        v.check_name
        for v in check_net_income_sign_flip(
            {"net_income": str(ni_inc)}, {"net_income": str(-ni_cf_magnitude)}
        )
    }
    assert names == {"net_income_sign_flipped_across_statements"}


def test_same_sign_never_fires_the_sign_flip_check_regardless_of_magnitude():
    """A same-sign pair can never be a sign flip, however large the gap --
    that is exactly the NCI/discontinued-ops shape `net_income_basis_difference`
    exists for instead. VZ's real magnitude gap (206%) is far larger than the
    1% tolerance and still correctly raises nothing here."""
    assert check_net_income_sign_flip(VZ_INCOME_2010Q3, VZ_CASH_FLOW_2010Q3_NCI) == []


def test_missing_net_income_on_either_side_raises_nothing():
    assert check_net_income_sign_flip({}, NVDA_CASH_FLOW_AGREEING) == []
    assert check_net_income_sign_flip(NVDA_INCOME, {}) == []
    assert check_net_income_sign_flip({}, {}) == []
    assert net_income_basis_difference({}, NVDA_CASH_FLOW_AGREEING) is None
    assert net_income_basis_difference(NVDA_INCOME, {}) is None
    assert net_income_basis_difference({}, {}) is None
