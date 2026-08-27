"""Normalization and integrity checks for provider fundamental statements.

Pure compute — no I/O, no DB, no settings. The job here is to turn a provider's
raw statement row into a canonical payload plus a `content_hash` that is stable
across refetches, because that hash IS the observation's identity in
`fundamental_statement_obs` (migration 114). If the hash is unstable, every
refresh inserts a duplicate "restatement" and the immutability contract becomes
noise.

Run `uv run python -m uw_scan.fundamentals.statements` for the self-check.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Bump when the normalization below changes in any way that alters a hash.
# Stored on every row: without it, old hashes become unreproducible and the
# audit trail that `content_hash` exists to provide is gone.
FIELD_MAP_VERSION = "uw_v1"

# Verified against real UW payloads (income / balance / cash-flow, 245 tickers):
# every row carries both, and both change when the provider re-ingests, with no
# change to any reported figure. Hashing them would make each refetch look like
# a restatement.
ENVELOPE_FIELDS = frozenset({"inserted_at", "updated_at"})

# A US-listed company with under a million shares outstanding is a unit error or
# a bad parse, not a real capital structure. Measured on 20,053 cached balance
# rows: 83 fall below this, the 0.1th percentile sits at 15,393 shares, and none
# are <= 0.
MIN_PLAUSIBLE_SHARES = Decimal("1000000")

# Relative tolerance for the balance-sheet identity. Below this, a mismatch is
# rounding in reported figures rather than a disagreement.
IDENTITY_TOLERANCE = Decimal("0.01")

# Relative tolerance for net-income reconciliation between the income
# statement and the cash-flow statement's own net-income line. Same numeric
# value as IDENTITY_TOLERANCE but named separately -- the two checks measure
# unrelated identities that happen to share a threshold; a future change to
# one must not silently move the other.
NI_RECONCILIATION_TOLERANCE = Decimal("0.01")

_NUMERIC = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


@dataclass(frozen=True)
class Violation:
    """One deterministic integrity failure against a single observation.

    A violation never blocks ingest. It records that the provider served a
    figure we do not believe, so a consumer can exclude it explicitly instead of
    a silent drop reporting false coverage.
    """

    check_name: str
    # Named for the DB column it lands in. Shadows `dataclasses.field`, which is
    # why `detail` defaults to None rather than a default_factory.
    field: str | None = None
    observed_value: Decimal | None = None
    detail: dict[str, Any] | None = None


def _canonical(value: Any) -> Any:
    """Coerce provider numerics to one textual form.

    UW returns figures as strings (`"11582000000"`). A provider that later
    returns them as JSON numbers reports the same fact, so both must hash the
    same or a format change upstream would look like a market-wide restatement.
    `f` formatting keeps plain notation, so the stored payload stays readable.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)) or (
        isinstance(value, str) and _NUMERIC.match(value)
    ):
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except InvalidOperation as exc:
            _ = repr(exc)  # CI Guardrail 2: uncoercible cell kept verbatim
            return value
    return value


