"""Surface family: the nightly vol and skew rollups, the skew markout, the
swing-DTE greeks refresh, the full-chain option-surface capture (watchlist and
research cohort, plus the cohort's history catch-up), and the IB-vs-UW IV canary.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (massive-0 primary, uw-0 primary plus its uw-0 pin).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import external_api_recorder as _external_api_recorder
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.db import research_budget_ok as _research_budget_ok
from uw_scan.worker.db import uw_client as _uw_client
from uw_scan.worker.jobs.option_surface_capture import option_surface_capture
from uw_scan.worker.jobs.option_surface_iv_canary import option_surface_iv_canary
from uw_scan.worker.jobs.option_surface_research_capture import (
    option_surface_research_capture,
)
from uw_scan.worker.jobs.option_surface_research_catchup import (
    option_surface_research_catchup,
)
from uw_scan.worker.jobs.skew_analytics import (
    nightly_skew_analytics_rollup,
    skew_markout_refresh,
)
from uw_scan.worker.jobs.skew_swing_greeks import skew_swing_greeks_refresh
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _pinned,
    _worker_groups,
)
from uw_scan.worker.volatility_jobs import (
    nightly_vol_analytics_rollup,
)

logger = logging.getLogger(__name__)


def _should_schedule_option_surface_capture(settings: Settings) -> bool:
    """Exactly one process owns the nightly full-chain surface capture.

    A UW-bound watchlist loop with no advisory lock; scheduling it on every role's
    index-0 would multiply UW /greeks spend (429 risk) and race upserts. Pin to uw-0,
    following the skew_swing / rates-FRED precedent.
    """
    return _pinned(settings, "uw")


def _should_schedule_skew_swing_greeks(settings: Settings) -> bool:
    """Exactly one process owns the swing-greeks refresh.

    It is a UW-bound watchlist loop with no advisory lock (unlike the cockpit
    snapshot, which single-flights via pg_try_advisory_lock). _is_primary_worker is
    true for index-0 of EVERY role (uw-0, massive-0, ai-*-0), so scheduling it there
    would run it N times -> duplicate UW /greeks spend (429 risk) + racing
    delete-then-insert on skew_swing_greeks. Pin to uw-0 (the UW role), following the
    rates-FRED / pipeline-benchmark precedent.
    """
    return _pinned(settings, "uw")


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

    def _vol_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_vol_analytics_rollup(repo=repo)

    def _skew_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_skew_analytics_rollup(repo=repo)

    def _skew_markout_refresh() -> None:
        with _repo(settings) as repo:
            skew_markout_refresh(repo=repo)

    def _option_surface_capture() -> None:
        if not settings.option_surface_capture_enabled:
            return
        # ET market date (not host-local) so a non-ET host doesn't stamp +1 day.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="option_surface_capture"
            ) as uw:
                with _repo(settings) as repo:
                    option_surface_capture(
                        repo=repo,
                        client=uw,
                        today=market_date,
                        backfill_days=settings.option_surface_backfill_days,
                    )

    def _option_surface_research_capture() -> None:
        if not settings.option_surface_research_capture_enabled:
            return
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="option_surface_research_capture",
            ) as uw:
                with _repo(settings) as repo:
                    option_surface_research_capture(
                        repo=repo,
                        client=uw,
                        cohort=settings.option_surface_research_cohort,
                        today=market_date,
                    )

    def _option_surface_research_catchup() -> None:
        if not settings.option_surface_research_catchup_enabled:
            return
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="option_surface_research_catchup",
            ) as uw:
                with _repo(settings) as repo:
                    # Gated, unlike the 19:00/19:10 durable captures. Those are
                    # unrecoverable if skipped, so they take priority; this one is
                    # pure catch-up over a window that is still fetchable
                    # tomorrow, and it is the bulkiest research spender of the
                    # night. Deferring a batch costs one day of latency.
                    if not _research_budget_ok(settings, repo):
                        logger.info(
                            "option_surface_research_catchup skipped: research UW "
                            "budget exhausted"
                        )
                        return
                    option_surface_research_catchup(
                        repo=repo,
                        client=uw,
                        cohort=settings.option_surface_research_cohort,
                        today=market_date,
                        max_calls=settings.option_surface_research_catchup_max_calls,
                    )

    def _option_surface_iv_canary() -> None:
        if not settings.option_surface_iv_canary_enabled:
            return
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            option_surface_iv_canary(repo=repo, settings=settings, today=market_date)

    def _skew_swing_greeks_refresh() -> None:
        # ET market date (not host-local) so a non-ET host doesn't stamp +1 day.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="skew_swing_greeks",
            ) as uw:
                with _repo(settings) as repo:
                    skew_swing_greeks_refresh(repo=repo, client=uw, today=market_date)

    if "massive" in groups:
        if _is_primary_worker(settings):
            sched.add_job(
                _vol_analytics_rollup,
                CronTrigger.from_crontab("0 18 * * 0-4", timezone=settings.rth_tz),
                id="nightly_vol_analytics_rollup",
                name="Nightly vol analytics rollup",
            )
            # Skew rollup at 18:30 ET — after the 18:00 vol rollup so the
            # per-day skew snapshots build on fresh RV/IV. Idempotent upsert.
            sched.add_job(
                _skew_analytics_rollup,
                CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
                id="nightly_skew_analytics_rollup",
                name="Nightly skew analytics rollup",
                max_instances=1,
                coalesce=True,
            )
            # Skew markout at 18:45 ET — after the 18:30 rollup so it scores the day's
            # fresh snapshot. This is the job that was missing: it re-scores all skew
            # snapshots and (re)writes skew_directional_verdicts / RV-reversion verdicts.
            # Without it the verdict store stayed empty and every directional lean was
            # NEUTRAL. Pure compute over the warm store (no external calls); idempotent.
            sched.add_job(
                _skew_markout_refresh,
                CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
                id="skew_markout_refresh",
                name="Skew markout verdict refresh",
                max_instances=1,
                coalesce=True,
            )

    if "uw" in groups:
        if _is_primary_worker(settings):
            # Skew swing-DTE greeks at 17:30 ET — UW-bound watchlist loop, before the
            # 18:30 skew rollup so the strike-by-delta structure detail has a fresh swing
            # chain. Pinned to uw-0 (NOT _is_primary_worker, which is true for index-0 of
            # every role) because it has no advisory lock: scheduling it per role-0 would
            # run N copies -> duplicate UW spend + racing delete-then-insert.
            if _should_schedule_skew_swing_greeks(settings):
                sched.add_job(
                    _skew_swing_greeks_refresh,
                    CronTrigger.from_crontab("30 17 * * 0-4", timezone=settings.rth_tz),
                    id="skew_swing_greeks_refresh",
                    name="Skew swing-DTE greeks refresh",
                    max_instances=1,
                    coalesce=True,
                )
            if _should_schedule_option_surface_capture(settings):
                sched.add_job(
                    _option_surface_capture,
                    CronTrigger.from_crontab("0 19 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_capture",
                    name="Option surface full-chain capture",
                    max_instances=1,
                    coalesce=True,
                )
                # 19:10, between the watchlist capture (19:00) and the IV canary
                # (19:30). Sequential rather than concurrent: both loops are UW
                # /greeks-bound against a shared per-minute ceiling, and
                # overlapping them is how you turn two comfortable jobs into two
                # throttled ones.
                sched.add_job(
                    _option_surface_research_capture,
                    CronTrigger.from_crontab("10 19 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_research_capture",
                    name="Option surface capture (research cohort)",
                    max_instances=1,
                    coalesce=True,
                )
                # 03:20 ET, not in the 19:00-19:30 capture block. The account
                # counter resets at 20:00 ET, so this runs against a fresh budget
                # and cannot eat the evening's durable captures.
                #
                # Mon-Fri (APScheduler Monday=0) purely to match the house
                # convention — unlike the captures, this job has no session
                # dependency at all. It fills weekly sample dates from up to 180
                # days back, and weekly_sessions() already excludes today, so
                # which weekday it runs on changes nothing but how soon it
                # finishes.
                sched.add_job(
                    _option_surface_research_catchup,
                    CronTrigger.from_crontab("20 3 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_research_catchup",
                    name="Option surface catch-up (research cohort history)",
                    max_instances=1,
                    coalesce=True,
                )
                sched.add_job(
                    _option_surface_iv_canary,
                    CronTrigger.from_crontab("30 19 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_iv_canary",
                    name="Option surface IB-vs-UW IV canary",
                    max_instances=1,
                    coalesce=True,
                )
