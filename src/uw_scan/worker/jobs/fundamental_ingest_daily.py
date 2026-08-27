"""Pull statements for the names that actually reported, the day they report.

WHY DAILY BEATS THE MONTHLY SWEEP ON BOTH AXES
----------------------------------------------
A statement is retrievable the day the company reports: 100% of reports 2-7 days old had
their period in the panel, 98.5% across 704 report events over 120 days. So the monthly
sweep's up-to-30-day staleness bought nothing — and it cost more, because it asked all
450 names when ~6 of them had news. The calendar asks ~6.

    calendar, 2 slots x ~2 pages          ~6 calls/day
    reporters in universe, ~5.9 x 4       ~24 calls/day
    -----------------------------------------------
    daily total                          ~900 calls/month
    monthly blind sweep, 450 x 4        1,800 calls/month

Measurement: `docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md` F3/F5.

WHY THE MONTHLY SWEEP IS STILL REGISTERED
------------------------------------------
Two reasons, either sufficient. The calendar is the CLASSIFIED calendar and misses names
UW reports as `report_time: "unknown"` (~2% of the statement-bearing universe). And the
sweep is the only thing that re-pulls a period long after first ingest, which is what
delivers a filing date UW publishes after we first stored the row. This job does not
replace it; it makes it a backstop.

WHAT THE LOOKBACK IS AND IS NOT
-------------------------------
It is outage insurance: a day the worker was down gets picked up the next day. It is NOT
waiting for UW to publish — F3 measured that there is nothing to wait for, and all ten
non-landed report events were permanently non-landed for reasons that are not timing. The
default of 3 is a weekend, not a measurement, and it should not be grown to chase a
missing filing date; that is the backstop's job.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.sources.earnings_calendar import fetch_calendar_listings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest

log = logging.getLogger(__name__)

_EMPTY: dict[str, int] = {
    "tickers": 0,
    "inserted": 0,
    "touched": 0,
    "violations": 0,
    "failed": 0,
    "filing_date_tolerance": 0,
    "calendar_symbols": 0,
    "targets": 0,
    "calendar_rows": 0,
    "calendar_unknown_rows": 0,
}


def _persist_unknown_statements(
    calendar_repo: EarningsCalendarRepository, new_filings: list[dict[str, Any]]
) -> int:
    """Land the `statement_obs` fallback rows (spec §5-i) for a landed-this-run
    statement whose `filing_published_at` date has no calendar row for that ticker —
    the ~2% UW reports `report_time: "unknown"`, invisible to both classified slots
    (see `sources/earnings_calendar.py`). A ticker that DID appear on the calendar for
    that exact date is left alone: the calendar row already carries the real session,
    and re-upserting session=NULL there would just be a no-op touch (COALESCE never
    lets NULL clobber a known value) — checked explicitly so the intent stays legible
    rather than relying on that safety net.
    """
    if not new_filings:
        return 0
    tickers = sorted({filing["ticker"].upper() for filing in new_filings})
    earliest = min(filing["filing_published_at"] for filing in new_filings)
    existing = {
        (row["ticker"], row["report_date"])
        for row in calendar_repo.next_prints(on_or_after=earliest, tickers=tickers)
    }
    unknown_rows = [
        {
            "ticker": filing["ticker"],
            "report_date": filing["filing_published_at"],
            "session": None,
            "source": "statement_obs",
        }
        for filing in new_filings
        if (filing["ticker"].upper(), filing["filing_published_at"]) not in existing
    ]
    return calendar_repo.upsert_rows(unknown_rows)


def fundamental_ingest_daily(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    today: date,
    lookback_days: int = 3,
    tier: str = "ranked",
    schema: str = "uw_scan",
) -> dict[str, Any]:
    """Ingest statements for universe names on the last `lookback_days`+1 calendars.

    `today` is injected rather than read from the clock so a replay and a test mean the
    same thing by it.
    """
    repo = FundamentalObsRepository(conn, schema=schema)
    universe = set(repo.list_universe(tier))
    if not universe:
        log.info("fundamental_ingest_daily: tier %r is empty — nothing to do", tier)
        return dict(_EMPTY)

    # `fetch_calendar_listings` replaces the old `fetch_calendar_symbols` call — one
    # fetch per scanned date, same as before, zero added UW spend — and persists the
    # durable calendar (spec §5-i) as a side effect of the fetch it was already paying
    # for. `EarningsCalendarRepository` is only constructed once universe is known
    # non-empty, so an unseeded tier still reads no calendar at all.
    calendar_repo = EarningsCalendarRepository(conn, schema=schema)
    symbols: set[str] = set()
    calendar_rows = 0
    for offset in range(max(0, lookback_days) + 1):
        report_date = today - timedelta(days=offset)
        listings = fetch_calendar_listings(client, report_date)
        symbols |= {listing.symbol for listing in listings}
        calendar_rows += calendar_repo.upsert_rows(
            [
                {
                    "ticker": listing.symbol,
                    "report_date": report_date,
                    "session": listing.session,
                    "source": "uw_calendar",
                }
                for listing in listings
            ]
        )

    targets = sorted(symbols & universe)
    if not targets:
        log.info(
            "fundamental_ingest_daily: %d symbols on the calendar, none in tier %r",
            len(symbols),
            tier,
        )
        return dict(_EMPTY, calendar_symbols=len(symbols), calendar_rows=calendar_rows)

    counters = fundamental_ingest(
        conn=conn, client=client, tier=tier, schema=schema, tickers=targets
    )
    new_filings = counters.pop("new_filings", [])
    calendar_unknown_rows = _persist_unknown_statements(calendar_repo, new_filings)

    summary = {
        **counters,
        "calendar_symbols": len(symbols),
        "targets": len(targets),
        "calendar_rows": calendar_rows,
        "calendar_unknown_rows": calendar_unknown_rows,
    }
    log.info("fundamental_ingest_daily %s", summary)
    return summary
