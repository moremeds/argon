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
from uw_scan.sources.earnings_calendar import fetch_calendar_symbols
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
}


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

    symbols: set[str] = set()
    for offset in range(max(0, lookback_days) + 1):
        symbols |= fetch_calendar_symbols(client, today - timedelta(days=offset))

    targets = sorted(symbols & universe)
    if not targets:
        log.info(
            "fundamental_ingest_daily: %d symbols on the calendar, none in tier %r",
            len(symbols),
            tier,
        )
        return dict(_EMPTY, calendar_symbols=len(symbols))

    counters = fundamental_ingest(
        conn=conn, client=client, tier=tier, schema=schema, tickers=targets
    )
    summary = {**counters, "calendar_symbols": len(symbols), "targets": len(targets)}
    log.info("fundamental_ingest_daily %s", summary)
    return summary
