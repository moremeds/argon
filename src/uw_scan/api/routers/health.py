"""/api/health — reports DB up, scheduler lag, last successful full scan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository, provider_day_bounds
from uw_scan.worker.schedule_expectations import expected_market_cron_fires_between

router = APIRouter()

HealthSource = Literal["uw", "massive"]


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
    throughput_window_minutes: float = 0.0
    requests_per_minute: float | None = None
    http_429: int | None = None
    avg_scan_duration_seconds: float | None = None
    queue_drain_rate_per_minute: float | None = None
    record_health_ok: bool | None = None
    record_health: list["RecordHealthCheck"] = Field(default_factory=list)
    workers: list["WorkerHealth"] = Field(default_factory=list)
    ws_consumer: "WsConsumerHealth | None" = None
    trade_insights_ai: "TradeInsightsAiHealth | None" = None


class TradeInsightsAiProviderHealth(BaseModel):
    """Per-provider AI worker pool status."""

    workers_expected: int
    workers_healthy: int
    queued_depth: int
    last_beat_at: datetime | None = None


class TradeInsightsAiHealth(BaseModel):
    codex: TradeInsightsAiProviderHealth
    claude: TradeInsightsAiProviderHealth


class WsConsumerHealth(BaseModel):
    """Massive.com WS consumer status, surfaced for the HealthPanel.

    ``healthy`` is true when:
      * the market is closed (no ticks are expected), OR
      * ``last_tick_at`` is within ``massive_ws_heartbeat_stale_after_seconds``.

    ``reason`` carries the short label the UI displays under the row.
    """

    healthy: bool
    last_tick_at: datetime | None = None
    last_tick_age_seconds: float | None = None
    last_flush_at: datetime | None = None
    ticks_received: int = 0
    ticks_flushed: int = 0
    connection_started_at: datetime | None = None
    last_error: str | None = None
    reason: str | None = None


class WorkerHealth(BaseModel):
    label: str
    role: Literal["uw", "massive", "ai"]
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


_RECORD_HEALTH_CACHE_TTL_SECONDS = 15.0
_RecordHealthCacheKey = tuple[
    tuple[str, ...] | None,
    float,
    float,
    int,
    float,
]


@dataclass(frozen=True)
class _RecordHealthCacheEntry:
    cached_at: datetime
    record_health_ok: bool
    record_health: tuple[RecordHealthCheck, ...]


_record_health_cache: dict[_RecordHealthCacheKey, _RecordHealthCacheEntry] = {}


def _record_health_cache_get(
    key: _RecordHealthCacheKey,
    *,
    now_utc: datetime,
) -> tuple[bool, list[RecordHealthCheck]] | None:
    entry = _record_health_cache.get(key)
    if entry is None:
        return None
    age = (now_utc - entry.cached_at).total_seconds()
    if age < 0 or age > _RECORD_HEALTH_CACHE_TTL_SECONDS:
        _record_health_cache.pop(key, None)
        return None
    return (
        entry.record_health_ok,
        [check.model_copy() for check in entry.record_health],
    )


def _record_health_cache_set(
    key: _RecordHealthCacheKey,
    *,
    now_utc: datetime,
    record_health_ok: bool,
    record_health: list[RecordHealthCheck],
) -> None:
    _record_health_cache[key] = _RecordHealthCacheEntry(
        cached_at=now_utc,
        record_health_ok=record_health_ok,
        record_health=tuple(check.model_copy() for check in record_health),
    )


def _record_health_cache_clear_for_tests() -> None:
    _record_health_cache.clear()


def _parse_record_tables(record_tables: str | None) -> list[str] | None:
    if record_tables is None:
        return None
    selected = [item.strip() for item in record_tables.split(",") if item.strip()]
    return selected or None


def _provider_ai_health(
    *,
    repo: Repository,
    now_utc: datetime,
    provider: str,
    expected_count: int,
    fresh_window: timedelta,
) -> "TradeInsightsAiProviderHealth":
    """Per-provider Trade Insights AI worker health.

    Looks up the provider-pinned heartbeat key (e.g. trade_insights_ai_tick_codex);
    falls back to the legacy key when the provider-pinned worker hasn't started
    yet. Healthiness is binary per pool — exact worker count isn't tracked yet.
    """
    pinned_key = f"trade_insights_ai_tick_{provider}"
    legacy_key = "trade_insights_ai_tick"
    heartbeats = repo.get_heartbeats([pinned_key, legacy_key])
    beat = heartbeats.get(pinned_key) or heartbeats.get(legacy_key)
    pool_alive = beat is not None and (now_utc - beat) < fresh_window
    depth = repo.count_queued_trade_insight_ai_analyses_by_provider(provider)
    return TradeInsightsAiProviderHealth(
        workers_expected=expected_count,
        workers_healthy=expected_count if pool_alive else 0,
        queued_depth=depth,
        last_beat_at=beat,
    )


def _worker_health_rows(
    *,
    repo: Repository,
    now_utc: datetime,
    uw_count: int,
    massive_count: int,
    ai_count: int,
) -> list[WorkerHealth]:
    expected_workers: list[tuple[str, Literal["uw", "massive"], int, str]] = []
    for role, count, label_prefix in (
        ("uw", uw_count, "UW"),
        ("massive", massive_count, "Massive"),
        ("ai", ai_count, "AI"),
    ):
        for index in range(max(0, count)):
            expected_workers.append(
                (f"{label_prefix} {index + 1}", role, index, f"worker:{role}:{index}")
            )

    heartbeats = repo.get_heartbeats(
        heartbeat_name for _, _, _, heartbeat_name in expected_workers
    )

    rows: list[WorkerHealth] = []
    for label, role, index, heartbeat_name in expected_workers:
        last_beat_at = heartbeats.get(heartbeat_name)
        rows.append(
            WorkerHealth(
                label=label,
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
        ai_count=settings.ai_worker_count,
    )
    provider_day_start, provider_day_end = provider_day_bounds()
    provider_usage = repo.get_external_api_usage_summary(
        source, provider_day_start, provider_day_end
    )
    throughput = repo.get_throughput_summary(
        source,
        provider_day_start,
        now_utc,
    )
    provider_fields = {
        "source": _source_label(source),
        "latency_p95_ms": provider_usage.latency_p95_ms,
        "http_2xx": provider_usage.http_2xx,
        "http_4xx": provider_usage.http_4xx,
        "http_5xx": provider_usage.http_5xx,
        "uw_today": provider_usage.uw_latest_daily_count,
        "throughput_window_minutes": throughput.window_minutes,
        "requests_per_minute": throughput.requests_per_minute,
        "http_429": throughput.http_429,
        "avg_scan_duration_seconds": throughput.avg_scan_duration_seconds,
        "queue_drain_rate_per_minute": throughput.queue_drain_rate_per_minute,
    }
    # R4: WS heartbeat health is market-session aware. Outside RTH (mon-fri
    # 09:30-20:15 ET) no ticks flow, so a static staleness threshold would
    # falsely red-flag every weekend and overnight period.
    from uw_scan.worker.market_session import current_market_date

    in_session = current_market_date(now_utc, settings.rth_tz) is not None
    ws_state = repo.get_ws_consumer_state()
    if ws_state is None or ws_state.last_tick_at is None:
        ws_consumer = WsConsumerHealth(
            healthy=not in_session,
            reason="no ticks received yet" if in_session else "market closed",
        )
    else:
        age_s = (now_utc - ws_state.last_tick_at).total_seconds()
        stale = age_s >= settings.massive_ws_heartbeat_stale_after_seconds
        ws_consumer = WsConsumerHealth(
            healthy=(not stale) or (not in_session),
            last_tick_at=ws_state.last_tick_at,
            last_tick_age_seconds=age_s,
            last_flush_at=ws_state.last_flush_at,
            ticks_received=ws_state.ticks_received,
            ticks_flushed=ws_state.ticks_flushed,
            connection_started_at=ws_state.connection_started_at,
            last_error=ws_state.last_error,
            reason=(
                "heartbeat stale"
                if stale and in_session
                else ("market closed" if stale else None)
            ),
        )

    # Per-provider AI worker health (Phase B). Pool is healthy if its
    # provider-pinned heartbeat key has beaten within 2 × poll + 60s.
    ai_fresh_window = timedelta(
        seconds=2 * settings.trade_insights_ai_poll_seconds + 60
    )
    ai_block = TradeInsightsAiHealth(
        codex=_provider_ai_health(
            repo=repo,
            now_utc=now_utc,
            provider="codex",
            expected_count=settings.trade_insights_ai_codex_worker_count,
            fresh_window=ai_fresh_window,
        ),
        claude=_provider_ai_health(
            repo=repo,
            now_utc=now_utc,
            provider="claude",
            expected_count=settings.trade_insights_ai_claude_worker_count,
            fresh_window=ai_fresh_window,
        ),
    )

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
        "ws_consumer": ws_consumer,
        "trade_insights_ai": ai_block,
    }
    record_fields = {"record_health_ok": None, "record_health": []}
    record_reason = None
    if record_window_hours is not None:
        selected_tables = _parse_record_tables(record_tables)
        cache_key: _RecordHealthCacheKey = (
            tuple(selected_tables) if selected_tables is not None else None,
            record_window_hours,
            record_min_coverage,
            watchlist_size,
            settings.record_health_daily_window_hours,
        )
        cached_record_health = _record_health_cache_get(cache_key, now_utc=now_utc)
        if cached_record_health is None:
            try:
                record_rows = repo.list_record_health(
                    since=now_utc - timedelta(hours=record_window_hours),
                    # Daily tables (nightly vol rollup, daily snapshots) refresh
                    # once per day, so they need a wider window to count as fresh.
                    daily_since=now_utc
                    - timedelta(hours=settings.record_health_daily_window_hours),
                    expected_tickers=watchlist_size,
                    min_coverage=record_min_coverage,
                    tables=selected_tables,
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
            _record_health_cache_set(
                cache_key,
                now_utc=now_utc,
                record_health_ok=record_ok,
                record_health=record_health,
            )
        else:
            record_ok, record_health = cached_record_health
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
    next_stale_at = last_scan + timedelta(hours=settings.full_scan_stale_after_hours)
    missed_full_scans = expected_market_cron_fires_between(
        settings.full_scan_crons,
        settings.rth_tz,
        start_utc=next_stale_at,
        end_utc=now_utc,
    )
    if len(missed_full_scans) >= 2:
        return HealthResponse(
            ok=False,
            db=db_status,
            scheduler_lag_seconds=lag,
            last_full_scan_at=last_scan,
            reason=f"{len(missed_full_scans)} expected full scans missed",
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
