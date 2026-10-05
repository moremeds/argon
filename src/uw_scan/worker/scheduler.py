"""APScheduler driver: registers the three cron jobs + the ad-hoc rescan poll."""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.storage.ops_health import _ops_conn
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import fundamentals_provider as _fundamentals_provider
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import research_budget_ok as _research_budget_ok
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once
from uw_scan.worker.jobs.data_gap_healer import data_gap_healer_job
from uw_scan.worker.jobs.pipeline_benchmark import pipeline_benchmark_snapshot_job
from uw_scan.worker.jobs.record_health_snapshot import record_health_snapshot_job
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh
from uw_scan.worker.jobs.theta_harvester import (
    theta_harvester_markout,
    theta_harvester_scan,
)
from uw_scan.worker.jobs.trade_insight_outcome_backfill import (
    trade_insight_outcome_backfill_once,
)
from uw_scan.worker.jobs.volatility_backfill import volatility_backfill_tick
from uw_scan.worker.schedule.gold import register as register_gold_jobs
from uw_scan.worker.schedule.vrp import register as register_vrp_jobs
from uw_scan.worker.schedule.surface import register as register_surface_jobs
# Re-exported: tests/unit/test_scheduler_option_surface_gate.py imports it from here.
from uw_scan.worker.schedule.surface import (  # noqa: F401
    _should_schedule_option_surface_capture as _should_schedule_option_surface_capture,
)
from uw_scan.worker.schedule.macro import register as register_macro_jobs
from uw_scan.worker.schedule.regime import _should_schedule_regime_live
from uw_scan.worker.schedule.regime import register as register_regime_jobs
from uw_scan.worker.schedule.scan_core import register as register_scan_core_jobs
from uw_scan.worker.schedule.ai import register as register_ai_jobs
from uw_scan.worker.schedule.fundamentals import register as register_fundamentals_jobs
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _owns_global_daily_jobs,
    _pinned,
    _ticker_shard_filter,
    _validate_worker_settings,
    _worker_groups,
)
from uw_scan.worker.schema_gate import wait_for_schema
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Suppress APScheduler's per-execution bookkeeping ("Running job…" / "executed
# successfully") — rescan_tick fires every second per worker (the heartbeat
# every 15 s) and would flood concurrently→Warp, saturating the render loop.
# WARNING still surfaces missed-firing, executor overload, and error events.
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger("uw_scan.worker")


def _should_schedule_pipeline_benchmark(settings: Settings) -> bool:
    return _pinned(settings, "uw")


def _should_schedule_data_gap_healer(settings: Settings) -> bool:
    """Nightly gap healer runs on exactly one process (uw-0 or 'all'), and only
    when enabled. Off by default until manual runs prove it safe."""
    return settings.data_gap_healer_enabled and _pinned(settings, "uw")


def _should_schedule_uw_alpha_capture(settings: Settings) -> bool:
    """Pin the 5 UW historical-alpha nightly captures to uw-0 (or 'all').

    Each wrapper is advisory-locked for single-flight, but pinning avoids
    scheduling them on every uw-worker index — same rationale as the option
    surface capture above. Gated by the master capture flag.
    """
    if not settings.uw_alpha_capture_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_sector_rs_daily(settings: Settings) -> bool:
    """Single owner for the nightly sector RS + breadth upserts. apex bars plus
    a daily_ohlc fallback, no UW/IB spend → pin to massive-0, same as
    earnings_reactions. Gated on `sector_rs_enabled`
    (default off until the backfill lands on the mini)."""
    if not settings.sector_rs_enabled:
        return False
    return _pinned(settings, "massive")


def _should_schedule_mcp_event_retention(settings: Settings) -> bool:
    """Single owner for the nightly mcp_event purge. Pure warm-store
    housekeeping DELETE — no UW/IB spend → pin to massive-0, same as
    sector_rs_daily. No enable flag: pure housekeeping (agent-mcp plan M3)."""
    return _pinned(settings, "massive")


def _worker_label(settings: Settings) -> str:
    role = settings.worker_role.lower()
    if role == "all":
        return "all"
    return f"{role}-{settings.worker_index}-of-{settings.worker_count}"


def _worker_heartbeat_name(settings: Settings) -> str:
    role = settings.worker_role.lower()
    if role == "all":
        return "worker"
    return f"worker:{role}:{settings.worker_index}"


