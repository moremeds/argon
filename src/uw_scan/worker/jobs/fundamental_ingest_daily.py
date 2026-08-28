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

#: How far BACKWARD a filing-publication date can sit from the real report
#: date and still be recognized as "the same print." A filing follows its
#: earnings release — it does not precede it (verified, not assumed: a
#: pooled 57-ticker live sample spanning three independent draws — the
#: original 26, UNH, and a fresh 30 — found the gap non-negative in every
#: case; see FILING_FORWARD_TOLERANCE_DAYS). That means a purely-backward
#: window can be widened with no risk of reaching the WRONG print, because
#: quarterly prints sit ~91.25 days apart (`DAYS_PER_QUARTER`,
#: `fundamentals/underwriting.py`) and a symmetric window is the only shape
#: that has to stay under half that spacing to stay unambiguous. 45 days is
#: half of ~91.25 (so it can never be nearer the PRIOR quarter's print than
#: the current one, even by the old symmetric logic's own math) and clears
#: every observed gap with real headroom: BXP 9d, ISRG 5d, BAC 17d, BLK 22d,
#: UNH 25d (the largest, and a non-exotic large-cap — the tail is not
#: confined to obscure names). Measurement: this fix's own live queries
#: (option_wizard_local.uw_scan.fundamental_statement_obs, period_end
#: 2026-06-30, cross-referenced against UW `get_earnings_history`, 2026-08-28).
FILING_LOOKBACK_DAYS = 45

#: How far FORWARD a filing date is allowed to sit from a real report date —
#: i.e. how much slack a genuinely FUTURE print gets before it stops looking
#: like "the same print" as an already-filed statement. Measured at 0/57 in
#: the pooled sample above: no filing has ever been observed dated before
#: its own report. A couple of days of slack (not zero) absorbs weekend/
#: timezone edge cases in either clock without opening the door back up to
#: matching the wrong quarter — 3 days is under 1% of the ~91.25-day
#: inter-print spacing, so it cannot reach a neighboring quarter's print
#: even stacked with FILING_LOOKBACK_DAYS on the other side of a single
#: filing date.
FILING_FORWARD_TOLERANCE_DAYS = 3

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
    — the two coincide for some names and drift by up to `FILING_LOOKBACK_DAYS`
    for others (measured; see that constant's docstring — filing follows print,
    never the reverse), so "already known" can never be an exact-date match
    against the classified calendar's `report_date`: that compares the new row's
    date against a set keyed on a DIFFERENT clock and almost never matches for a
    name whose 10-Q lands days after its actual report. A classified ticker is
    instead recognized as known when ANY existing calendar row for it falls
    within `FILING_LOOKBACK_DAYS` BEFORE the filing date or
    `FILING_FORWARD_TOLERANCE_DAYS` AFTER it — covering the real report date on
    whichever side of the filing it lands (almost always before; a few days'
    slack absorbs the rest), without reaching into a neighboring quarter
    (quarters sit ~91 days apart; see the window constants). A ticker that IS
    newly-known this way is left alone entirely: the
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
    window_start = min(filing_dates) - timedelta(days=FILING_LOOKBACK_DAYS)
    window_end = max(filing_dates) + timedelta(days=FILING_FORWARD_TOLERANCE_DAYS)
    known_dates_by_ticker: dict[str, list[date]] = {}
    for row in calendar_repo.prints_between(window_start, window_end):
        known_dates_by_ticker.setdefault(row["ticker"], []).append(row["report_date"])

    unknown_rows = []
    for filing in new_filings:
        ticker = filing["ticker"].upper()
        filing_date = filing["filing_published_at"]
        known_dates = known_dates_by_ticker.get(ticker, [])
        # Asymmetric on purpose: a filing lands ON OR AFTER its print (delta >= 0,
        # bounded by FILING_LOOKBACK_DAYS), never meaningfully before it (delta < 0,
        # bounded by the much smaller FILING_FORWARD_TOLERANCE_DAYS) — see both
        # constants' docstrings for the 57-ticker measurement backing this shape.
        if any(
            -FILING_FORWARD_TOLERANCE_DAYS
            <= (filing_date - known_date).days
            <= FILING_LOOKBACK_DAYS
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
