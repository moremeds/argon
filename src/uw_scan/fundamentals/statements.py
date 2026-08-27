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

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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


def check_cross_statement_violations(
    income: Mapping[str, Any], cashflow: Mapping[str, Any]
) -> list[Violation]:
    """Net income must agree between the income statement and the cash-flow
    statement's own net-income reconciliation line, within 1%.

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

    Attributed to the INCOME observation (`field="net_income"`) because that
    is the claim being contradicted; the cash-flow figure travels in `detail`
    for the reader to compare.
    """
    ni_inc = _dec(income, "net_income")
    ni_cf = _dec(cashflow, "net_income")
    if ni_inc is None or ni_cf is None:
        return []
    tolerance = NI_RECONCILIATION_TOLERANCE * max(abs(ni_inc), abs(ni_cf))
    if abs(ni_inc - ni_cf) > tolerance:
        return [
            Violation(
                "net_income_disagrees_across_statements",
                "net_income",
                ni_inc,
                {"cashflow_net_income": str(ni_cf)},
            )
        ]
    return []


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

    # Cross-statement NI reconciliation: agreeing pair raises nothing.
    income = {"net_income": "58321000000"}
    agreeing_cf = {"net_income": "58321000000"}
    assert check_cross_statement_violations(income, agreeing_cf) == []
    # A real 2x-magnitude disagreement (CVX 2023-06-30 shape) fires.
    disagreeing_cf = {"net_income": "-58000000000"}
    names = {
        v.check_name for v in check_cross_statement_violations(income, disagreeing_cf)
    }
    assert names == {"net_income_disagrees_across_statements"}, names
    print("statements self-check ok")


if __name__ == "__main__":
    _self_check()
