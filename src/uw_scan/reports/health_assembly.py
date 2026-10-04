"""/api/health assembly (moved from ``api/routers/health.py``, I-36).

The router parses the query params, reads the clock and calls ``build_health``.
The two ``worker`` functions the assembly needs (the cron-fire expectation and
the market-session date) are passed in, so ``reports`` never imports ``worker``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Literal

from uw_scan.config import Settings
from uw_scan.models.health import (
    HealthFreshness,
    HealthFreshnessRow,
    HealthGapHealer,
    HealthResponse,
    JobFailureStreak,
    TradeInsightsAiHealth,
    WsConsumerHealth,
)
from uw_scan.reports.health_blocks import (
    ExpectedFires,
    _job_degraded,
    _parse_record_tables,
    _provider_ai_health,
    _record_window_scans_expected,
    _snapshot_record_health,
    _worker_health_rows,
)
from uw_scan.storage._helpers import provider_day_bounds
from uw_scan.storage.repository import Repository
from uw_scan.version import app_version

HealthSource = Literal["uw", "massive"]

#: ``current_market_date(now_utc, tz) -> date | None``.
MarketDateFn = Callable[[datetime, str], date | None]

# Captured once at import. Version is fixed for a process's lifetime (launchd
# restarts the stack on deploy), so a constant is both correct and avoids
# re-reading the VERSION file on every 5s health poll.
APP_VERSION = app_version()


def _source_label(source: HealthSource) -> str:
    return "Massive.com" if source == "massive" else "UnusualWhales"


def build_health(
    repo: Repository,
    settings: Settings,
    *,
    clock: Callable[[], datetime],
    source: HealthSource,
    record_window_hours: float | None,
    record_min_coverage: float,
    record_tables: str | None,
    expected_fires: ExpectedFires,
    market_date_fn: MarketDateFn,
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
            version=APP_VERSION,
            reason="database unreachable",
        )

    # Freshness block — built once here, after the DB-up check, and passed to
    # EVERY DB-up return below (incl. the degraded "no scans"/"coverage low"
    # paths), so the operator surface never disappears exactly when health is
    # already degraded.
    from uw_scan.reports.data_freshness import _REGISTRY_BY_NAME
    from uw_scan.storage.data_freshness_repository import DataFreshnessRepository

    _fr_rows = DataFreshnessRepository(
        repo.conn, schema=settings.db_schema
    ).latest_snapshot()
    _as_of = None
    with repo.conn.cursor() as _cur:
        _cur.execute(
            f"SELECT MAX(run_date) FROM {settings.db_schema}.data_freshness_snapshots"
        )
        _row = _cur.fetchone()
        _as_of = _row[0] if _row else None
    freshness = HealthFreshness(
        as_of=_as_of,
        frozen=[r["table_name"] for r in _fr_rows if r["frozen"]],
        tables=[HealthFreshnessRow(**r) for r in _fr_rows],
        # A table with no healer_adapter (e.g. wgc_etf_monthly, blocked on a
        # missing credential) has no autoheal circuit to break -- it was
        # never eligible to retry in the first place, regardless of how long
        # it's been frozen. Same when the feature is off (default):
        # nothing ever ran, so nothing tripped. Without both guards this
        # field falsely reports "circuit broken" for tables autoheal never
        # touched, on day one of deploy, even with the feature disabled.
        autoheal_circuit_broken=[
            r["table_name"]
            for r in _fr_rows
            if r["frozen"]
            and settings.data_freshness_autoheal_enabled
            and (_entry := _REGISTRY_BY_NAME.get(r["table_name"]))
            and _entry.healer_adapter
            and r["consecutive_frozen_nights"]
            >= settings.data_freshness_autoheal_circuit_breaker_nights
        ],
    )

    # Gap-healer block — exact strict-coverage status, distinct from freshness.
    from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository

    _gh = DataGapHealerRepository(
        repo.conn, schema=settings.db_schema
    ).gap_healer_health()
    _gh_counts = _gh["counts"]
    gap_healer = HealthGapHealer(
        latest_run_id=_gh["latest_run_id"],
        latest_run_status=_gh["latest_run_status"],
        latest_run_at=_gh["latest_run_at"],
        healed=_gh_counts.get("healed", 0),
        no_data=_gh_counts.get("no_data", 0),
        failed=_gh_counts.get("failed", 0),
        running=_gh_counts.get("running", 0),
        skipped_budget=_gh_counts.get("skipped_budget", 0),
        open_gaps=(
            _gh_counts.get("planned", 0)
            + _gh_counts.get("skipped_budget", 0)
            + _gh_counts.get("failed", 0)
            + _gh_counts.get("running", 0)
        ),
        open_by_dataset=_gh["open_by_dataset"],
        last_verified_at=_gh["last_verified_at"],
    )

    # Job-failure streak block — consecutive-failure counts per job (see
    # storage/ops_health), surfaced alongside gap_healer/freshness so an
    # operator sees a stuck job without tailing logs.
    from uw_scan.storage.ops_health import JobFailuresRepository

    _streaks = JobFailuresRepository(repo.conn).list_streaks(min_streak=1)
    job_failures = [
        JobFailureStreak(
            job_name=s.job_name,
            consecutive=s.consecutive,
            last_error=s.last_error,
            last_failed_at=s.last_failed_at,
        )
        for s in _streaks
    ]

    # Degraded block — jobs whose latest run succeeded with part of its work
    # missing (thin data, a failed unit among interchangeable ones). Read-side
    # only, built from records the jobs already persist; informational only,
    # never flips ok, never alerts.
    job_degraded = _job_degraded(repo)

    # Sidebar fields — always populated when DB is up so the panel renders
    # correctly even before the first full scan has fired.
    now_utc = clock()
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
        "version": APP_VERSION,
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
    in_session = market_date_fn(now_utc, settings.rth_tz) is not None
    ws_state = repo.get_ws_consumer_state()
    if ws_state is None or ws_state.last_tick_at is None:
        ws_consumer = WsConsumerHealth(
            healthy=not in_session,
            active_source=ws_state.active_source if ws_state else None,
            reason="no ticks received yet" if in_session else "market closed",
        )
    else:
        age_s = (now_utc - ws_state.last_tick_at).total_seconds()
        heartbeat_at = ws_state.last_flush_at or ws_state.last_tick_at
        heartbeat_age_s = (now_utc - heartbeat_at).total_seconds()
        stale = heartbeat_age_s >= settings.massive_ws_heartbeat_stale_after_seconds
        ws_consumer = WsConsumerHealth(
            healthy=(not stale) or (not in_session),
            last_tick_at=ws_state.last_tick_at,
            last_tick_age_seconds=age_s,
            last_flush_at=ws_state.last_flush_at,
            ticks_received=ws_state.ticks_received,
            ticks_flushed=ws_state.ticks_flushed,
            connection_started_at=ws_state.connection_started_at,
            last_error=ws_state.last_error,
            active_source=ws_state.active_source,
            reason=(
                "heartbeat stale"
                if stale and in_session
                else ("market closed" if stale else None)
            ),
        )

    # Per-provider AI worker health (Phase B). Pool is healthy if its
    # provider-pinned heartbeat key has beaten within 2 × poll + 60s.
    # codex/claude are retired providers: reported disabled with zero expected
    # workers; queued_depth still surfaces any leftover rows.
    ai_fresh_window = timedelta(
        seconds=2 * settings.trade_insights_ai_poll_seconds + 60
    )
    ai_block = TradeInsightsAiHealth(
        codex=_provider_ai_health(
            repo=repo,
            now_utc=now_utc,
            provider="codex",
            enabled=False,
            expected_count=0,
            fresh_window=ai_fresh_window,
        ),
        claude=_provider_ai_health(
            repo=repo,
            now_utc=now_utc,
            provider="claude",
            enabled=False,
            expected_count=0,
            fresh_window=ai_fresh_window,
        ),
        deepseek=_provider_ai_health(
            repo=repo,
            now_utc=now_utc,
            provider="deepseek",
            enabled=settings.trade_insights_ai_deepseek_enabled,
            expected_count=settings.trade_insights_ai_deepseek_worker_count,
            fresh_window=ai_fresh_window,
        ),
    )

    heartbeat_fields = {
        "worker_lag_seconds": scheduler_heartbeat_lag,
        "scheduler_heartbeat_lag_seconds": scheduler_heartbeat_lag,
        "scheduler_heartbeat_name": scheduler_heartbeat_name,
        "rescan_heartbeat_lag_seconds": rescan_heartbeat_lag,
        "spot_quote_lag_seconds": spot_quote_lag,
        "latest_spot_quote_at": latest_spot_quote_at,
        "latest_spot_quote_fetched_at": latest_spot_quote_fetched_at,
        "workers": worker_health,
        "ws_consumer": ws_consumer,
        "trade_insights_ai": ai_block,
    }
    record_fields: dict = {"record_health_ok": None, "record_health": []}
    record_reason = None
    record_note = None
    # Market-calendar aware: coverage is only expected when scans were due. If no
    # full-scan cron was scheduled to fire within the record window (weekend,
    # holiday, overnight), an empty window is healthy — not an ALERT. Mirrors the
    # WS-consumer's in-session relaxation, and skips the expensive per-table scan
    # when there is nothing to verify.
    record_scans_expected = _record_window_scans_expected(
        settings,
        now_utc=now_utc,
        record_window_hours=record_window_hours,
        expected_fires=expected_fires,
    )
    if record_window_hours is not None and not record_scans_expected:
        record_fields = {"record_health_ok": True, "record_health": []}
    elif record_window_hours is not None:
        record_fields, record_reason, record_note = _snapshot_record_health(
            repo,
            now_utc=now_utc,
            watchlist_size=watchlist_size,
            selected_tables=_parse_record_tables(record_tables),
            min_coverage=record_min_coverage,
        )

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
            freshness=freshness,
            gap_healer=gap_healer,
            job_failures=job_failures,
            job_degraded=job_degraded,
        )

    lag = (now_utc - last_scan).total_seconds()
    next_stale_at = last_scan + timedelta(
        hours=settings.health_full_scan_missed_grace_hours
    )
    missed_full_scans = expected_fires(
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
            freshness=freshness,
            gap_healer=gap_healer,
            job_failures=job_failures,
            job_degraded=job_degraded,
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
            freshness=freshness,
            gap_healer=gap_healer,
            job_failures=job_failures,
            job_degraded=job_degraded,
        )

    return HealthResponse(
        ok=True,
        db=db_status,
        scheduler_lag_seconds=lag,
        last_full_scan_at=last_scan,
        reason=record_note,
        watchlist_size=watchlist_size,
        **provider_fields,
        **heartbeat_fields,
        **record_fields,
        freshness=freshness,
        gap_healer=gap_healer,
        job_failures=job_failures,
        job_degraded=job_degraded,
    )
