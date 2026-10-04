"""AI tick family: the Trade Insights AI analysis polls -- the legacy any-provider
pool and the provider-pinned deepseek pool.

Registered by ``scheduler.main()`` on every process; each block keeps the exact
guard it had in ``main()`` (its ai role group plus that provider's kill switch).
"""

from __future__ import annotations

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.config import Settings
from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick
from uw_scan.worker.schedule.roles import _worker_groups


def register(sched: BaseScheduler, settings: Settings) -> None:
    groups = _worker_groups(settings)

    def _trade_insights_ai_tick_any() -> None:
        trade_insights_ai_tick(settings, provider_filter=None)

    def _trade_insights_ai_tick_deepseek() -> None:
        trade_insights_ai_tick(settings, provider_filter="deepseek")

    # Legacy single-pool role (claims any provider's row).
    if "ai" in groups and settings.trade_insights_ai_deepseek_enabled:
        sched.add_job(
            _trade_insights_ai_tick_any,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick",
            name="Trade Insights AI analysis poll (any provider)",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )
    # Provider-pinned deepseek pool.
    if "ai-deepseek" in groups and settings.trade_insights_ai_deepseek_enabled:
        sched.add_job(
            _trade_insights_ai_tick_deepseek,
            IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
            id="trade_insights_ai_tick_deepseek",
            name="Trade Insights AI analysis poll (deepseek)",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
        )