def normalize(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical payload: envelope noise dropped, nulls dropped, numerics coerced.

    Nulls are dropped rather than preserved so that a provider adding a new
    always-null column does not re-hash the entire history. A field that changes
    from a value TO null still re-hashes, which is correct — that is a real
    change in what was reported.
    """
    return {
        key: _canonical(value)
        for key, value in sorted(raw.items())
        if key not in ENVELOPE_FIELDS and value is not None
    }


def content_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical payload. Identity for a tier-1 observation."""
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dec(payload: Mapping[str, Any], key: str) -> Decimal | None:
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        _ = repr(exc)  # CI Guardrail 2: uncoercible cell → no violation check
        return None


def check_violations(statement: str, payload: Mapping[str, Any]) -> list[Violation]:
    """Deterministic integrity checks against one normalized payload.

    Only checks with a measured basis are here. Two of them fire at 0% on the
    current 245-name cache and are kept anyway, so that their absence stays
    *observed* rather than assumed the day a new source is added.

    Income statements carry one check (`gross_profit_equals_revenue_despite_costs`);
    the rest are balance-sheet checks.

    Deliberately NOT a check: `total_assets > total_liabilities +
    total_shareholder_equity`. That fires on 14.4% of cached balance rows, but
    2,815 of the 2,876 failures are in that one direction and they cluster
    per-filer (121 of 245 tickers fail on ~every row; 124 fail on none) — the
    signature of UW reporting equity parent-only, excluding non-controlling
    interest, not of bad data. DIS, AES, CMI and BXP lead the list, all NCI-heavy
    by construction. Flagging it would mark half the universe broken while it is
    fine. The reverse direction cannot be explained that way, so that IS checked.
    """
    if statement == "income":
        # UW sometimes echoes total_revenue into gross_profit while still
        # reporting a positive cost_of_revenue — CEG 2026-06-30 serves revenue
        # 7,506m, cost 6,276m and gross_profit 7,506m, when the prior quarter is
        # internally consistent (11,122 - 6,352 = 4,770). Measured: 580 rows
        # across 46 tickers, ~2.8% of income rows, concentrated in insurers and
        # utilities (AFL 70, AIG 62).
        #
        # It matters because the derived gross_margin becomes exactly 1.0, and a
        # card rendering "100.0% gross margin" for an insurer is a false statement
        # about a real company, not a rounding artifact.
        revenue = _dec(payload, "total_revenue")
        gross = _dec(payload, "gross_profit")
        cost = _dec(payload, "cost_of_revenue")
        if (
            None not in (revenue, gross, cost)
            and cost > 0
            and revenue
            and gross == revenue
        ):
            return [
                Violation(
                    "gross_profit_equals_revenue_despite_costs",
                    "gross_profit",
                    gross,
                    {
                        "cost_of_revenue": str(cost),
                        "implied_gross_profit": str(revenue - cost),
                        "note": "derived gross_margin is 1.0 and must render as na",
                    },
                )
            ]
        return []

    if statement != "balance":
        return []

    out: list[Violation] = []
    assets = _dec(payload, "total_assets")
    liabilities = _dec(payload, "total_liabilities")
    equity = _dec(payload, "total_shareholder_equity")
    shares = _dec(payload, "common_stock_shares_outstanding")

    if assets is not None and assets < 0:
        out.append(Violation("negative_total_assets", "total_assets", assets))
    if liabilities is not None and liabilities < 0:
        out.append(
            Violation("negative_total_liabilities", "total_liabilities", liabilities)
        )
    if shares is not None and shares < MIN_PLAUSIBLE_SHARES:
        out.append(
            Violation(
                "implausible_share_count",
                "common_stock_shares_outstanding",
                shares,
                {"floor": str(MIN_PLAUSIBLE_SHARES)},
            )
        )
    if None not in (assets, liabilities, equity) and assets:
        gap = (assets - (liabilities + equity)) / abs(assets)
        if gap < -IDENTITY_TOLERANCE:
            out.append(
                Violation(
                    "accounting_identity_reversed",
                    "total_assets",
                    assets,
                    {
                        "relative_gap": str(gap.quantize(Decimal("0.0001"))),
                        "note": "assets below liabilities+equity; NCI cannot explain this direction",
                    },
                )
            )
    return out


def check_net_income_sign_flip(
    income: Mapping[str, Any], cashflow: Mapping[str, Any]
) -> list[Violation]:
    """A genuine cross-statement defect: the cash-flow statement's net_income
    has the OPPOSITE SIGN of the income statement's, but nearly the same
    MAGNITUDE (within 1%). That combination cannot come from noncontrolling
    interests or discontinued operations -- both of those move the cash-flow
    figure's size relative to the income figure, never its sign -- so this is
    a literal vendor sign inversion, not an accounting difference.

    CROSS-OBSERVATION, unlike every other check in this module: it needs BOTH
    statements for the same (ticker, period) in hand at once, whereas
    `check_violations` above evaluates one payload in isolation. That
    distinction matters operationally: `FundamentalObsRepository.recheck_violations`
    re-runs `check_violations` one stored row at a time, so it can NEVER apply
    this check retroactively to a pair whose second statement landed in a
    later ingest run -- there is no single row to hand it. The only path that
    reaches a pair completed after the fact is a full re-ingest of that
    ticker: `fundamental_ingest` always re-fetches a ticker's ENTIRE statement
    history (see its module docstring), so both the calendar-driven daily job
    and the monthly full-tier sweep re-derive every (period, statement) pair
    the provider currently reports each time they touch a ticker, and this
    check is wired at that single call site so both inherit it. A cash-flow
    statement that shows up a quarter late is still invisible until the NEXT
    run that includes the ticker -- the daily job only includes tickers the
    earnings calendar names that day, so the monthly sweep (which touches the
    whole tier unconditionally) is what guarantees every ticker gets
    revisited at least once a month regardless of the calendar.

    The comparison stays in `Decimal` end to end via `_dec` -- this is the
    exact shape (`abs(a - b) > tolerance * max(abs(a), abs(b))`) that broke
    once already in this codebase in `float()`, where `0.11 - 0.10 < 0.01` is
    `True` in binary floating point.

    MEASURED, full local warm store, 28,973 historical (ticker, period)
    pairs with both statements: exactly 5 fire (0.017%) -- CVX 2023-03-31,
    CVX 2023-06-30, GE 2022-09-30, IREN 2022-06-30, UMC 2010-09-30. This
    replaces an earlier, much broader version of this check
    (`net_income_disagrees_across_statements`, since removed) that fired on
    6,269 pairs (21.6%) by comparing the raw figures with no sign/magnitude
    distinction -- 3,153 of those 6,269 matched the income statement's OWN
    `net_income_from_continuing_operations` line, and the rest were
    overwhelmingly noncontrolling-interest structures (VZ 2010-09-30: income
    881M vs cash-flow 2,698M, exactly 881M + 1,817M of Vodafone's NCI in
    Verizon Wireless -- both real, neither a defect). See
    `net_income_basis_difference` below for that population, which is
    descriptive, not a violation.

    Attributed to the INCOME observation (`field="net_income"`) because that
    is the claim being contradicted; the cash-flow figure travels in `detail`
    for the reader to compare.

    NON-RETRACTION CAVEAT: this is a CROSS-OBSERVATION check, so a violation
    persisted via `record_violations` is NOT guaranteed correct forever the
    way a single-observation check's is -- see that method's own docstring
    for the accepted, measured (not assumed) reasoning for why this is left
    as a known limitation rather than built around.
    """
    ni_inc = _dec(income, "net_income")
    ni_cf = _dec(cashflow, "net_income")
    if ni_inc is None or ni_cf is None or ni_inc == 0 or ni_cf == 0:
        return []
    if (ni_inc > 0) == (ni_cf > 0):
        return []  # same sign -- not a sign flip, whatever else it might be
    magnitude_gap = abs(abs(ni_inc) - abs(ni_cf))
    tolerance = NI_RECONCILIATION_TOLERANCE * max(abs(ni_inc), abs(ni_cf))
    if magnitude_gap > tolerance:
        return []
    return [
        Violation(
            "net_income_sign_flipped_across_statements",
            "net_income",
            ni_inc,
            {"cashflow_net_income": str(ni_cf)},
        )
    ]


@dataclass(frozen=True)
class NiBasisDifference:
    """A DESCRIPTIVE (never a violation) gap between the income statement's
    `net_income` and the cash-flow statement's own `net_income` line, where
    the cash-flow figure matches NEITHER the income statement's headline
    `net_income` NOR its `net_income_from_continuing_operations` within 1%,
    and is not a sign flip (see `check_net_income_sign_flip`).

    Deliberately NOT a `Violation` and NEVER routed through
    `record_violations`. The driver, measured across the 6,269 pairs an
    earlier, broader version of this check originally flagged, is
    overwhelmingly noncontrolling interests and discontinued operations: ASC
    230's indirect method opens the cash-flow statement from consolidated net
    income (including NCI), while the income statement's headline
    `net_income` is attributable to the parent, post-discontinued-ops. That
    is a real, correct accounting difference Argon cannot attribute without
    an NCI field it does not store -- not a vendor error. Calling it a
    violation would poison the desk's limits block with the ordinary
    accounting convention of every company with a noncontrolling interest or
    OP-unit structure (342 of 419 tickers measured this way, including every
    REIT with OP units) -- see VZ 2010-09-30 in
    `check_net_income_sign_flip`'s docstring: BOTH figures there are correct.

    Follows this repo's own precedent for a measurement it cannot attribute:
    revenue concentration is "descriptive only, never a composite input"
    (`fundamentals/concentration.py`), and the valuation buy-zone surface
    "LISTS, it must never RANK" (`storage/fundamental_anchors.py`) -- readable
    by ticker, never framed as an integrity failure.
    """

    income_net_income: Decimal
    cashflow_net_income: Decimal


def net_income_basis_difference(
    income: Mapping[str, Any], cashflow: Mapping[str, Any]
) -> NiBasisDifference | None:
    """`None` when the cash-flow statement's `net_income` agrees with either
    of the income statement's two net-income lines, or when the pair is
    instead a `check_net_income_sign_flip` violation (mutually exclusive with
    this function by construction, so a ticker-period never appears in both
    the violations table and this descriptive population).

    Read-time only: nothing here is persisted. A cross-obs verdict depends on
    a second statement that can be corrected or restated later, so unlike
    `check_violations`' checks it must be recomputed from current data on
    every read, not frozen the day it was first observed.
    """
    ni_inc = _dec(income, "net_income")
    ni_cf = _dec(cashflow, "net_income")
    if ni_inc is None or ni_cf is None:
        return None
    if abs(ni_inc - ni_cf) <= NI_RECONCILIATION_TOLERANCE * max(
        abs(ni_inc), abs(ni_cf)
    ):
        return None  # agrees with the headline net_income
    ni_cont = _dec(income, "net_income_from_continuing_operations")
    if ni_cont is not None and abs(
        ni_cont - ni_cf
    ) <= NI_RECONCILIATION_TOLERANCE * max(abs(ni_cont), abs(ni_cf)):
        return None  # agrees with net_income_from_continuing_operations instead
    if check_net_income_sign_flip(income, cashflow):
        return None  # a literal sign inversion is a VIOLATION, not a basis gap
    return NiBasisDifference(ni_inc, ni_cf)


def all_check_names() -> frozenset[str]:
    """Every `check_name` any `Violation`-emitting function in this module can
    produce -- derived by parsing this module's OWN source with `ast`, never
    by running a checker against a fixture.

    This exists because a fixture-triggered enumeration only ever sees the
    checks its fixture happens to make fire. That is exactly the shape of bug
    that shipped once already here: `negative_total_assets` (in
    `check_violations` above) had no entry in `validity.CHECK_EFFECTS` --
    `effect_for("negative_total_assets")` raised in production the moment a
    real balance sheet reported negative assets -- and the completeness test
    that was supposed to catch it never triggered that branch, because its
    one fixture had `assets=50` (positive). A static walk finds the check
    whether or not anything in the test suite ever makes it fire.

    Every check_name in this module is passed as `Violation`'s first
    POSITIONAL argument, and always as a string literal (never built up at
    runtime), so an `ast.Call` walk matching `Violation(<string literal>,
    ...)` finds all of them without importing or executing anything beyond
    parsing this file's text.
    """
    tree = ast.parse(Path(__file__).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Violation"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return frozenset(names)


def _self_check() -> None:
    base = {
        "ticker": "NVDA",
        "fiscal_date_ending": "2026-04-30",
        "report_type": "quarterly",
        "total_revenue": "81615000000",
        "inserted_at": "2026-05-21T06:58:08Z",
        "updated_at": "2026-08-11T03:58:32Z",
        "non_interest_income": None,
    }
    # Envelope timestamps must not reach the hash — this is the whole point.
    moved = dict(
        base, inserted_at="2027-01-01T00:00:00Z", updated_at="2027-01-02T00:00:00Z"
    )
    assert content_hash(normalize(base)) == content_hash(normalize(moved))

    # String and numeric spellings of one figure are one fact.
    assert content_hash(normalize(base)) == content_hash(
        normalize(dict(base, total_revenue=81615000000))
    )
    # A real change in a reported figure must re-hash.
    assert content_hash(normalize(base)) != content_hash(
        normalize(dict(base, total_revenue="81615000001"))
    )
    # Adding an always-null column must not re-hash the history.
    assert content_hash(normalize(base)) == content_hash(
        normalize(dict(base, brand_new=None))
    )
    # Nulls are dropped, envelope fields are dropped.
    payload = normalize(base)
    assert "non_interest_income" not in payload and "inserted_at" not in payload
    assert payload["total_revenue"] == "81615000000"

    # NVDA's real 2026-04-30 balance sheet satisfies the identity and must stay clean.
    clean = {
        "total_assets": "259474000000",
        "total_liabilities": "64000000000",
        "total_shareholder_equity": "195474000000",
        "common_stock_shares_outstanding": "24391000000",
    }
    assert check_violations("balance", clean) == []
    # NCI-shaped gap (assets exceed liabilities+equity) is explicitly NOT a violation.
    nci = dict(clean, total_shareholder_equity="185474000000")
    assert check_violations("balance", nci) == []
    # The reverse direction is.
    reversed_ = dict(clean, total_shareholder_equity="205474000000")
    names = {v.check_name for v in check_violations("balance", reversed_)}
    assert names == {"accounting_identity_reversed"}, names
    # Share-count floor.
    assert {
        v.check_name
        for v in check_violations(
            "balance", dict(clean, common_stock_shares_outstanding="15393")
        )
    } == {"implausible_share_count"}
    # Income statements carry no balance checks.
    assert check_violations("income", clean) == []

    # Cross-statement NI sign-flip: agreeing pair raises nothing.
    income = {"net_income": "58321000000"}
    agreeing_cf = {"net_income": "58321000000"}
    assert check_net_income_sign_flip(income, agreeing_cf) == []
    assert net_income_basis_difference(income, agreeing_cf) is None
    # A real sign-flip defect (CVX 2023-06-30 shape) fires as a violation.
    flipped_cf = {"net_income": "-58000000000"}
    names = {v.check_name for v in check_net_income_sign_flip(income, flipped_cf)}
    assert names == {"net_income_sign_flipped_across_statements"}, names
    assert (
        net_income_basis_difference(income, flipped_cf) is None
    )  # violation, not a gap
    # A same-sign NCI-shaped gap (VZ 2010-09-30 shape) is descriptive, not a violation.
    nci_income = {
        "net_income": "881000000",
        "net_income_from_continuing_operations": "0",
    }
    nci_cf = {"net_income": "2698000000"}
    assert check_net_income_sign_flip(nci_income, nci_cf) == []
    gap = net_income_basis_difference(nci_income, nci_cf)
    assert gap == NiBasisDifference(Decimal("881000000"), Decimal("2698000000")), gap

    # Enumeration finds every check_name, including one no fixture above fires.
    found = all_check_names()
    assert "negative_total_assets" in found, found  # never triggered above
    assert "net_income_sign_flipped_across_statements" in found, found
    print("statements self-check ok")


if __name__ == "__main__":
    _self_check()