def _record_worker_heartbeat(settings: Settings) -> None:
    with _repo(settings) as repo:
        repo.upsert_heartbeat(_worker_heartbeat_name(settings))


# Interval "tick" jobs that fire every few seconds. Recording every success of
# these upserted job_failures (one fresh connection each) several times a
# second fleet-wide. A success is only recorded when it can change the row: the
# first success of the process (clears a streak left by a previous process) and
# the first success after a failure (resets the streak). Failures always record.
_TICK_JOB_IDS = frozenset(
    {
        "worker_heartbeat",
        "rescan_tick",
        "volatility_backfill_tick",
        "trade_insights_ai_tick",
        "trade_insights_ai_tick_deepseek",
    }
)
# Tick jobs whose last recorded state in this process is success.
_tick_jobs_recorded_clean: set[str] = set()


def _handle_job_event(event) -> None:
    from uw_scan.storage.ops_health import JobFailuresRepository

    failed = getattr(event, "exception", None) is not None
    if event.job_id in _TICK_JOB_IDS:
        if not failed and event.job_id in _tick_jobs_recorded_clean:
            return
        if failed:
            _tick_jobs_recorded_clean.discard(event.job_id)
    try:
        with _ops_conn() as conn:
            repo = JobFailuresRepository(conn)
            if failed:
                repo.record_failure(event.job_id, str(event.exception))
                streak = next(
                    (s for s in repo.list_streaks() if s.job_name == event.job_id), None
                )
                if streak and streak.consecutive in (3, 10):
                    from uw_scan.alerts import send_alert

                    send_alert(
                        f"job {event.job_id} failing",
                        f"{streak.consecutive} consecutive; last: {streak.last_error[:200]}",
                    )
            else:
                repo.record_success(event.job_id)
            conn.commit()
        if not failed and event.job_id in _TICK_JOB_IDS:
            _tick_jobs_recorded_clean.add(event.job_id)
    except Exception as exc:  # ops telemetry must never crash the scheduler
        logger.warning(
            "job-failure listener could not record event for %s: %s",
            getattr(event, "job_id", "?"),
            repr(exc),
            exc_info=True,
        )


