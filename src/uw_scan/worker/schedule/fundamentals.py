"""Fundamentals family: the massive statement refresh, the fundamental-lane
recompute, the UW statement / revenue-breakdown / vendor-sector captures, and the
industry-desk spine (earnings reactions, implied move, delta rail, desk rollup).

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (massive group, massive-0, uw-0, its own predicate).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import fundamentals_provider as _fundamentals_provider
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _pinned,
    _worker_groups,
)

logger = logging.getLogger(__name__)


def _should_schedule_fundamental_ingest(settings: Settings) -> bool:
    """One process owns the monthly statement pull. Pinned to uw-0, not
    `_is_primary_worker` (true for index-0 of every role) — the job has no
    advisory lock, so scheduling it per role-0 would multiply UW spend and race
    the insert-or-touch on identical content hashes."""
    if not settings.fundamental_ingest_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_fundamental_ingest_daily(settings: Settings) -> bool:
    """Same uw-0 pin and the same reason as the monthly sweep it complements:
    no advisory lock, so a per-role-0 schedule would run N copies of the same
    calendar pull against one insert-or-touch table."""
    if not settings.fundamental_ingest_daily_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_fundamental_concentration_capture(settings: Settings) -> bool:
    """Same uw-0 pin and the same reason as the statement ingest: no advisory
    lock, so a per-role-0 schedule would run N copies of a 450-call job against
    one insert-or-touch table."""
    if not settings.fundamental_concentration_capture_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_company_sector_refresh(settings: Settings) -> bool:
    """Same uw-0 pin as its monthly siblings: no advisory lock, and N copies
    would each spend a call per ticker on one upsert table."""
    if not settings.company_sector_refresh_enabled:
        return False
    return _pinned(settings, "uw")


def _should_schedule_earnings_reactions(settings: Settings) -> bool:
    """Single owner for the nightly earnings-reaction compute. Pure warm-store
    read (calendar x daily_ohlc, no UW/IB spend) -> pin to massive-0, same as
    vrp_markout / chanlun_lifecycle. Gated separately on `earnings_reactions_enabled`."""
    if not settings.earnings_reactions_enabled:
        return False
    return _pinned(settings, "massive")


def _should_schedule_implied_move(settings: Settings) -> bool:
    """Single owner for the nightly implied-move snapshot. Pure warm-store
    read (calendar x option_surface_grid_daily, no UW/IB spend) -> pin to
    massive-0, same as earnings_reactions / vrp_markout / chanlun_lifecycle.
    Gated separately on `implied_move_snapshot_enabled`."""
    if not settings.implied_move_snapshot_enabled:
        return False
    return _pinned(settings, "massive")


def _should_schedule_fundamental_change_events(settings: Settings) -> bool:
    """Single owner for the nightly delta-rail derive (Task 8, spec §5-iv).
    Pure warm-store read over valuation_anchors / implied_move_daily /
    fundamental_statement_obs / chain_membership / fundamental_scores -- no
    UW/IB spend -> pin to massive-0, same as its siblings above. Gated
    separately on `fundamental_change_events_enabled`."""
    if not settings.fundamental_change_events_enabled:
        return False
    return _pinned(settings, "massive")


def _should_schedule_fundamentals_desk_rollup(settings: Settings) -> bool:
    """Single owner for the nightly desk matrix rollup (Task 12, spec §3c).
    Pure warm-store read (the statement panel + its recorded violations) --
    no UW/IB spend -> pin to massive-0, same as its industry-desk siblings
    above. Gated separately on `fundamentals_desk_rollup_enabled`."""
    if not settings.fundamentals_desk_rollup_enabled:
        return False
    return _pinned(settings, "massive")


def register(
    sched: BaseScheduler,
    settings: Settings,
    *,
    ticker_filter: Callable[[str], bool],
) -> None:
    groups = _worker_groups(settings)

    def _fundamentals_refresh() -> None:
        provider = _fundamentals_provider(settings)
        if provider is None:
            logger.warning("MASSIVE_API_KEY not set; skipping fundamentals refresh")
            return
        try:
            with _repo(settings) as repo:
                n = fundamentals_refresh_once(
                    repo, provider, ticker_filter=ticker_filter
                )
                logger.info("fundamentals_refresh refreshed %d tickers", n)
        finally:
            provider.close()

    def _earnings_reactions_compute() -> None:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from uw_scan.worker.jobs.earnings_reactions import earnings_reactions_compute

        as_of = _dt.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            result = earnings_reactions_compute(
                repo.conn, as_of=as_of, schema=settings.db_schema
            )
        logger.info("earnings_reactions_compute %s", result)

    def _implied_move_snapshot() -> None:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from uw_scan.worker.jobs.implied_move_snapshot import implied_move_snapshot

        as_of = _dt.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            result = implied_move_snapshot(
                repo.conn, as_of=as_of, schema=settings.db_schema
            )
        logger.info("implied_move_snapshot %s", result)

    def _fundamental_change_events() -> None:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from uw_scan.worker.jobs.fundamental_change_events import (
            derive_change_events,
        )

        as_of = _dt.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            result = derive_change_events(
                repo.conn, as_of=as_of, schema=settings.db_schema
            )
        logger.info("fundamental_change_events %s", result)

    def _fundamentals_desk_rollup() -> None:
        from uw_scan.worker.jobs.fundamentals_desk_rollup import (
            fundamentals_desk_rollup,
        )

        with _repo(settings) as repo:
            result = fundamentals_desk_rollup(repo.conn, schema=settings.db_schema)
        logger.info("fundamentals_desk_rollup %s", result)

    def _fundamental_refresh() -> None:
        from uw_scan.worker.jobs.fundamental_refresh import fundamental_refresh

        with _repo(settings) as repo:
            fundamental_refresh(conn=repo.conn, settings=settings)

    def _fundamental_ingest() -> None:
        from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
        from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest
        from uw_scan.worker.jobs.fundamental_ingest_daily import (
            persist_unknown_statements,
        )

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="fundamental_ingest",
            ) as uw:
                with _repo(settings) as repo:
                    counters = fundamental_ingest(
                        conn=repo.conn, client=uw, schema=settings.db_schema
                    )
                    # Unfiltered by calendar (this ingests the whole tier), so this is
                    # the only caller that can hand `persist_unknown_statements` a
                    # ticker UW never lists in either classified slot — the ~2%
                    # `report_time: "unknown"` population spec §5-i exists for. The
                    # daily job (`fundamental_ingest_daily.py`) mirrors this same call
                    # against its own, calendar-filtered `new_filings`.
                    new_filings = counters.pop("new_filings", [])
                    calendar_repo = EarningsCalendarRepository(
                        repo.conn, schema=settings.db_schema
                    )
                    counters["calendar_unknown_rows_new"] = persist_unknown_statements(
                        calendar_repo, new_filings
                    )
        logger.info("fundamental_ingest %s", counters)

    def _fundamental_ingest_daily() -> None:
        from uw_scan.worker.jobs.fundamental_ingest_daily import (
            fundamental_ingest_daily,
        )

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="fundamental_ingest_daily",
            ) as uw:
                with _repo(settings) as repo:
                    counters = fundamental_ingest_daily(
                        conn=repo.conn,
                        client=uw,
                        today=datetime.now(ZoneInfo(settings.rth_tz)).date(),
                        lookback_days=settings.fundamental_ingest_daily_lookback_days,
                        forward_days=settings.fundamental_ingest_daily_forward_days,
                        schema=settings.db_schema,
                    )
        logger.info("fundamental_ingest_daily %s", counters)

    def _fundamental_concentration_capture() -> None:
        from uw_scan.worker.jobs.fundamental_concentration_capture import (
            fundamental_concentration_capture,
        )

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="fundamental_concentration_capture",
            ) as uw:
                with _repo(settings) as repo:
                    counters = fundamental_concentration_capture(
                        conn=repo.conn, client=uw, schema=settings.db_schema
                    )
        logger.info("fundamental_concentration_capture %s", counters)

    def _company_sector_refresh() -> None:
        from uw_scan.worker.jobs.company_sector_refresh import company_sector_refresh

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="company_sector_refresh",
            ) as uw:
                with _repo(settings) as repo:
                    counters = company_sector_refresh(
                        conn=repo.conn,
                        client=uw,
                        schema=settings.db_schema,
                        include_sp500=True,
                    )
        logger.info("company_sector_refresh %s", counters)

    if "massive" in groups:
        sched.add_job(
            _fundamentals_refresh,
            CronTrigger.from_crontab(
                settings.fundamentals_refresh_cron, timezone=settings.rth_tz
            ),
            id="fundamentals_refresh",
            name="Nightly massive fundamentals refresh",
            max_instances=1,
            coalesce=True,
        )
    if "massive" in groups:
        if _is_primary_worker(settings):
            # Fundamental lane recompute at 18:20 ET — after the 17:30 OHLC pull
            # so the closes the band is marked against are today's, and before
            # the 18:30+ block so it does not queue behind them. Routing ->
            # subscores -> anchor bands, all warm-store + local-lake compute:
            # zero UW/IB spend, which is why it sits on massive-0. Runs nightly
            # even with no new filing, because spot moves daily and
            # valuation_anchors.as_of is the SPOT date — the close the row was
            # priced at, not this job's clock. A healthy 18:20 Monday run writes
            # as_of = Friday, since the lake lands a session near midnight NY.
            # Do NOT health-check that table with max(as_of) >= today.
            if settings.fundamental_refresh_enabled:
                sched.add_job(
                    _fundamental_refresh,
                    CronTrigger.from_crontab("20 18 * * 0-4", timezone=settings.rth_tz),
                    id="fundamental_refresh",
                    name="Fundamental routing + subscores + valuation anchors",
                    max_instances=1,
                    coalesce=True,
                )
    if "uw" in groups:
        if _is_primary_worker(settings):
            # Monthly statement pull, 03:40 ET on the 2nd. Overnight and off the
            # 2nd-of-month boundary that quarter-end reporting clusters around, so
            # it never contends with the 19:00 surface capture for the shared UW
            # per-minute ceiling.
            if _should_schedule_fundamental_ingest(settings):
                sched.add_job(
                    _fundamental_ingest,
                    CronTrigger.from_crontab(
                        settings.fundamental_ingest_cron, timezone=settings.rth_tz
                    ),
                    id="fundamental_ingest",
                    name="Fundamental statement ingest (monthly)",
                    max_instances=1,
                    coalesce=True,
                )
            # Daily calendar-driven statement pull, 04:20 ET. Complements the
            # monthly sweep above rather than replacing it: the premarket/
            # afterhours pair is the CLASSIFIED calendar and misses names whose
            # report_time UW leaves "unknown" (~2% of the statement-bearing
            # universe), and the full sweep is the only thing that re-pulls a
            # period late enough to collect a filing date UW published after we
            # first stored the row. Runs every day, not weekdays, so a Monday
            # holiday cannot open a hole the 3-day lookback fails to reach.
            if _should_schedule_fundamental_ingest_daily(settings):
                sched.add_job(
                    _fundamental_ingest_daily,
                    CronTrigger.from_crontab(
                        settings.fundamental_ingest_daily_cron,
                        timezone=settings.rth_tz,
                    ),
                    id="fundamental_ingest_daily",
                    name="Fundamental statement ingest (daily, calendar-driven)",
                    max_instances=1,
                    coalesce=True,
                )
            # Monthly revenue-breakdown capture, 04:10 ET on the 3rd — a day
            # after the statement ingest so the two monthly uw-0 jobs never
            # share a per-minute ceiling. Accrual, not analysis: see the job.
            if _should_schedule_fundamental_concentration_capture(settings):
                sched.add_job(
                    _fundamental_concentration_capture,
                    CronTrigger.from_crontab(
                        settings.fundamental_concentration_capture_cron,
                        timezone=settings.rth_tz,
                    ),
                    id="fundamental_concentration_capture",
                    name="Fundamental revenue-breakdown capture (monthly)",
                    max_instances=1,
                    coalesce=True,
                )
            # Vendor-sector fill, 04:40 ET DAILY — a cache top-up, not an
            # accrual like the two monthly uw-0 jobs above it. It asks only
            # names with no row, so the first run costs one call per universe
            # ticker and every run after it costs zero. Daily is what makes the
            # table non-empty the morning after a deploy; monthly left the
            # vendor pass blind for up to 31 days. Answers one routing question
            # the chain taxonomy cannot ("is this a deposit-funded financial?")
            # for the universe names with no watchlist row — see the job.
            if _should_schedule_company_sector_refresh(settings):
                sched.add_job(
                    _company_sector_refresh,
                    CronTrigger.from_crontab(
                        settings.company_sector_refresh_cron,
                        timezone=settings.rth_tz,
                    ),
                    id="company_sector_refresh",
                    name="Vendor sector fill for company_type routing (daily)",
                    max_instances=1,
                    coalesce=True,
                )
    if _should_schedule_earnings_reactions(settings):
        # Earnings reaction compute at 19:41 ET DAILY — not weekday-only, since
        # a Monday-holiday print's Tuesday close still needs to be picked up on
        # schedule. Pure warm-store read (calendar x daily_ohlc); zero UW/IB
        # spend, so massive-0 is the right single-flight home, same pin as
        # regime_live/chanlun_lifecycle above. Shifted one minute off :40
        # (branch-fix-p2, M10) — vrp_paper_mark and macro_state_compute both
        # also fire at 19:40 on massive-0; each opens its own connection and
        # APScheduler's default pool is 10, so this was contention, not
        # breakage, but a minute's shift buys legibility in the job logs for
        # free.
        sched.add_job(
            _earnings_reactions_compute,
            CronTrigger.from_crontab("41 19 * * *", timezone=settings.rth_tz),
            id="earnings_reactions_compute",
            name="Earnings reaction history (calendar x OHLC)",
            max_instances=1,
            coalesce=True,
        )
    if _should_schedule_implied_move(settings):
        # Implied-move snapshot at 20:45 ET WEEKDAYS — after the 19:00/19:30
        # surface-capture jobs so tonight's option_surface_grid_daily rows
        # are already written, and after the 19:40 earnings-reaction compute
        # (unrelated table, but keeps the fundamentals-industry-desk jobs in
        # one block). Pure warm-store read (calendar x surface grid); zero
        # UW/IB spend, so massive-0 is the right single-flight home, same
        # pin as earnings_reactions above.
        sched.add_job(
            _implied_move_snapshot,
            CronTrigger.from_crontab("45 20 * * 0-4", timezone=settings.rth_tz),
            id="implied_move_snapshot",
            name="Implied move snapshot (option surface grid)",
            max_instances=1,
            coalesce=True,
        )
    if _should_schedule_fundamental_change_events(settings):
        # Delta-rail derive at 21:15 ET WEEKDAYS (Task 8, spec §5-iv) — after
        # the 20:45 implied_move_snapshot and the 18:20 fundamental_refresh
        # (routing -> subscores -> anchor bands) so band_entry/band_exit and
        # bucket_flip read tonight's freshest valuation_anchors/
        # fundamental_scores rows, and after implied_move_snapshot so
        # implied_move_shift reads tonight's implied_move_daily row rather
        # than last night's. Pure warm-store read; zero UW/IB spend, so
        # massive-0 is the right single-flight home, same pin as its
        # siblings above.
        sched.add_job(
            _fundamental_change_events,
            CronTrigger.from_crontab("15 21 * * 0-4", timezone=settings.rth_tz),
            id="fundamental_change_events",
            name="Fundamental delta-rail change events",
            max_instances=1,
            coalesce=True,
        )
    if _should_schedule_fundamentals_desk_rollup(settings):
        # Desk matrix rollup at 21:30 ET DAILY (Task 12, spec §3c) -- not
        # weekday-only, since the statement store and its violations can
        # change any day (a `recheck_violations` replay, a late restatement)
        # and the matrix should reflect that the next morning regardless of
        # what day it landed. Pure warm-store read (statement panel +
        # violations); zero UW/IB spend, so massive-0 is the right
        # single-flight home, same pin as its industry-desk siblings above.
        sched.add_job(
            _fundamentals_desk_rollup,
            CronTrigger.from_crontab("30 21 * * *", timezone=settings.rth_tz),
            id="fundamentals_desk_rollup",
            name="Fundamentals desk matrix rollup (rev YoY, gross margin)",
            max_instances=1,
            coalesce=True,
        )
