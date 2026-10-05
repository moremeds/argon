"""VRP family: the harvest markout, the research expansion, the tradable
iron-condor layer (candidates, paper open/mark, weekly backtest), the macro
short-vol signal, and the macro forward entry-capture marks plus its nightly
strike-grid cache.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (massive-0 primary, the entry-capture pin, the global
daily owner).
"""

from __future__ import annotations

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from uw_scan.config import Settings
from uw_scan.worker.db import repo_session as _repo
from uw_scan.worker.jobs.vrp_macro_entry import (
    vrp_macro_entry_grid_refresh,
    vrp_macro_entry_snapshot_once,
)
from uw_scan.worker.jobs.vrp_macro_signal import vrp_macro_signal_refresh
from uw_scan.worker.jobs.vrp_markout import vrp_markout_refresh
from uw_scan.worker.jobs.vrp_research_jobs import vrp_research_refresh
from uw_scan.worker.jobs.vrp_trading_jobs import (
    vrp_backtest_refresh,
    vrp_candidates_refresh,
    vrp_paper_mark,
    vrp_paper_open,
)
from uw_scan.worker.schedule.roles import (
    _is_primary_worker,
    _owns_global_daily_jobs,
    _pinned,
    _worker_groups,
)


def _should_schedule_vrp_macro_entry(settings: Settings) -> bool:
    """Exactly one process owns the 8x/day VRP entry-capture marks.

    Each mark drives UW chain calls + serial xenon/IB snapshots + DB upserts;
    scheduling on every index-0 process would duplicate the load (UW 429 risk,
    redundant IB lines). Pin to massive-0 (or 'all'), gated by the capture flag.
    """
    if not settings.vrp_macro_entry_capture_enabled:
        return False
    return _pinned(settings, "massive")


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

    def _vrp_markout_refresh() -> None:
        with _repo(settings) as repo:
            vrp_markout_refresh(repo=repo)

    def _vrp_macro_signal_refresh() -> None:
        with _repo(settings) as repo:
            vrp_macro_signal_refresh(repo=repo, settings=settings)

    def _vrp_macro_entry_rth() -> None:
        with _repo(settings) as repo:
            vrp_macro_entry_snapshot_once(repo, settings, session="rth", birth=True)

    def _vrp_macro_entry_eod() -> None:
        with _repo(settings) as repo:
            vrp_macro_entry_snapshot_once(repo, settings, session="eod", birth=True)

    def _vrp_macro_entry_postclose() -> None:
        with _repo(settings) as repo:
            vrp_macro_entry_snapshot_once(
                repo, settings, session="postclose", birth=False
            )

    def _vrp_macro_entry_grid_refresh() -> None:
        with _repo(settings) as repo:
            vrp_macro_entry_grid_refresh(repo, settings)

    def _vrp_research_refresh() -> None:
        with _repo(settings) as repo:
            vrp_research_refresh(repo=repo)

    def _vrp_candidates_refresh() -> None:
        with _repo(settings) as repo:
            vrp_candidates_refresh(repo=repo, settings=settings)

    def _vrp_paper_open() -> None:
        with _repo(settings) as repo:
            vrp_paper_open(repo=repo, settings=settings)

    def _vrp_paper_mark() -> None:
        with _repo(settings) as repo:
            vrp_paper_mark(repo=repo, settings=settings)

    def _vrp_backtest_refresh() -> None:
        with _repo(settings) as repo:
            vrp_backtest_refresh(repo=repo, settings=settings)

    if "massive" in groups:
        if _is_primary_worker(settings):
            # VRP harvest markout at 18:50 ET — aligned with the skew markout
            # (18:45). Pure compute over vrp_daily; idempotent. Scores whether
            # selling rich vol earns a reliable premium per bucket (Spec B).
            sched.add_job(
                _vrp_markout_refresh,
                CronTrigger.from_crontab("50 18 * * 0-4", timezone=settings.rth_tz),
                id="vrp_markout_refresh",
                name="VRP harvest markout verdict refresh",
                max_instances=1,
                coalesce=True,
            )
            # VRP research expansion at 19:10 ET — AFTER the 19:00 fundamentals
            # refresh (the filing_date earnings leg) so the calendar is fresh.
            # Pure compute over the warm store; idempotent (full-rewrite per run).
            sched.add_job(
                _vrp_research_refresh,
                CronTrigger.from_crontab("10 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_research_refresh",
                name="VRP research expansion (validation/sector/horizon/directional/ΔVRP)",
                max_instances=1,
                coalesce=True,
            )
            # VRP tradable layer (plan 2026-06-22) — all AFTER vrp_research (19:10)
            # so the SELLABLE-sector gate is fresh. massive-0 / primary, weekdays ET.
            sched.add_job(
                _vrp_candidates_refresh,
                CronTrigger.from_crontab("25 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_candidates_refresh",
                name="VRP iron-condor candidate emit",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_paper_open,
                CronTrigger.from_crontab("30 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_open",
                name="VRP paper-ledger open",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_paper_mark,
                CronTrigger.from_crontab("40 19 * * 0-4", timezone=settings.rth_tz),
                id="vrp_paper_mark",
                name="VRP paper-ledger mark/close",
                max_instances=1,
                coalesce=True,
            )
            sched.add_job(
                _vrp_backtest_refresh,
                CronTrigger.from_crontab("0 20 * * 6", timezone=settings.rth_tz),
                id="vrp_backtest_refresh",
                name="VRP condor backtest (weekly)",
                max_instances=1,
                coalesce=True,
            )

    if _should_schedule_vrp_macro_entry(settings):
        # VRP macro forward entry-capture: 8 marks/day (10:00-15:00 hourly RTH +
        # 15:55 EOD + 16:10 post-close ET). RTH/EOD marks birth today's auto cohort
        # (idempotent via the partial unique index — a missed 10:00 still births at
        # 11:00, the recorded born_at shows which mark won); post-close never births
        # (a post-close-only cohort can't be marked intraday and would skew the
        # stride dataset). max_instances=1 + coalesce so a slow mark can't stack.
        sched.add_job(
            _vrp_macro_entry_rth,
            CronTrigger.from_crontab("0 10-15 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_entry_rth",
            name="VRP macro entry-capture (RTH marks, birth)",
            max_instances=1,
            coalesce=True,
        )
        sched.add_job(
            _vrp_macro_entry_eod,
            CronTrigger.from_crontab("55 15 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_entry_eod",
            name="VRP macro entry-capture (EOD mark, last-resort birth)",
            max_instances=1,
            coalesce=True,
        )
        sched.add_job(
            _vrp_macro_entry_postclose,
            CronTrigger.from_crontab("10 16 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_entry_postclose",
            name="VRP macro entry-capture (post-close mark)",
            max_instances=1,
            coalesce=True,
        )
        # Nightly strike-grid cache @ 03:50 ET — fresh UW budget (after the 00:00
        # UTC reset, before the always-on stack exhausts it ~08:00 ET). Enumerates
        # SPX's listed strikes for the ~43-DTE expiry so the RTH birth reads the
        # cache and makes ZERO UW calls. Sits right after vrp_macro_signal_refresh
        # (03:45) in the nightly regime cluster.
        sched.add_job(
            _vrp_macro_entry_grid_refresh,
            CronTrigger.from_crontab("50 3 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_entry_grid_refresh",
            name="VRP macro entry-capture (nightly strike-grid cache)",
            max_instances=1,
            coalesce=True,
        )

    if _owns_global_daily_jobs(settings):
        # VRP macro short-vol signal at 03:45 ET — AFTER vol_index_lake_sync
        # (03:15) so it reads the freshest synced EOD vol. Computes the weekly
        # bull-put-spread readout + full-history backtest headline per name and
        # persists the daily snapshot. Pure DB-read math; idempotent.
        sched.add_job(
            _vrp_macro_signal_refresh,
            CronTrigger.from_crontab("45 3 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_signal_refresh",
            name="VRP macro short-vol signal refresh",
            max_instances=1,
            coalesce=True,
        )
