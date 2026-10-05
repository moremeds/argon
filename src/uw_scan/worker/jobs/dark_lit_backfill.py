"""Budgeted backfill of dark-pool + lit print history (uw_dark_lit_flow_prints).

Until v0.13.28 the nightly capture fetched one 500-print page per ticker, day and
source, and UW serves the newest prints first, so busy names kept only the
after-hours tail (September 2026: 45.6% of dark and 20.9% of lit ticker-days cut).
The paged capture fixed tonight onward; this job re-pages the past through the
SAME ``capture_dark_lit_for``, so there is still one writer.

What it fetches: every active-watchlist ticker x session from UW's earliest
available date through ``LAST_CUT_DATE``, OLDEST FIRST (UW's window is 730
trading days and rolls forward a day per day, so the oldest days expire first),
skipping a ticker-day that is already finished (``dark_lit_backfill_progress``)
or already complete (both sources under 500 prints, i.e. never cut).

What stops it, checked before every ticker-day (``stop_reason`` on the runs row):
- ``quota``: this UW budget day's cap (UTC day, the account counter's reset;
  Mon-Fri vs Saturday vs Sunday settings) minus this job's own calls in
  ``external_api_requests`` would not cover a worst-case ticker-day (2 sources x
  page cap = 120 calls), so the cap is never exceeded.
- ``research_budget``: the shared governor (research ceiling, total guard) says no.
- ``error_streak``: consecutive capture failures, so a UW outage cannot burn the quota.
- ``exhausted``: nothing left to fetch. ``calendar_unavailable``: apex is down.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta

from uw_scan.api.client import UwClient, UwHTTPError
from uw_scan.config import Settings
from uw_scan.sources.source_errors import SourceUnavailable
from uw_scan.storage.advisory_locks import fixed_key, single_flight
from uw_scan.storage.repository import Repository
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository
from uw_scan.worker.jobs.uw_alpha_capture import (
    _MAX_PRINT_PAGES,
    _PRINT_LIMIT,
    capture_dark_lit_for,
)

logger = logging.getLogger(__name__)

JOB_NAME = "dark_lit_backfill"
DARK_LIT_BACKFILL_LOCK = fixed_key("dark_lit_backfill")

# Last market_date the one-page capture may have cut. v0.13.28 (the paged capture)
# was cut on 2026-10-05; including that day costs at most one re-page of an
# already-complete day, excluding it would lose a cut one. Raise it only if the
# deploy landed after the 2026-10-06 18:55 ET capture.
LAST_CUT_DATE = date(2026, 10, 5)
# Calendar days to look back for the first session. UW's 730-trading-day window
# is ~1,065 calendar days; the first out-of-window answer names the real start.
_LOOKBACK_DAYS = 1100
_WORST_CASE_CALLS = 2 * _MAX_PRINT_PAGES
_ERROR_STREAK = 20
_RECHECK_EVERY = 25  # ticker-days between DB re-reads of spend and governor
_EARLIEST_RE = re.compile(
    r"earliest date currently available to this token is (\d{4}-\d{2}-\d{2})"
)


def budget_day(now_utc: datetime) -> date:
    return now_utc.astimezone(UTC).date()


def day_quota(settings: Settings, now_utc: datetime) -> int:
    """This UW budget day's cap. The day is UTC (the account counter resets at
    00:00 UTC = 20:00 ET), so UTC Saturday is the Friday-evening ET run."""
    wd = budget_day(now_utc).weekday()
    if wd == 5:
        return settings.dark_lit_backfill_saturday_max_calls
    if wd == 6:
        return settings.dark_lit_backfill_sunday_max_calls
    return settings.dark_lit_backfill_weekday_max_calls


def spent_today(conn, schema: str, now_utc: datetime) -> int:
    """This job's UW calls since the start of ``now_utc``'s budget day. Every
    attempt is its own telemetry row (autocommit recorder), so retries count
    too. A run passes its START time: past midnight UTC the count keeps growing
    instead of resetting, which can only stop it early."""
    day_start = datetime.combine(budget_day(now_utc), datetime.min.time(), UTC)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {schema}.external_api_requests "
            "WHERE provider = 'uw' AND job_name = %s AND request_started_at >= %s",
            (JOB_NAME, day_start),
        )
        return int(cur.fetchone()[0])


def pending_ticker_days(
    sessions: Iterable[date],
    tickers: Iterable[str],
    counts: dict[tuple[date, str], tuple[int, int]],
    finished: set[tuple[date, str]],
    floor: date | None,
) -> list[tuple[date, str]]:
    """(date, ticker) still to fetch, oldest date first, then ticker.

    ``counts`` maps a stored ticker-day to its (dark, lit) print counts; a day
    is complete when both are under one page. ``finished`` holds done and
    unavailable ticker-days; ``floor`` is the newest date UW refused as out of
    its window, so it and everything older are skipped.
    """
    tickers = sorted(set(tickers))
    out: list[tuple[date, str]] = []
    for d in sorted(set(sessions)):
        if floor is not None and d <= floor:
            continue
        for t in tickers:
            if (d, t) in finished:
                continue
            dark, lit = counts.get((d, t), (None, None))
            if dark is not None and dark < _PRINT_LIMIT and lit < _PRINT_LIMIT:
                continue
            out.append((d, t))
    return out


def _load_state(conn, schema: str, start: date, end: date, tickers: list[str]):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT market_date, ticker,
                   count(*) FILTER (WHERE source = 'darkpool'),
                   count(*) FILTER (WHERE source = 'lit_flow')
              FROM {schema}.uw_dark_lit_flow_prints
             WHERE market_date BETWEEN %s AND %s AND ticker = ANY(%s)
             GROUP BY 1, 2
            """,
            (start, end, tickers),
        )
        counts = {(r[0], r[1]): (int(r[2]), int(r[3])) for r in cur.fetchall()}
        cur.execute(
            f"SELECT market_date, ticker, status FROM {schema}.dark_lit_backfill_progress"
        )
        rows = cur.fetchall()
    finished = {(r[0], r[1]) for r in rows}
    unavailable = [r[0] for r in rows if r[2] == "unavailable"]
    return counts, finished, (max(unavailable) if unavailable else None)


