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

CROSS-STATEMENT NI SIGN-FLIP CHECK
------------------------------------
This job does not call `check_net_income_sign_flip` itself — it delegates
its `targets` straight into `fundamental_ingest`, which runs the check
against every complete (income, cash-flow) pair it re-fetches for those
tickers, so this job inherits it without a separate call site. What this job
does NOT guarantee is revisiting a ticker whose cash-flow statement lands
after its income statement and after the ticker drops off the classified
calendar — see `fundamental_ingest`'s own docstring for why the monthly full
sweep, not this job, is what closes that gap.
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

#: How far a filing-publication date can drift from the real report date and
#: still be recognized as "the same print" by the statement_obs fallback's
#: already-known guard. MEASURED, not guessed (branch-fix-p2, C1): a live
#: sample of 26 tickers with both a real report_date (UW `get_earnings_
#: history`) and a `filing_published_at` (this repo's `fundamental_
#: statement_obs`, period_end 2026-06-30) found the gap is one-directional
#: (filing always on-or-after the report) and distributed 15/26 at 0 days,
#: 6/26 at 1 day, 2/26 at 3 days (GILD, MRK), 1/26 at 5 days (ISRG, the C1
#: repro case), 1/26 at 8 days (AVB), 1/26 at 9 days (BXP, the observed max).
#: 10 days covers every sample with margin and stays far short of the ~91-day
#: gap between a ticker's own consecutive quarters (see the filing-date-
#: recovery VERDICT's tolerance study), so a window this wide cannot
#: misidentify a DIFFERENT quarter's print as the one just filed.
FILING_TO_PRINT_WINDOW_DAYS = 10

_EMPTY: dict[str, int] = {
    "tickers": 0,
    "inserted": 0,
    "touched": 0,
    "violations": 0,
    "failed": 0,
    "filing_date_tolerance": 0,
    "calendar_symbols": 0,
    "targets": 0,
    # NEW rows only (xmax=0), not rows seen — see the field-level comments below
    # where these are actually assigned.
    "calendar_rows_new": 0,
    "calendar_unknown_rows_new": 0,
}


def persist_unknown_statements(
    calendar_repo: EarningsCalendarRepository, new_filings: list[dict[str, Any]]
) -> int:
    """Land the `statement_obs` fallback rows (spec §5-i) for a landed-this-run
    statement whose `filing_published_at` date has no calendar row for that ticker —
    the ~2% UW reports `report_time: "unknown"`, invisible to both classified slots
    (see `sources/earnings_calendar.py`).

    `filing_published_at` is a FILING date, not a print date (branch-fix-p2, C1)
    — the two coincide for some names and land up to `FILING_TO_PRINT_WINDOW_DAYS`
    apart for others (measured; see that constant's docstring), so "already known"
    can never be an exact-date match against the classified calendar's `report_date`:
    that compares the new row's date against a set keyed on a DIFFERENT clock and
    almost never matches for a name whose 10-Q lands days after its actual report.
    A classified ticker is instead recognized as known when ANY existing calendar
    row for it falls within the measured window of the filing date — covering the
    real report date whichever side of the filing it lands on, without reaching
    into a neighboring quarter (quarters sit ~91 days apart; see the window
    constant). A ticker that IS newly-known this way is left alone entirely: the
    calendar row already carries the real session, and re-upserting session=NULL
    there would just be a no-op touch (COALESCE never lets NULL clobber a known
    value) — checked explicitly so the intent stays legible rather than relying on
    that safety net.

    Public (not `fundamental_ingest_daily`-private) because the daily job's own
    `targets` can only ever be tickers the classified calendar just listed — a
    ticker UW never lists in either slot can never reach `fundamental_ingest`
    through THIS job, so it can never appear in `new_filings` here. The monthly
    backstop sweep (`scheduler.py`'s `_fundamental_ingest`, which ingests the whole
    tier unfiltered by calendar) is the only caller that can actually hand this a
    calendar-invisible ticker, and calls this same function after its own
    `fundamental_ingest(...)`.
    """
    if not new_filings:
        return 0
    filing_dates = [filing["filing_published_at"] for filing in new_filings]
    window_start = min(filing_dates) - timedelta(days=FILING_TO_PRINT_WINDOW_DAYS)
    window_end = max(filing_dates) + timedelta(days=FILING_TO_PRINT_WINDOW_DAYS)
    known_dates_by_ticker: dict[str, list[date]] = {}
    for row in calendar_repo.prints_between(window_start, window_end):
        known_dates_by_ticker.setdefault(row["ticker"], []).append(row["report_date"])

    unknown_rows = []
    for filing in new_filings:
        ticker = filing["ticker"].upper()
        filing_date = filing["filing_published_at"]
        known_dates = known_dates_by_ticker.get(ticker, [])
        if any(
            abs((filing_date - known_date).days) <= FILING_TO_PRINT_WINDOW_DAYS
            for known_date in known_dates
        ):
            continue
        unknown_rows.append(
            {
                "ticker": filing["ticker"],
                "report_date": filing_date,
                "session": None,
                "source": "statement_obs",
            }
        )
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
    # Rows genuinely NEW to the calendar this run (xmax=0 per Task 4's upsert_rows) —
    # NOT how many listings were seen. `calendar_symbols` below is the "seen" count;
    # on a normal re-scan day this stays near-zero for names already on the calendar
    # from a prior run, which is expected, not a failure.
    calendar_rows_new = 0
    for offset in range(max(0, lookback_days) + 1):
        report_date = today - timedelta(days=offset)
        listings = fetch_calendar_listings(client, report_date)
        symbols |= {listing.symbol for listing in listings}
        calendar_rows_new += calendar_repo.upsert_rows(
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
        return dict(
            _EMPTY, calendar_symbols=len(symbols), calendar_rows_new=calendar_rows_new
        )

    counters = fundamental_ingest(
        conn=conn, client=client, tier=tier, schema=schema, tickers=targets
    )
    new_filings = counters.pop("new_filings", [])
    # Also a NEW-only count (same xmax=0 semantics) — see persist_unknown_statements.
    calendar_unknown_rows_new = persist_unknown_statements(calendar_repo, new_filings)

    summary = {
        **counters,
        "calendar_symbols": len(symbols),
        "targets": len(targets),
        "calendar_rows_new": calendar_rows_new,
        "calendar_unknown_rows_new": calendar_unknown_rows_new,
    }
    log.info("fundamental_ingest_daily %s", summary)
    return summary
