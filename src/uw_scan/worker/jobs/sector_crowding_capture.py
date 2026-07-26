"""Nightly UW in-outflow + AUM capture for the sector-crowding universe.

Same fetcher and same table as the gold ETF flow ingest
(worker/jobs/gold_jobs.py:271-310) -- only the ticker constant differs. One
/api/etfs/{t}/in-outflow call plus one /api/etfs/{t}/info call per ticker,
15 tickers, so ~30 UW calls a night against a 120k/day budget.

ponytail: no kill-switch setting. 30 calls is inside the noise floor and each
ticker is already wrapped in its own try/except, so a UW outage degrades to a
warn-and-continue rather than a stuck job. Add a flag if this ever grows a
per-constituent fan-out.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from uw_scan.reports.sector_crowding import (
    BENCHMARK,
    LOOKBACK_DAYS,
    SECTOR_CROWDING_TICKERS,
)
from uw_scan.sources import uw as uw_sources

logger = logging.getLogger(__name__)

# Nightly re-fetch window. Matches gold_jobs' 45-day default, which exists to
# absorb UW revising recent flow figures. See the sizing note in the loop below
# for why this is not simply LOOKBACK_DAYS.
CAPTURE_TAIL_DAYS = 45


def sector_crowding_capture(*, repo, client, settings) -> int:
    """Fetch and persist in-outflow history + AUM for the sector universe.

    Returns the number of flow rows inserted.
    """
    today = datetime.now(ZoneInfo(settings.rth_tz)).date()
    end = today.isoformat()

    # as_of is part of etf_flows_daily's conflict target
    # (ticker, obs_date, as_of), so a wall-clock stamp would make every re-run
    # a fresh key and ON CONFLICT DO NOTHING would never fire. worker/CLAUDE.md
    # requires a job that runs twice in a minute to produce the same DB state,
    # so stamp the market DATE instead: a same-day re-run (manual kick, crash
    # retry, both shards racing) collides and no-ops. Distinct capture dates
    # still get distinct as_of rows, which is what the column is for.
    captured_at = datetime(today.year, today.month, today.day, tzinfo=UTC)

    run_id = repo.insert_scan_run(
        ticker="SECTOR",
        notes=f"sector_crowding_capture:{end}",
    )

    inserted = 0
    try:
        inserted = _capture_all(repo, client, run_id, today, end, captured_at)
    finally:
        # Without this the row sits at status='running' forever and any
        # scan_runs-based freshness check reads the job as hung. In `finally`
        # because a repo-level failure outside the per-ticker guards must still
        # close the run -- and finish_scan_run self-commits (scan_runs.py:78),
        # so on that path the partial flow inserts land too. Partial beats
        # nothing here: the per-ticker guards already make partial the normal
        # outcome of a UW hiccup.
        repo.finish_scan_run(run_id, status="ok" if inserted else "fail")

    # repo.conn.commit(), not repo.commit() -- Repository exposes the psycopg
    # connection and has no commit of its own, and scheduler._repo closes the
    # connection without committing. finish_scan_run above already committed,
    # so on the happy path this is a no-op; it stays because every other worker
    # job ends this way and the guarantee should not depend on a storage
    # method's private commit behaviour.
    repo.conn.commit()
    logger.info("sector_crowding_capture: inserted %d flow rows", inserted)
    return inserted


def _capture_all(repo, client, run_id, today, end, captured_at) -> int:
    """One in-outflow pull plus one AUM refresh per ticker.

    Split out only so `sector_crowding_capture` can wrap the whole sweep in a
    try/finally without a 90-line try body. Never raises for a single bad
    ticker; returns the number of flow rows inserted.
    """
    inserted = 0
    for ticker in (*SECTOR_CROWDING_TICKERS, BENCHMARK):
        try:
            # Window sizing, not cosmetics. as_of is per capture DATE, so a
            # same-day re-run no-ops -- but each new day still re-inserts the
            # whole window under a new as_of. Measured on the live DB
            # 2026-07-26: GLD holds 621 rows for 73 distinct obs_dates (8.5x)
            # from gold_jobs' 45-day window over 3 tickers. A flat 400-day
            # window over 15 tickers would add ~4,100 rows a night -- about a
            # million rows a year to store ~4,100 facts. Reads are unaffected
            # (fetch_etf_flows_daily is DISTINCT ON (obs_date) ORDER BY as_of
            # DESC); this is purely a storage bound.
            #
            # So: pull a short tail nightly, and widen to the full history only
            # when the tail comes back empty. That is the first run for a
            # ticker, or recovery after an outage longer than the tail. Self
            # healing, so no separate backfill script is needed.
            has_recent = bool(
                repo.fetch_etf_flows_daily(
                    ticker, from_date=today - timedelta(days=CAPTURE_TAIL_DAYS)
                )
            )
            days = CAPTURE_TAIL_DAYS if has_recent else LOOKBACK_DAYS
            start = (today - timedelta(days=days)).isoformat()

            rows = [
                {
                    "ticker": row.ticker,
                    "obs_date": row.date,
                    "share_change": row.change,
                    "premium_change_usd": row.change_prem,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in uw_sources.fetch_etf_in_outflow(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    start_date=start,
                    end_date=end,
                )
            ]
            if not rows:
                logger.warning("sector_crowding_capture: %s returned 0 rows", ticker)
                continue
            inserted += repo.insert_etf_flows_daily_rows(
                rows, as_of=captured_at, source="UW"
            )
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort
            logger.warning(
                "sector_crowding_capture: %s flows skipped (%s)",
                ticker,
                repr(exc)[:200],
            )
            continue

        # Refresh AUM in the same pass; the crowding flow leg divides by it and
        # a stale cache silently skews the ratio.
        try:
            info = uw_sources.fetch_etf_info(client, repo, run_id, ticker)
            if info.aum is not None:
                repo.upsert_etf_aum(ticker, info.aum)
        except Exception as exc:  # noqa: BLE001 - AUM is a nice-to-have here
            logger.warning(
                "sector_crowding_capture: %s aum skipped (%s)",
                ticker,
                repr(exc)[:200],
            )
    return inserted
