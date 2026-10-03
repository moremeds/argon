"""Durable on-demand volatility backfill (I-22).

GET /stock/{t}/volatility/series used to run this as a FastAPI BackgroundTask:
an API restart lost the work and its UW spend ran outside the budget governor.
The GET now only enqueues (``volatility_backfill_status.status = 'queued'``);
this tick, on the uw-0 worker, claims one queued ticker and runs it.

Order per tick: nothing claimable? stop -> research budget exhausted? stop,
rows stay as they are -> claim one -> run it. Claimable = 'queued', or
'running' past STALE_RUNNING_AFTER (its worker died). The reclaim keeps the row
'running' and bumps started_at in the same UPDATE as the claim: the worker never
writes 'queued', so it cannot violate a pre-157 CHECK during a deploy where the
worker container starts before the api container has migrated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.reports.volatility_series import run_volatility_backfill
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

# Measured on option_wizard_local (100 runs, 2026-10-03): p50 19 s, max 808 s
# (~13.5 min, 340 UW calls). A row 'running' for longer than this lost its
# worker (restart / crash) and is reclaimed by the next tick.
STALE_RUNNING_AFTER = timedelta(minutes=60)

_LOCK_KEY_SQL = "('x' || substr(md5('vol_backfill:' || %s), 1, 16))::bit(64)::bigint"


def _next_fridays(n: int, *, today: date | None = None) -> list[date]:
    today = today or date.today()
    days = (4 - today.weekday()) % 7
    first = today + timedelta(days=days)
    return [first + timedelta(days=7 * i) for i in range(n)]


def _try_acquire_backfill_lock(conn: psycopg.Connection, ticker: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_LOCK_KEY_SQL})", (ticker,))
        row = cur.fetchone()
        return bool(row and row[0])


def _release_backfill_lock(conn: psycopg.Connection, ticker: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT pg_advisory_unlock({_LOCK_KEY_SQL})", (ticker,))


def run_claimed_backfill(ticker: str, *, repo: Repository, settings: Settings) -> str:
    """Run the backfill for a ticker already claimed ('running'). Returns the
    final status. On failure commits status='failed' and re-raises so the job
    listener records it."""
    conn = repo.conn
    # Single-flight across processes: a stale requeue can hand the ticker to a
    # second claim while the first worker is still alive. The session advisory
    # lock keeps the second one out; the first one writes the final status.
    if not _try_acquire_backfill_lock(conn, ticker):
        log.info("volatility backfill for %s already in flight", ticker)
        return "running"
    try:
        with ExternalApiRequestRecorder(
            settings.db_dsn(), schema=settings.db_schema
        ) as recorder:
            with UwClient(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                timeout=settings.request_timeout_seconds,
                telemetry_recorder=recorder,
                job_name="volatility_backfill",
            ) as client:
                run_id = repo.latest_run_id(ticker)
                if run_id == 0:
                    run_id = repo.insert_scan_run(ticker, notes="volatility_backfill")
                    conn.commit()
                # Cache all expiries from today through Dec 31 of NEXT calendar
                # year (full forward-vol curve through year-end+1), capped at
                # 40 maturities to bound API + smile volume.
                year_end = date(datetime.now(timezone.utc).year + 1, 12, 31)
                term_rows = repo.fetch_iv_term_rows(run_id, ticker)
                if term_rows:
                    expiries = [
                        r["expiry"].isoformat()
                        for r in sorted(term_rows, key=lambda r: r["expiry"])
                        if r["expiry"] <= year_end
                    ][:40]
                else:
                    expiries = [
                        d.isoformat() for d in _next_fridays(40) if d <= year_end
                    ]
                status = run_volatility_backfill(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    nearest_expiries=expiries,
                )
        repo.upsert_volatility_backfill_status(
            ticker=ticker,
            status=status,
            finished_at=datetime.now(timezone.utc),
        )
        conn.commit()
        return status
    except Exception as exc:
        log.warning("volatility backfill failed for %s: %s", ticker, repr(exc))
        conn.rollback()
        repo.upsert_volatility_backfill_status(
            ticker=ticker,
            status="failed",
            finished_at=datetime.now(timezone.utc),
            error_message=repr(exc),
        )
        conn.commit()
        raise
    finally:
        _release_backfill_lock(conn, ticker)


def volatility_backfill_tick(
    *, repo: Repository, settings: Settings, budget_ok: Callable[[], bool]
) -> str | None:
    """One tick: run at most one queued backfill. Returns the ticker run."""
    if not repo.has_claimable_volatility_backfill(STALE_RUNNING_AFTER):
        return None
    if not budget_ok():
        log.info(
            "volatility_backfill_tick skipped: research UW budget exhausted; "
            "queued backfills wait"
        )
        return None
    ticker = repo.claim_volatility_backfill(STALE_RUNNING_AFTER)
    if ticker is None:
        return None
    run_claimed_backfill(ticker, repo=repo, settings=settings)
    return ticker