def _mark(conn, schema: str, ticker: str, d: date, status: str, pages: int, rows: int):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.dark_lit_backfill_progress
                (ticker, market_date, status, pages, rows_written)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ticker, market_date) DO NOTHING
            """,
            (ticker, d, status, pages, rows),
        )
    conn.commit()


def _out_of_window(exc: Exception) -> date | None:
    """UW's historic_data_access_missing 403 -> the earliest date it names (or
    date.min when the message no longer names one); anything else -> None."""
    if not (isinstance(exc, UwHTTPError) and exc.status_code == 403):
        return None
    if "historic_data_access_missing" not in exc.body_excerpt:
        return None
    m = _EARLIEST_RE.search(exc.body_excerpt)
    return date.fromisoformat(m.group(1)) if m else date.min


def dark_lit_backfill(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    sessions_fn: Callable[[date, date], list[date]],
    budget_ok: Callable[[], bool],
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    with single_flight(repo.conn, DARK_LIT_BACKFILL_LOCK) as acquired:
        if not acquired:
            logger.info("%s: lock held; skipping", JOB_NAME)
            return {"stop_reason": "locked"}
        return _run(repo, client, settings, sessions_fn, budget_ok, now_fn)


def _run(repo, client, settings, sessions_fn, budget_ok, now_fn) -> dict:
    conn, schema = repo.conn, settings.db_schema
    started = now_fn()
    quota = day_quota(settings, started)
    spent_at_start = spent = spent_today(conn, schema, started)
    s = {"done": 0, "unavailable": 0, "errors": 0, "remaining": None}
    reason = "exhausted"
    try:
        sessions = sessions_fn(
            started.date() - timedelta(days=_LOOKBACK_DAYS), LAST_CUT_DATE
        )
    except SourceUnavailable as exc:
        logger.warning("%s: session calendar unavailable: %s", JOB_NAME, repr(exc))
        sessions, reason = [], "calendar_unavailable"
    if sessions:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker FROM {schema}.watchlist WHERE removed_at IS NULL"
            )
            tickers = [r[0].upper() for r in cur.fetchall()]
        counts, finished, floor = _load_state(
            conn, schema, min(sessions), LAST_CUT_DATE, tickers
        )
        conn.commit()
        pending = pending_ticker_days(sessions, tickers, counts, finished, floor)
        alpha = UwHistoricalAlphaRepository(conn, schema=schema)
        skip_before: date | None = None
        streak = 0
        reason, i = "exhausted", 0
        for i, (d, t) in enumerate(pending):
            if skip_before is not None and d < skip_before:
                continue
            if i % _RECHECK_EVERY == 0:
                spent = spent_today(conn, schema, started)
                conn.commit()
                if not budget_ok():
                    reason = "research_budget"
                    break
            if spent + _WORST_CASE_CALLS > quota:
                reason = "quota"
                break
            stats: dict[str, int] = {}
            run_id = repo.insert_scan_run(t, notes=JOB_NAME)
            try:
                n = capture_dark_lit_for(client, repo, alpha, run_id, t, d, stats=stats)
                repo.finish_scan_run(run_id, status="ok")
                conn.commit()
                _mark(conn, schema, t, d, "done", stats.get("pages", 0), n)
                s["done"] += 1
                streak = 0
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                repo.finish_scan_run(run_id, status="error")
                conn.commit()
                earliest = _out_of_window(exc)
                if earliest is not None:
                    _mark(
                        conn, schema, t, d, "unavailable", stats.get("pages", 0) + 1, 0
                    )
                    s["unavailable"] += 1
                    # The window is account-wide: every ticker on and before
                    # this date is out of it too.
                    skip_before = max(earliest, d + timedelta(days=1))
                    stats["pages"] = stats.get("pages", 0) + 1
                else:
                    s["errors"] += 1
                    streak += 1
                    logger.warning("%s %s %s failed: %s", JOB_NAME, t, d, repr(exc))
                    if streak >= _ERROR_STREAK:
                        reason = "error_streak"
                        break
            spent += stats.get("pages", 0)
        else:
            i = len(pending)
        s["remaining"] = sum(
            1 for d, _ in pending[i:] if skip_before is None or d >= skip_before
        )
    calls = spent_today(conn, schema, started) - spent_at_start
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.dark_lit_backfill_runs
                (started_at, budget_day, quota, calls, ticker_days_done,
                 unavailable, errors, remaining, stop_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                started,
                budget_day(started),
                quota,
                calls,
                s["done"],
                s["unavailable"],
                s["errors"],
                s["remaining"],
                reason,
            ),
        )
    conn.commit()
    summary = {**s, "calls": calls, "quota": quota, "stop_reason": reason}
    logger.info("%s complete %s", JOB_NAME, summary)
    return summary
