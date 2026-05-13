"""/api/stock/{ticker}/volatility/series — see spec 2026-05-13 §5.1."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.models import VolatilitySeriesResponse
from uw_scan.reports.volatility_series import (
    assemble_volatility_series,
    run_volatility_backfill,
)
from uw_scan.storage.repository import Repository

router = APIRouter()
log = logging.getLogger(__name__)

HISTORY_THRESHOLD_DAYS = 90
STALE_BACKFILL_MINUTES = 5


def _next_fridays(n: int, *, today: date | None = None) -> list[date]:
    today = today or date.today()
    days = (4 - today.weekday()) % 7
    first = today + timedelta(days=days)
    return [first + timedelta(days=7 * i) for i in range(n)]


_LOCK_KEY_SQL = "('x' || substr(md5('vol_backfill:' || %s), 1, 16))::bit(64)::bigint"


def _try_acquire_backfill_lock(conn: psycopg.Connection, ticker: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_LOCK_KEY_SQL})", (ticker,))
        row = cur.fetchone()
        return bool(row and row[0])


def _release_backfill_lock(conn: psycopg.Connection, ticker: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT pg_advisory_unlock({_LOCK_KEY_SQL})", (ticker,))


def _kick_backfill(ticker: str) -> None:
    """Background-task entrypoint. Owns its own repo + client.

    Single-flight enforced by a session-scoped pg_advisory_lock keyed on
    md5('vol_backfill:{ticker}'). Held across the whole backfill, released
    in finally.
    """
    settings = get_settings()
    conn = psycopg.connect(settings.db_dsn())
    try:
        if not _try_acquire_backfill_lock(conn, ticker):
            log.info("volatility backfill for %s already in flight", ticker)
            return
        try:
            repo = Repository(conn, schema=settings.db_schema)
            repo.upsert_volatility_backfill_status(
                ticker=ticker,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            conn.commit()
            with UwClient(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                timeout=settings.request_timeout_seconds,
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
        except Exception as exc:
            log.exception("background backfill failed for %s", ticker)
            try:
                conn.rollback()
                Repository(
                    conn, schema=settings.db_schema
                ).upsert_volatility_backfill_status(
                    ticker=ticker,
                    status="failed",
                    finished_at=datetime.now(timezone.utc),
                    error_message=repr(exc),
                )
                conn.commit()
            except Exception:
                log.exception("could not record failed backfill status for %s", ticker)
    finally:
        try:
            _release_backfill_lock(conn, ticker)
        except Exception:
            log.exception("could not release backfill lock for %s", ticker)
        conn.close()


@router.get(
    "/stock/{ticker}/volatility/series",
    response_model=VolatilitySeriesResponse,
)
def get_volatility_series(
    ticker: str,
    background_tasks: BackgroundTasks,
    repo: Repository = Depends(get_repo),
) -> VolatilitySeriesResponse:
    t = ticker.upper()
    history_fresh = repo.count_realized_vol_history(t, days=HISTORY_THRESHOLD_DAYS)
    persisted = repo.get_volatility_backfill_status(t)

    status = "ready"
    if history_fresh < HISTORY_THRESHOLD_DAYS:
        if persisted and persisted["status"] == "running":
            started = persisted.get("started_at")
            now = datetime.now(timezone.utc)
            if started and (now - started) > timedelta(minutes=STALE_BACKFILL_MINUTES):
                status = "running"
                background_tasks.add_task(_kick_backfill, t)
            else:
                status = "running"
        elif persisted and persisted["status"] == "failed":
            status = "failed"
        else:
            status = "running"
            background_tasks.add_task(_kick_backfill, t)
    return assemble_volatility_series(ticker=t, repo=repo, backfill_status=status)
