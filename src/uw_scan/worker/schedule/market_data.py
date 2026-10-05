"""Market-data family: daily SPY OHLC, corporate actions, technicals (daily
refresh and live coverage), single-name greek exposure, the cockpit snapshot,
the UW historical-alpha captures, sector RS, the economic-release calendar, the
on-demand volatility backfill queue, the SPX density cone, the Theta Harvester
scan and markout, and the trade-insight outcome backfill.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (massive-0 primary, uw-0 primary, the regime-live
owner, its own flag or pin).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import fundamentals_provider as _fundamentals_provider
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import research_budget_ok as _research_budget_ok
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh
from uw_scan.worker.jobs.theta_harvester import (
    theta_harvester_markout,
    theta_harvester_scan,
)
from uw_scan.worker.jobs.trade_insight_outcome_backfill import (
    trade_insight_outcome_backfill_once,
)
from uw_scan.worker.jobs.volatility_backfill import volatility_backfill_tick
from uw_scan.worker.schedule.regime import _should_schedule_regime_live
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _pinned,
    _worker_groups,
)
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
)

logger = logging.getLogger(__name__)


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


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

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

    def _dark_lit_backfill() -> None:
        from uw_scan.sources.apex import fetch_bulk_daily_closes
        from uw_scan.worker.jobs.dark_lit_backfill import JOB_NAME, dark_lit_backfill

        def _sessions(start, end):
            # SPY's daily bars are the trading calendar back to 2023 (the
            # warm-store spine starts 2025-04); one apex call, zero UW spend.
            closes = fetch_bulk_daily_closes(
                ["SPY"], base_url=settings.apex_api_url, start=start, end=end
            )
            return sorted(closes.get("SPY", {}))

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name=JOB_NAME
            ) as uw:
                with _repo(settings) as repo:
                    dark_lit_backfill(
                        repo=repo,
                        client=uw,
                        settings=settings,
                        sessions_fn=_sessions,
                        budget_ok=lambda: _research_budget_ok(settings, repo),
                    )

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

    def _cockpit_daily_snapshot() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="cockpit_daily_snapshot",
            ) as uw:
                with _repo(settings) as repo:
                    cockpit_daily_snapshot(repo=repo, client=uw, settings=settings)

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
            # Dark/lit print history backfill — uw-0, default off. 22:30 ET: after
            # the 18:15-20:00 UW capture peak and the 20:00 ET (00:00 UTC) budget
            # reset, so each run spends one fresh UTC budget day's cap and exits.
            # Daily: the Friday and Saturday evening runs are UTC Sat/Sun.
            if settings.dark_lit_backfill_enabled and _pinned(settings, "uw"):
                sched.add_job(
                    _dark_lit_backfill,
                    CronTrigger.from_crontab("30 22 * * *", timezone=settings.rth_tz),
                    id="dark_lit_backfill",
                    name="Dark/lit print history backfill (budgeted)",
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
