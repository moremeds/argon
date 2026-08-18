"""Capture UW `rev_breakdown` rows as point-in-time observations (migration 122).

WHY THIS JOB EXISTS AT ALL, GIVEN THE SIGNAL DOES NOT PAY
---------------------------------------------------------
It is not justified by value; it is justified by optionality. Revenue
concentration is measured, descriptive, and explicitly barred from the composite
(plan D2/D3). What makes capture worth ~450 UW calls a month is that the
provider's history may roll: if it does, a quarter not captured tonight is a
quarter no future decision can ever use, and the cost of finding out too late is
unbounded while the cost of capturing is a rounding error against a 120k/day
budget.

WHY MONTHLY AND NOT QUARTERLY
-----------------------------
Filings are quarterly, but they arrive spread across the calendar and the
provider's window — if it rolls — rolls on its own schedule, not ours. A monthly
pass cannot be outrun by either. Quarterly would align our cadence with the thing
we are trying to observe, which is exactly how a rolling window slips past
unnoticed.

WHY THE RAW ROWS AND NOT THE SHARE
----------------------------------
The derivation rules are new and one of them has already been rewritten once
against real data (see `fundamentals/concentration.py`). Storing a derived share
would freeze today's rules into history and make the next correction a re-fetch
we may not be able to make. Rows are facts, shares are opinions.

SELF-GATING
-----------
An unseeded universe tier yields no tickers and the job returns having spent zero
calls, matching the research-capture jobs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    content_hash,
    normalize,
)
from uw_scan.storage.fundamental_concentration import RevenueBreakdownRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository

log = logging.getLogger(__name__)

SOURCE = "uw"

# The statement normalizer, reused verbatim rather than reimplemented: it already
# drops the two envelope fields that made every tier-1 refresh read as a phantom
# restatement, and a second copy of that rule is a second place to get it wrong.
# The version travels onto the row so old hashes stay reproducible.
PAYLOAD_VERSION = FIELD_MAP_VERSION


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        _ = repr(exc)  # CI Guardrail 2: unparseable period → row dropped, never a raise
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: uncoercible figure → row dropped
        return None


def build_rows(ticker: str, raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Storable observations from one ticker's `rev_breakdown` payload.

    A row missing a period or a numeric value is dropped rather than defaulted:
    both columns are NOT NULL because a breakdown row without them describes
    nothing, and inventing a zero would put a fabricated figure in an immutable
    observation table.

    Deduplicated on the table's own identity. A provider that repeats a row
    within one payload is asserting the same fact twice, and letting both through
    would make the insert conflict with itself inside a single batch.
    """
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in raw_rows:
        report_date = _parse_date(raw.get("report_date"))
        value = _decimal(raw.get("value"))
        if report_date is None or value is None:
            continue
        payload = normalize(raw)
        row = {
            "source": SOURCE,
            "ticker": ticker,
            "report_date": report_date,
            "rev_group": str(raw.get("rev_group") or ""),
            "field": raw.get("field"),
            "axis": [str(a) for a in (raw.get("axis") or [])],
            "members": [str(m) for m in (raw.get("members") or [])],
            "value": value,
            "content_hash": content_hash(payload),
            "payload_version": PAYLOAD_VERSION,
            "raw_jsonb": payload,
        }
        seen[(row["report_date"], row["rev_group"], row["content_hash"])] = row
    return list(seen.values())


def fundamental_concentration_capture(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    tier: str = "ranked",
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
) -> dict[str, int]:
    """Capture breakdown rows for a universe tier. Returns counters."""
    names = (
        tickers
        if tickers is not None
        else FundamentalObsRepository(conn, schema=schema).list_universe(tier)
    )
    totals = {
        "tickers": 0,
        "rows": 0,
        "inserted": 0,
        "touched": 0,
        "empty": 0,
        "failed": 0,
    }
    if not names:
        log.info("fundamental_concentration_capture: tier %r is empty", tier)
        return totals

    repo = RevenueBreakdownRepository(conn, schema=schema)
    for ticker in names:
        try:
            resp, _ = client.get(EndpointSlug.FUNDAMENTAL_BREAKDOWN, ticker=ticker)
            if resp.status_code != 200:
                log.warning(
                    "fundamental_concentration_capture: HTTP %s for %s",
                    resp.status_code,
                    ticker,
                )
                totals["failed"] += 1
                continue
            raw_rows = (resp.json().get("data") or {}).get("rev_breakdown") or []
            rows = build_rows(ticker, raw_rows)
            if not rows:
                # Real and common: a filer that publishes no disaggregation has
                # no breakdown to capture. Counted separately from a failure so
                # a provider outage never hides inside "this one has no rows".
                totals["empty"] += 1
                continue
            inserted, touched = repo.record_rows(rows)
            totals["tickers"] += 1
            totals["rows"] += len(rows)
            totals["inserted"] += inserted
            totals["touched"] += touched
        except Exception:
            # One bad ticker must not abort a 450-name run; the loop is the unit
            # of retry, and a partial capture is resumable because the write path
            # is insert-or-touch.
            totals["failed"] += 1
            log.exception("fundamental_concentration_capture: %s failed", ticker)

    log.info("fundamental_concentration_capture: %s", totals)
    return totals
