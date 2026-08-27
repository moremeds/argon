"""Tier-1 fundamental statement ingest (migration 114, spec §4.3 rev 5).

WHY THIS IS SAFE TO RUN AGAINST A LOCAL DB
------------------------------------------
Unlike `option_surface_capture`, this job accrues NOTHING that expires. UW serves
the full statement history on every call, so a run against `option_wizard_local`
that is later re-run against the prodlike DB loses no data — the second run
reconstructs everything. That is what makes local-first development legitimate
here and illegitimate for the forward-only surface captures.

WHY FILING DATES ARE STORED NULL RATHER THAN ESTIMATED
------------------------------------------------------
`fundamental-breakdown` supplies real filing dates for most but not all periods.
The obvious fallback — `period_end + 45 days` — is a CONSUMER policy, not a fact,
and it belongs nowhere near an immutable observation: it errs early for late
filers, which manufactures look-ahead. Measured cost of that leak on the
validation panel: composite IC 0.059 with the fallback, 0.039 without. So the
column stores what the provider actually said, NULL where it said nothing, and
each consumer decides its own lag policy and records that it applied one.

WHY THE PERIOD MATCH IS TOLERANT
--------------------------------
The statement endpoints normalise a period to a calendar month-end; `fundamental-
breakdown` reports the true fiscal period end. AAPL's June quarter is `2026-06-30` in
one and `2026-06-27` in the other. An exact lookup therefore misses on every period of
every 52/53-week filer, permanently — measured 2026-08-23 at 129 tickers and 885 periods,
**zero** of which matched at tolerance 0.

`FILING_DATE_MATCH_TOLERANCE_DAYS` is read off the recovery curve, not chosen: 7 days
recovers 592 of those periods (1,785 statement rows), 98.5% of everything reachable at
any tolerance, and no period matched two breakdown rows. Quarters sit ~91 days apart, so
the window cannot reach a neighbour. Full curve:
`docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`.

SELF-GATING
-----------
An unseeded tier yields no tickers and the job returns having spent zero calls.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    check_violations,
    content_hash,
    normalize,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.worker.jobs.fundamental_observation_availability import (
    fundamental_observation_availability,
)

log = logging.getLogger(__name__)

SOURCE = "uw"

# Read off the recovery curve: 3 days takes 452 of the 885 NULL periods, 5 takes 569,
# 7 takes 592, and 14 takes only 601 — so the gap between the two spellings runs past 4
# days (AAPL 3, NVDA 4) for a minority of names, and past 7 for almost none. Well clear
# of the ~91-day spacing that separates quarters. See the module docstring.
FILING_DATE_MATCH_TOLERANCE_DAYS = 7

# Slug -> the `statement` value stored on the observation. Short names because
# they are an argon-side vocabulary, not UW's URL spelling: a second source
# (SEC XBRL) must land in the same column with the same three values.
STATEMENTS: dict[EndpointSlug, str] = {
    EndpointSlug.INCOME_STATEMENTS: "income",
    EndpointSlug.BALANCE_SHEETS: "balance",
    EndpointSlug.CASH_FLOWS: "cash_flow",
}


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        _ = repr(exc)  # CI Guardrail 2: unparseable date → NULL, never a raise
        return None


def _filing_dates(client: UwClient, ticker: str) -> dict[date, date]:
    """Real filing dates keyed by period end. Empty dict on any failure.

    Never raises: a missing breakdown costs point-in-time precision on that
    ticker, which is recorded as NULL, but must not cost the statements too.
    """
    try:
        resp, _ = client.get(EndpointSlug.FUNDAMENTAL_BREAKDOWN, ticker=ticker)
    except Exception:
        log.exception("fundamental_ingest: breakdown failed for %s", ticker)
        return {}
    if resp.status_code != 200:
        log.warning(
            "fundamental_ingest: breakdown HTTP %s for %s", resp.status_code, ticker
        )
        return {}
    general = (resp.json().get("data") or {}).get("general") or []
    out: dict[date, date] = {}
    for row in general:
        period = _parse_date(row.get("report_period_end_date"))
        filed = _parse_date(row.get("filing_date"))
        if period and filed:
            out[period] = filed
    return out


def _resolve_filing_date(filed: dict[date, date], period_end: date) -> date | None:
    """The filing date for `period_end`, tolerating the two endpoints' period spellings.

    Exact first, so a calendar-quarter filer never travels the tolerance path and a
    recorded period always beats an arithmetic neighbour. Ties resolve to the earlier
    breakdown period because `min` compares the tuple's second element — arbitrary, but
    deterministic, which is the property that matters for a reproducible panel.
    """
    exact = filed.get(period_end)
    if exact is not None:
        return exact
    nearest = min(
        ((abs((candidate - period_end).days), candidate) for candidate in filed),
        default=None,
    )
    if nearest is None or nearest[0] > FILING_DATE_MATCH_TOLERANCE_DAYS:
        return None
    return filed[nearest[1]]


def fundamental_ingest(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    tier: str = "ranked",
    period_type: str = "quarterly",
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Ingest every statement period for a universe tier. Returns counters."""
    repo = FundamentalObsRepository(conn, schema=schema)
    names = tickers if tickers is not None else repo.list_universe(tier)
    if not names:
        log.info("fundamental_ingest: tier %r is empty — nothing to do", tier)
        return {
            "tickers": 0,
            "inserted": 0,
            "touched": 0,
            "violations": 0,
            "failed": 0,
            "filing_date_tolerance": 0,
            "availability_claims": 0,
            "new_filings": [],
        }

    totals: dict[str, Any] = {
        "tickers": 0,
        "inserted": 0,
        "touched": 0,
        "violations": 0,
        "failed": 0,
        # How often the two endpoints' period spellings disagreed. Reported rather than
        # assumed: if this ever reads 0 the tolerant path has silently stopped firing.
        "filing_date_tolerance": 0,
        # Capture-bounded claims written for versions this run persisted. A run
        # that inserts rows and claims none has left them invisible to history.
        "availability_claims": 0,
        # {"ticker": ..., "filing_published_at": date} for each ticker that landed at
        # least one genuinely new row this run — consumed by `fundamental_ingest_daily`
        # to feed the `statement_obs` calendar-discovery path (spec §5-i). `record_statements`
        # reports counts, not which rows were new, so this takes the MAX filing_published_at
        # among the ticker's rows THIS run as the new statement's date — a heuristic, but a
        # safe one: a ticker only lands a new row on the day it reports, and that is always
        # its most recent period.
        "new_filings": [],
    }
    for ticker in names:
        try:
            filed = _filing_dates(client, ticker)
            rows: list[dict[str, Any]] = []
            flagged: list[tuple[dict[str, Any], list[Any]]] = []
            for slug, statement in STATEMENTS.items():
                resp, _ = client.get(slug, ticker=ticker)
                if resp.status_code != 200:
                    log.warning(
                        "fundamental_ingest: %s HTTP %s for %s",
                        slug,
                        resp.status_code,
                        ticker,
                    )
                    continue
                for raw in resp.json().get("data") or []:
                    if raw.get("report_type") != period_type:
                        continue
                    period_end = _parse_date(raw.get("fiscal_date_ending"))
                    if period_end is None:
                        continue
                    payload = normalize(raw)
                    resolved = _resolve_filing_date(filed, period_end)
                    if resolved is not None and period_end not in filed:
                        totals["filing_date_tolerance"] += 1
                    row = {
                        "source": SOURCE,
                        "ticker": ticker,
                        "period_end": period_end,
                        "period_type": period_type,
                        "statement": statement,
                        "content_hash": content_hash(payload),
                        "provider_record_id": None,
                        "filing_accession": None,
                        "filing_published_at": resolved,
                        "raw_jsonb": payload,
                        "field_map_version": FIELD_MAP_VERSION,
                    }
                    rows.append(row)
                    violations = check_violations(statement, payload)
                    if violations:
                        flagged.append((row, violations))

            inserted, touched = repo.record_statements(rows)
            if inserted > 0:
                filed_dates = [
                    row["filing_published_at"]
                    for row in rows
                    if row["filing_published_at"] is not None
                ]
                if filed_dates:
                    totals["new_filings"].append(
                        {"ticker": ticker, "filing_published_at": max(filed_dates)}
                    )
            for row, violations in flagged:
                obs_id = repo.obs_id(
                    source=row["source"],
                    ticker=row["ticker"],
                    period_end=row["period_end"],
                    period_type=row["period_type"],
                    statement=row["statement"],
                    content_hash=row["content_hash"],
                )
                if obs_id is not None:
                    totals["violations"] += repo.record_violations(obs_id, violations)

            # Claim availability for what just landed. Scoped to this ticker and
            # set-based, so it costs one statement per class rather than one per
            # row, and ON CONFLICT DO NOTHING makes it heal a previous run that
            # died between the observation and the claim.
            #
            # Inside the try on purpose: the observations are already committed,
            # so a failure here leaves rows that no historical policy can see.
            # Counting the ticker as FAILED is what gets the operator to re-run,
            # and the re-run repairs it without writing another fact row.
            claims = fundamental_observation_availability(
                conn=conn, schema=schema, tickers=[ticker]
            )
            totals["availability_claims"] += claims["capture_inserted"]

            totals["tickers"] += 1
            totals["inserted"] += inserted
            totals["touched"] += touched
            log.info(
                "fundamental_ingest: %-6s %4d rows (+%d new, %d unchanged)",
                ticker,
                len(rows),
                inserted,
                touched,
            )
        except Exception:
            # One bad ticker must not abort a 245-name run; the loop is the unit
            # of retry, and a partial ingest is resumable because the write path
            # is insert-or-touch.
            totals["failed"] += 1
            log.exception("fundamental_ingest: %s failed", ticker)

    log.info("fundamental_ingest: %s", totals)
    return totals
