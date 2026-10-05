"""Ops family: the data-date freshness monitor, the pipeline benchmark and
record-health snapshots, the nightly data gap healer, and the mcp_event purge.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (uw-0 primary, the uw-0 / massive-0 pins, the healer flag).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.jobs.data_gap_healer import data_gap_healer_job
from uw_scan.worker.jobs.pipeline_benchmark import pipeline_benchmark_snapshot_job
from uw_scan.worker.jobs.record_health_snapshot import record_health_snapshot_job
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _pinned,
    _worker_groups,
)

logger = logging.getLogger(__name__)


def _should_schedule_pipeline_benchmark(settings: Settings) -> bool:
    return _pinned(settings, "uw")


def _should_schedule_data_gap_healer(settings: Settings) -> bool:
    """Nightly gap healer runs on exactly one process (uw-0 or 'all'), and only
    when enabled. Off by default until manual runs prove it safe."""
    return settings.data_gap_healer_enabled and _pinned(settings, "uw")


def _should_schedule_mcp_event_retention(settings: Settings) -> bool:
    """Single owner for the nightly mcp_event purge. Pure warm-store
    housekeeping DELETE — no UW/IB spend → pin to massive-0, same as
    sector_rs_daily. No enable flag: pure housekeeping (agent-mcp plan M3)."""
    return _pinned(settings, "massive")


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

    def _mcp_event_retention() -> None:
        from uw_scan.storage.mcp_events import purge_old_events

        with _repo(settings) as repo:
            deleted = purge_old_events(repo.conn, days=30)
            repo.conn.commit()
        logger.info("mcp_event_retention deleted=%d", deleted)

    def _data_freshness_monitor() -> None:
        # Per-table data-date freshness audit (#prevention) — DB-only, zero UW.
        from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor

        with _repo(settings) as repo:
            data_freshness_monitor(
                repo=repo,
                settings=settings,
                today=datetime.now(ZoneInfo(settings.rth_tz)).date(),
            )

    def _data_gap_healer() -> None:
        if not settings.data_gap_healer_enabled:
            return
        today = datetime.now(ZoneInfo(settings.rth_tz)).date()
        data_gap_healer_job(settings=settings, today=today)

    def _pipeline_benchmark_snapshot() -> None:
        pipeline_benchmark_snapshot_job(settings)

    if "uw" in groups:
        if _is_primary_worker(settings):
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
