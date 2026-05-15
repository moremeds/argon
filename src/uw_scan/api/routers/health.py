"""/api/health — reports DB up, scheduler lag, last successful full scan."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository, provider_day_bounds

router = APIRouter()

HealthSource = Literal["uw", "massive"]
THROUGHPUT_WINDOW_MINUTES = 15


def _source_label(source: HealthSource) -> str:
    return "Massive.com" if source == "massive" else "UnusualWhales"


class HealthResponse(BaseModel):
    ok: bool
    db: str
    scheduler_lag_seconds: float | None = None
    last_full_scan_at: datetime | None = None
    reason: str | None = None
    # Extra fields surfaced in the sidebar HealthPanel. Decoupled from the
    # ok/reason gating above so a benign "no scans yet" still returns lag /
    # watchlist size for the UI.
    worker_lag_seconds: float | None = None
    scheduler_heartbeat_lag_seconds: float | None = None
    scheduler_heartbeat_name: str | None = None
    rescan_heartbeat_lag_seconds: float | None = None
    spot_refresh_heartbeat_lag_seconds: float | None = None
    spot_quote_lag_seconds: float | None = None
    latest_spot_quote_at: datetime | None = None
    latest_spot_quote_fetched_at: datetime | None = None
    watchlist_size: int | None = None
    source: str = "UnusualWhales"
    latency_p95_ms: int | None = None
    http_2xx: int | None = None
    http_4xx: int | None = None
    http_5xx: int | None = None
    uw_today: int | None = None
    cache_hit_pct: float | None = None
    throughput_window_minutes: int = THROUGHPUT_WINDOW_MINUTES
    requests_per_minute: float | None = None
    http_429: int | None = None
    avg_scan_duration_seconds: float | None = None
    queue_drain_rate_per_minute: float | None = None
    record_health_ok: bool | None = None
    record_health: list["RecordHealthCheck"] = Field(default_factory=list)
    workers: list["WorkerHealth"] = Field(default_factory=list)


class WorkerHealth(BaseModel):
    label: str
    role: Literal["uw", "massive"]
    index: int
    heartbeat_name: str
    lag_seconds: float | None = None
    last_beat_at: datetime | None = None


class RecordHealthCheck(BaseModel):
    table: str
    window_start: datetime
    expected_tickers: int
    expected_min_tickers: int
    actual_tickers: int
    expected_min_rows: int
    actual_rows: int
    latest_at: datetime | None = None
    ok: bool


def _full_scan_interval_seconds(cron_expr: str, tz: str) -> float:
    """Two consecutive fires from an in-RTH anchor measure the typical gap.

    Anchored at Tue 10:00 UTC (≈ 06:00 ET) so the cron walks into RTH and
    yields the in-session interval (the threshold we actually care about);
    after-hours gaps would inflate the threshold and mask outages.
    """
    trig = CronTrigger.from_crontab(cron_expr, timezone=tz)
    anchor = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    a = trig.get_next_fire_time(None, anchor)
    if a is None:
        return 3600.0
    b = trig.get_next_fire_time(a, a)
    return (b - a).total_seconds() if b else 3600.0


def _parse_record_tables(record_tables: str | None) -> list[str] | None:
    if record_tables is None:
        return None
    selected = [item.strip() for item in record_tables.split(",") if item.strip()]
    return selected or None


def _worker_health_rows(
    *,
    repo: Repository,
    now_utc: datetime,
    uw_count: int,
    massive_count: int,
) -> list[WorkerHealth]:
    rows: list[WorkerHealth] = []
    for role, count, label_prefix in (
        ("uw", uw_count, "UW"),
        ("massive", massive_count, "Massive"),
    ):
        for index in range(max(0, count)):
            heartbeat_name = f"worker:{role}:{index}"
            last_beat_at = repo.get_heartbeat(heartbeat_name)
            rows.append(
                WorkerHealth(
                    label=f"{label_prefix} {index + 1}",
                    role=role,
                    index=index,
                    heartbeat_name=heartbeat_name,
                    last_beat_at=last_beat_at,
                    lag_seconds=(
                        (now_utc - last_beat_at).total_seconds()
                        if last_beat_at is not None
                        else None
                    ),
                )
            )
    return rows


@router.get("/health", response_model=HealthResponse)
def health(
    source: Annotated[HealthSource, Query()] = "uw",
    record_window_hours: Annotated[float | None, Query(ge=0.1, le=168)] = None,
    record_min_coverage: Annotated[float, Query(ge=0.0, le=1.0)] = 0.9,
    record_tables: Annotated[str | None, Query()] = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    db_status = "up"
    try:
        with repo.conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as e:  # noqa: BLE001
        return HealthResponse(
            ok=False,
            db=f"down: {repr(e)}",
            reason="database unreachable",
        )

    # Sidebar fields — always populated when DB is up so the panel renders
    # correctly even before the first full scan has fired.
    now_utc = datetime.now(timezone.utc)
    latest_heartbeat = repo.get_latest_heartbeat()
    scheduler_heartbeat_name = latest_heartbeat[0] if latest_heartbeat else None
    scheduler_heartbeat_lag = (
        (now_utc - latest_heartbeat[1]).total_seconds()
        if latest_heartbeat is not None
        else None
    )
    rescan_heartbeat = repo.get_heartbeat("rescan_tick")
    rescan_heartbeat_lag = (
        (now_utc - rescan_heartbeat).total_seconds()
        if rescan_heartbeat is not None
        else None
    )
    spot_refresh_heartbeat = repo.get_heartbeat("spot_refresh")
    spot_refresh_heartbeat_lag = (
        (now_utc - spot_refresh_heartbeat).total_seconds()
        if spot_refresh_heartbeat is not None
        else None
    )
    latest_spot_quote_at = None
    latest_spot_quote_fetched_at = None
    spot_quote_lag = None
    latest_spot_quote_times = repo.get_latest_intraday_quote_times()
    if latest_spot_quote_times is not None:
        latest_spot_quote_at, latest_spot_quote_fetched_at = latest_spot_quote_times
        spot_quote_lag = (now_utc - latest_spot_quote_fetched_at).total_seconds()
    watchlist_size = repo.count_active_watchlist()
    worker_health = _worker_health_rows(
        repo=repo,
        now_utc=now_utc,
        uw_count=settings.uw_worker_count,
        massive_count=settings.massive_worker_count,
    )
    provider_day_start, provider_day_end = provider_day_bounds()
    provider_usage = repo.get_external_api_usage_summary(
        source, provider_day_start, provider_day_end
    )
    throughput = repo.get_throughput_summary(
        source,
        now_utc - timedelta(minutes=THROUGHPUT_WINDOW_MINUTES),
        now_utc,
    )
    provider_fields = {
        "source": _source_label(source),
        "latency_p95_ms": provider_usage.latency_p95_ms,
        "http_2xx": provider_usage.http_2xx,
        "http_4xx": provider_usage.http_4xx,
        "http_5xx": provider_usage.http_5xx,
        "uw_today": provider_usage.uw_latest_daily_count,
        "throughput_window_minutes": THROUGHPUT_WINDOW_MINUTES,
        "requests_per_minute": throughput.requests_per_minute,
        "http_429": throughput.http_429,
        "avg_scan_duration_seconds": throughput.avg_scan_duration_seconds,
        "queue_drain_rate_per_minute": throughput.queue_drain_rate_per_minute,
    }
    heartbeat_fields = {
        "worker_lag_seconds": scheduler_heartbeat_lag,
        "scheduler_heartbeat_lag_seconds": scheduler_heartbeat_lag,
        "scheduler_heartbeat_name": scheduler_heartbeat_name,
        "rescan_heartbeat_lag_seconds": rescan_heartbeat_lag,
        "spot_refresh_heartbeat_lag_seconds": spot_refresh_heartbeat_lag,
        "spot_quote_lag_seconds": spot_quote_lag,
        "latest_spot_quote_at": latest_spot_quote_at,
        "latest_spot_quote_fetched_at": latest_spot_quote_fetched_at,
        "workers": worker_health,
    }
    record_fields = {"record_health_ok": None, "record_health": []}
    record_reason = None
    if record_window_hours is not None:
        try:
            record_rows = repo.list_record_health(
                since=now_utc - timedelta(hours=record_window_hours),
                expected_tickers=watchlist_size,
                min_coverage=record_min_coverage,
                tables=_parse_record_tables(record_tables),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_health = [
            RecordHealthCheck(
                table=row.table,
                window_start=row.window_start,
                expected_tickers=row.expected_tickers,
                expected_min_tickers=row.expected_min_tickers,
                actual_tickers=row.actual_tickers,
                expected_min_rows=row.expected_min_rows,
                actual_rows=row.actual_rows,
                latest_at=row.latest_at,
                ok=row.ok,
            )
            for row in record_rows
        ]
        record_ok = all(check.ok for check in record_health)
        record_fields = {
            "record_health_ok": record_ok,
            "record_health": record_health,
        }
        if not record_ok:
            failing = ", ".join(check.table for check in record_health if not check.ok)
            record_reason = f"record coverage below expected: {failing}"

    last_scan = repo.get_last_full_scan_finished_at()
    if last_scan is None:
        return HealthResponse(
            ok=False,
            db=db_status,
            reason="no successful full scan yet",
            watchlist_size=watchlist_size,
            **provider_fields,
            **heartbeat_fields,
            **record_fields,
        )

    lag = (now_utc - last_scan).total_seconds()
    threshold = 2.0 * _full_scan_interval_seconds(
        settings.full_scan_cron, settings.rth_tz
    )
    if lag > threshold:
        return HealthResponse(
            ok=False,
            db=db_status,
            scheduler_lag_seconds=lag,
            last_full_scan_at=last_scan,
            reason=f"scheduler lag {lag:.0f}s exceeds 2x interval ({threshold:.0f}s)",
            watchlist_size=watchlist_size,
            **provider_fields,
            **heartbeat_fields,
            **record_fields,
        )

    if record_reason is not None:
        return HealthResponse(
            ok=False,
            db=db_status,
            scheduler_lag_seconds=lag,
            last_full_scan_at=last_scan,
            reason=record_reason,
            watchlist_size=watchlist_size,
            **provider_fields,
            **heartbeat_fields,
            **record_fields,
        )

    return HealthResponse(
        ok=True,
        db=db_status,
        scheduler_lag_seconds=lag,
        last_full_scan_at=last_scan,
        watchlist_size=watchlist_size,
        **provider_fields,
        **heartbeat_fields,
        **record_fields,
    )
