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

log = logging.getLogger(__name__)

SOURCE = "uw"

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


def fundamental_ingest(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    tier: str = "ranked",
    period_type: str = "quarterly",
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
) -> dict[str, int]:
    """Ingest every statement period for a universe tier. Returns counters."""
    repo = FundamentalObsRepository(conn, schema=schema)
    names = tickers if tickers is not None else repo.list_universe(tier)
    if not names:
        log.info("fundamental_ingest: tier %r is empty — nothing to do", tier)
        return {"tickers": 0, "inserted": 0, "touched": 0, "violations": 0, "failed": 0}

    totals = {"tickers": 0, "inserted": 0, "touched": 0, "violations": 0, "failed": 0}
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
                    row = {
                        "source": SOURCE,
                        "ticker": ticker,
                        "period_end": period_end,
                        "period_type": period_type,
                        "statement": statement,
                        "content_hash": content_hash(payload),
                        "provider_record_id": None,
                        "filing_accession": None,
                        "filing_published_at": filed.get(period_end),
                        "raw_jsonb": payload,
                        "field_map_version": FIELD_MAP_VERSION,
                    }
                    rows.append(row)
                    violations = check_violations(statement, payload)
                    if violations:
                        flagged.append((row, violations))

            inserted, touched = repo.record_statements(rows)
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