def main() -> int:
    settings = Settings.from_env()
    _validate_worker_settings(settings)
    # Before any job exists: new code must not run against an unmigrated schema
    # (Watchtower can start this image before the api has migrated).
    wait_for_schema(settings.db_dsn())
    groups = _worker_groups(settings)
    ticker_filter = _ticker_shard_filter(settings)
    sched = BlockingScheduler(timezone=settings.rth_tz)
    sched.add_listener(_handle_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)


    def _spy_ohlc_refresh() -> None:
        if settings.massive_api_key is None:
            logger.warning("MASSIVE_API_KEY not set; skipping SPY refresh")
            return
        with _external_api_recorder(settings) as recorder:
            with _repo(settings) as repo:
                daily_spy_ohlc_refresh(
                    repo=repo,
                    api_key=settings.massive_api_key.get_secret_value(),
                    tz=settings.rth_tz,
                    telemetry_recorder=recorder,
                )


    def _spx_density_forecast() -> None:
        from uw_scan.worker.jobs.spx_density_forecast import spx_density_forecast_job

        with _repo(settings) as repo:
            summary = spx_density_forecast_job(repo, settings)
        logger.info("spx_density_forecast_tick %s", summary)


    def _theta_harvester_scan() -> None:
        with _repo(settings) as repo:
            theta_harvester_scan(repo=repo, settings=settings)

    def _theta_harvester_markout() -> None:
        with _repo(settings) as repo:
            theta_harvester_markout(repo=repo, settings=settings)

    def _sector_rs_daily() -> None:
        from datetime import datetime as _dt
        from functools import partial
        from zoneinfo import ZoneInfo

        from uw_scan.sources.apex import fetch_bulk_daily_closes
        from uw_scan.worker.jobs.sector_rs_daily import sector_rs_daily

        as_of = _dt.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            counters = sector_rs_daily(
                repo=repo,
                schema=settings.db_schema,
                as_of=as_of,
                fetch_closes=partial(
                    fetch_bulk_daily_closes, base_url=settings.apex_api_url
                ),
            )
        logger.info("sector_rs_daily %s", counters)

    def _mcp_event_retention() -> None:
        from uw_scan.storage.mcp_events import purge_old_events

        with _repo(settings) as repo:
            deleted = purge_old_events(repo.conn, days=30)
            repo.conn.commit()
        logger.info("mcp_event_retention deleted=%d", deleted)

    def _technical_daily_refresh() -> None:
        with _repo(settings) as repo:
            technical_daily_refresh(repo=repo, settings=settings)

    def _corporate_actions_refresh() -> None:
        provider = _fundamentals_provider(settings)
        if provider is None:
            logger.warning(
                "MASSIVE_API_KEY not set; skipping corporate-actions refresh"
            )
            return
        try:
            with _repo(settings) as repo:
                n = corporate_actions_refresh_once(repo, provider)
                logger.info("corporate_actions_refresh ingested %d tickers", n)
        finally:
            provider.close()

    def _volatility_backfill_tick() -> None:
        # Durable queue for the GET /volatility/series backfill (I-22): research
        # UW pool, so an exhausted budget leaves rows 'queued' for a later tick.
        with _repo(settings) as repo:
            volatility_backfill_tick(
                repo=repo,
                settings=settings,
                budget_ok=lambda: _research_budget_ok(settings, repo),
            )


    def _greek_exposure_daily_refresh() -> None:
        # Single-name daily GEX/DEX from UW's aggregate /greek-exposure history
        # (#179) — same authoritative basis the indices use. One UW call per
        # single-name ticker; single-flight via the job's advisory lock.
        from uw_scan.worker.jobs.greek_exposure_daily_refresh import (
            greek_exposure_daily_refresh,
        )

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="greek_exposure_daily_refresh",
            ) as uw:
                with _repo(settings) as repo:
                    greek_exposure_daily_refresh(
                        repo=repo, client=uw, settings=settings
                    )

    def _macro_release_calendar_capture() -> None:
        # Economic-release calendar: one UW call (current+next week) + a FRED
        # fill pass over past unfilled mapped rows. See reports/macro_releases.py.
        from uw_scan.worker.jobs.macro_release_calendar import (
            macro_release_calendar_capture,
        )

        fred_key = (
            settings.fred_api_key.get_secret_value() if settings.fred_api_key else None
        )
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="macro_release_calendar_capture",
            ) as uw:
                with _repo(settings) as repo:
                    summary = macro_release_calendar_capture(
                        repo,
                        uw,
                        fred_key,
                        record_request=lambda _p, e: recorder.record(e),
                    )
        logger.info("macro_release_calendar_capture %s", summary)

    def _make_uw_alpha_capture(wrapper, job_name: str):
        # UW historical-alpha nightly capture (5 datasets). Each wrapper is
        # advisory-locked for single-flight; env freezes at fork, so the flag is
        # read at scheduler build time via _should_schedule_uw_alpha_capture.
        def _job() -> None:
            with _external_api_recorder(settings) as recorder:
                with _uw_client(
                    settings, telemetry_recorder=recorder, job_name=job_name
                ) as uw:
                    with _repo(settings) as repo:
                        wrapper(repo=repo, client=uw, settings=settings)

        return _job

    def _data_freshness_monitor() -> None:
        # Per-table data-date freshness audit (#prevention) — DB-only, zero UW.
        from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor

        with _repo(settings) as repo:
            data_freshness_monitor(
                repo=repo,
                settings=settings,
                today=datetime.now(ZoneInfo(settings.rth_tz)).date(),
            )

    def _cockpit_daily_snapshot() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="cockpit_daily_snapshot",
            ) as uw:
                with _repo(settings) as repo:
                    cockpit_daily_snapshot(repo=repo, client=uw, settings=settings)

    def _data_gap_healer() -> None:
        if not settings.data_gap_healer_enabled:
            return
        today = datetime.now(ZoneInfo(settings.rth_tz)).date()
        data_gap_healer_job(settings=settings, today=today)


    def _trade_insight_outcome_backfill() -> None:
        """Nightly outcome scorer — runs at 17:00 ET (after the daily
        OHLC pull at 17:30 has at least one cron tick ahead of it the
        following business day, so forward closes have a chance to
        accumulate before each scan). Primary worker only — the upsert
        is idempotent but running on every worker wastes Postgres roundtrips.
        """
        with _repo(settings) as repo:
            counts = trade_insight_outcome_backfill_once(repo.conn)
            logger.info(
                "trade_insight_outcome_backfill bootstrapped=%d scored=%d",
                counts["bootstrapped"],
                counts["scored"],
            )


    def _technical_live_scan() -> None:
        # Weekday gate — same rationale as regime_live: a provisional close is
        # only meaningful during the trading week.
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            return
        from uw_scan.worker.jobs.technical_live import technical_live_scan

        with _external_api_recorder(settings) as recorder:
            with _repo(settings) as repo:
                summary = technical_live_scan(
                    repo, settings, telemetry_recorder=recorder
                )
        logger.info("technical_live_scan_tick %s", summary)


    def _pipeline_benchmark_snapshot() -> None:
        pipeline_benchmark_snapshot_job(settings)

    # 15 s, not 1 s: every consumer treats a beat as stale only after minutes
    # (benchmark collector 5 min, AI pools 5 min); the health panel shows lag.
    sched.add_job(
        lambda: _record_worker_heartbeat(settings),
        IntervalTrigger(seconds=15),
        id="worker_heartbeat",
        name="Worker heartbeat",
        max_instances=1,
        coalesce=True,
    )
    if "massive" in groups:
        if _is_primary_worker(settings):
            # Volatility tab v2 jobs — ET-anchored via from_crontab (review I9).
            sched.add_job(
                _spy_ohlc_refresh,
                CronTrigger.from_crontab("30 16 * * 0-4", timezone=settings.rth_tz),
                id="daily_spy_ohlc_refresh",
                name="Daily SPY OHLC refresh",
            )
            # SPX 1-5d density cone at 03:30 ET — AFTER vol_index_lake_sync (03:15)
            # so the anchor is the freshest lake close. Zero UW/IB spend; the job
            # self-gates (skips issue when no new SPX bar landed). tue-sat so
            # Friday's close is issued Saturday morning, not the following Monday.
            if settings.spx_density_enabled:
                sched.add_job(
                    _spx_density_forecast,
                    CronTrigger(
                        hour=3,
                        minute=30,
                        day_of_week="tue-sat",
                        timezone=settings.rth_tz,
                    ),
                    id="spx_density_forecast",
                    name="SPX 1-5d density cone (v13 GJR-GARCH, display-only)",
                    max_instances=1,
                    coalesce=True,
                )
            # Theta Harvester at 19:45 ET — after option_surface_capture (19:00)
            # and its IV canary (19:30) have landed the session's grid. Pure
            # warm-store compute: zero UW budget, so massive-0 is the right home.
            if settings.theta_harvester_enabled:
                sched.add_job(
                    _theta_harvester_scan,
                    CronTrigger.from_crontab("45 19 * * 0-4", timezone=settings.rth_tz),
                    id="theta_harvester_scan",
                    name="Theta Harvester short-strangle scan",
                    max_instances=1,
                    coalesce=True,
                )
                # Markout at 19:55 ET — 10 min after the scan, so the same
                # session's grid is available for any horizon coming due today.
                sched.add_job(
                    _theta_harvester_markout,
                    CronTrigger.from_crontab("55 19 * * 0-4", timezone=settings.rth_tz),
                    id="theta_harvester_markout",
                    name="Theta Harvester forward markout",
                    max_instances=1,
                    coalesce=True,
                )
            # Technicals daily refresh at 18:40 ET — after apex's own EOD sync and
            # before the 18:50 vrp_markout job. apex bars cost no UW budget, so
            # massive-0 is the right single-flight home. Idempotent; flag-gated.
            if settings.technicals_refresh_enabled:
                sched.add_job(
                    _technical_daily_refresh,
                    CronTrigger.from_crontab("40 18 * * 0-4", timezone=settings.rth_tz),
                    id="technical_daily_refresh",
                    name="Technicals daily refresh (apex bars -> technical_daily)",
                    max_instances=1,
                    coalesce=True,
                )
            # Corporate-actions ingestion at 17:35 ET — after the 17:30 OHLC pull,
            # before the research compute. Ingests split/dividend history (massive)
            # over the vrp_daily ∪ watchlist ∪ fundamental-universe names, for
            # exact-RV adjustment and for the valuation band's price-basis guard.
            # The 45-minute gap to `fundamental_refresh` at 18:20 is what arms
            # that guard on the first day after a deploy rather than leaving it
            # blind until the next fill.
            sched.add_job(
                _corporate_actions_refresh,
                CronTrigger.from_crontab("35 17 * * 0-4", timezone=settings.rth_tz),
                id="corporate_actions_refresh",
                name="Corporate-actions ingestion",
                max_instances=1,
                coalesce=True,
            )
            # M9 v5.3 outcome ledger — runs nightly at 17:00 ET, right after
            # the 17:30 OHLC pull would have updated daily_ohlc. Scores
            # outcomes from forward-looking closes; idempotent re-runs are
            # bounded by the partial pending-index in migration 054.
            sched.add_job(
                _trade_insight_outcome_backfill,
                CronTrigger.from_crontab("0 17 * * 0-4", timezone=settings.rth_tz),
                id="trade_insight_outcome_backfill",
                name="Trade insight outcome backfill",
                max_instances=1,
                coalesce=True,
            )

    if "uw" in groups:
        if _is_primary_worker(settings):
            # On-demand volatility backfill queue (GET /volatility/series
            # enqueues). uw-0 only: one UW-spending claimer is enough.
            sched.add_job(
                _volatility_backfill_tick,
                IntervalTrigger(seconds=10),
                id="volatility_backfill_tick",
                name="On-demand volatility backfill queue",
                max_instances=1,
                coalesce=True,
            )
        if _is_primary_worker(settings):
            # Single-name greek_exposure_daily refresh — UW aggregate
            # /greek-exposure history (~1 call/ticker), single-flight on uw-0.
            # Runs at 18:30 ET, inside the UW flow window, after the 18:00 vol
            # rollup (#179).
            sched.add_job(
                _greek_exposure_daily_refresh,
                CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
                id="greek_exposure_daily_refresh",
                name="Single-name greek_exposure_daily refresh (#179)",
                max_instances=1,
                coalesce=True,
            )
            # Economic-release calendar capture + FRED actual fill — pinned to
            # uw-0, gated by UW_SCAN_MACRO_RELEASE_CALENDAR_ENABLED. 1 UW call/day.
            if settings.macro_release_calendar_enabled:
                sched.add_job(
                    _macro_release_calendar_capture,
                    CronTrigger.from_crontab("35 18 * * 0-4", timezone=settings.rth_tz),
                    id="macro_release_calendar_capture",
                    name="Economic-release calendar capture + FRED fill",
                    max_instances=1,
                    coalesce=True,
                )
            # UW historical-alpha nightly capture (5 datasets) — pinned to uw-0,
            # gated by UW_SCAN_UW_ALPHA_CAPTURE_ENABLED. Staggered 18:35-18:55 ET,
            # after the 18:30 greek refresh, before the 20:00 healer / 21:00
            # freshness monitor. NOT budget-gated (durable data near the reset).
            if _should_schedule_uw_alpha_capture(settings):
                from uw_scan.worker.jobs.uw_alpha_capture import (
                    dark_lit_capture,
                    gex_levels_capture,
                    intraday_flow_capture,
                    short_pressure_capture,
                    volatility_signal_capture,
                )

                for wrapper, hhmm, jid in [
                    (gex_levels_capture, "35 18", "uw_alpha_gex_capture"),
                    (volatility_signal_capture, "40 18", "uw_alpha_volatility_capture"),
                    (
                        short_pressure_capture,
                        "45 18",
                        "uw_alpha_short_pressure_capture",
                    ),
                    (
                        intraday_flow_capture,
                        "50 18",
                        "uw_alpha_intraday_flow_capture",
                    ),
                    (dark_lit_capture, "55 18", "uw_alpha_dark_lit_capture"),
                ]:
                    sched.add_job(
                        _make_uw_alpha_capture(wrapper, jid),
                        CronTrigger.from_crontab(
                            f"{hhmm} * * 0-4", timezone=settings.rth_tz
                        ),
                        id=jid,
                        name=f"UW alpha capture: {jid}",
                        max_instances=1,
                        coalesce=True,
                    )
            # Data-date freshness monitor (#prevention) — DB-only audit at
            # 21:00 ET, after all nightly writers have run, so it sees the
            # freshest data each day.
            sched.add_job(
                _data_freshness_monitor,
                CronTrigger.from_crontab("0 21 * * 0-4", timezone=settings.rth_tz),
                id="data_freshness_monitor",
                name="Data-date freshness monitor (prevention)",
                max_instances=1,
                coalesce=True,
            )
            # Cockpit nightly snapshot — UW-bound (greeks/IV/RV/skew) and
            # single-flight via pg_try_advisory_lock; only the primary uw
            # worker schedules it to avoid duplicate UW spend.
            sched.add_job(
                _cockpit_daily_snapshot,
                CronTrigger.from_crontab(
                    settings.cockpit_snapshot_cron, timezone=settings.rth_tz
                ),
                id="cockpit_daily_snapshot",
                name="Cockpit 6-dim matrix daily snapshot",
            )
            if _should_schedule_data_gap_healer(settings):
                sched.add_job(
                    _data_gap_healer,
                    CronTrigger.from_crontab(
                        settings.data_gap_healer_cron_et, timezone=settings.rth_tz
                    ),
                    id="data_gap_healer",
                    name="Nightly data gap healer",
                    max_instances=1,
                    coalesce=True,
                )

    if _should_schedule_pipeline_benchmark(settings):
        sched.add_job(
            _pipeline_benchmark_snapshot,
            IntervalTrigger(minutes=5),
            id="pipeline_benchmark_snapshot",
            name="Pipeline benchmark snapshot",
            max_instances=1,
            coalesce=True,
        )
        # Same singleton owner. Persists the record-health counts /api/health
        # reads, so the API never sweeps the big tables itself.
        sched.add_job(
            lambda: record_health_snapshot_job(settings),
            IntervalTrigger(minutes=15),
            id="record_health_snapshot",
            name="Record health snapshot",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )


    if settings.technical_live_enabled and _should_schedule_regime_live(settings):
        # Live technicals coverage — upsert-per-ticker cache off intraday_quote.
        # Reuses the regime-live single-owner pin (massive-0); pure DB-read
        # splice-recompute, no provider spend.
        sched.add_job(
            _technical_live_scan,
            IntervalTrigger(minutes=settings.technical_live_scan_interval_minutes),
            id="technical_live_scan",
            name="Live technicals coverage",
            max_instances=1,
            coalesce=True,
        )


    if _should_schedule_sector_rs_daily(settings):
        # Sector RS + breadth at 21:30 ET Mon–Fri: after ohlc_pull (17:30), so
        # the daily_ohlc fallback holds tonight's SPY/ETF closes, and after the
        # 21:00 freshness monitor. Zero UW spend → massive-0.
        sched.add_job(
            _sector_rs_daily,
            CronTrigger(
                hour=21, minute=30, day_of_week="mon-fri", timezone=settings.rth_tz
            ),
            id="sector_rs_daily",
            name="Sector RS + breadth (gics ETFs + watchlist chains)",
            max_instances=1,
            coalesce=True,
        )

    if _should_schedule_mcp_event_retention(settings):
        # mcp_event pruning at 04:10 ET DAILY — pure housekeeping DELETE on an
        # append-only table; zero UW/IB spend → massive-0, same pin as
        # sector_rs_daily. Well clear of the RTH open and the nightly batch.
        sched.add_job(
            _mcp_event_retention,
            CronTrigger(hour=4, minute=10, timezone=settings.rth_tz),
            id="mcp_event_retention",
            name="MCP event retention (purge >30d)",
            max_instances=1,
            coalesce=True,
        )



    register_vrp_jobs(sched, settings)
    register_surface_jobs(sched, settings)
    register_macro_jobs(sched, settings)
    register_regime_jobs(sched, settings)
    register_fundamentals_jobs(sched, settings, ticker_filter=ticker_filter)
    register_scan_core_jobs(sched, settings, ticker_filter=ticker_filter)
    register_ai_jobs(sched, settings)

    if _owns_global_daily_jobs(settings):
        register_gold_jobs(sched, settings)

    stopping = False

    def _stop(_sig, _frame):
        nonlocal stopping
        if stopping:
            sys.exit(0)
        stopping = True
        logger.info("received signal, shutting down scheduler")
        try:
            sched.shutdown(wait=False)
        except SchedulerNotRunningError as exc:
            logger.debug("scheduler already stopped during shutdown: %s", repr(exc))
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("scheduler started role=%s groups=%s", _worker_label(settings), groups)
    sched.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
