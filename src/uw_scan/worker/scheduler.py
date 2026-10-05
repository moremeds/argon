"""APScheduler driver: registers the three cron jobs + the ad-hoc rescan poll."""

from __future__ import annotations

import logging
import signal
import sys

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.storage.ops_health import _ops_conn
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.schedule.gold import register as register_gold_jobs
from uw_scan.worker.schedule.vrp import register as register_vrp_jobs
from uw_scan.worker.schedule.surface import register as register_surface_jobs
from uw_scan.worker.schedule.ops import register as register_ops_jobs
from uw_scan.worker.schedule.market_data import register as register_market_data_jobs
# Re-exported: tests/unit/test_scheduler_option_surface_gate.py imports it from here.
from uw_scan.worker.schedule.surface import (  # noqa: F401
    _should_schedule_option_surface_capture as _should_schedule_option_surface_capture,
)
# Re-exported: tests/integration/worker/test_data_gap_healer_scheduler.py imports
# it from here, and data_gap_* files belong to another lane (Wave 7b).
from uw_scan.worker.schedule.ops import (  # noqa: F401
    _should_schedule_data_gap_healer as _should_schedule_data_gap_healer,
)
from uw_scan.worker.schedule.macro import register as register_macro_jobs
from uw_scan.worker.schedule.regime import register as register_regime_jobs
from uw_scan.worker.schedule.scan_core import register as register_scan_core_jobs
from uw_scan.worker.schedule.ai import register as register_ai_jobs
from uw_scan.worker.schedule.fundamentals import register as register_fundamentals_jobs
from uw_scan.worker.schedule.roles import (
    _owns_global_daily_jobs,
    _ticker_shard_filter,
    _validate_worker_settings,
    _worker_groups,
)
from uw_scan.worker.schema_gate import wait_for_schema

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










    register_vrp_jobs(sched, settings)
    register_surface_jobs(sched, settings)
    register_ops_jobs(sched, settings)
    register_market_data_jobs(sched, settings)
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
