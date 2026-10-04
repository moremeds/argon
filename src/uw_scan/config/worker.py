"""Worker topology and core scan cadence (D6 concern group: worker)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class WorkerSettings(BaseModel):
    # Scheduler — consumed by uw_scan.worker.scheduler and uw_scan.reports.health_blocks.
    # (spot_refresh_seconds removed in Phase 7 — WS consumer is the spot writer now.)
    # Multiple crons so we hit: 04:00 ET premarket warm-up, 09:30 open,
    # every :00 and :30 during RTH active hours, and the 16:00 + 16:30
    # close-of-day batches. UW option data only updates during RTH, so
    # outside-RTH fires are intentionally sparse. The freshness gate below
    # still skips tickers that were refreshed within the last N hours.

    # full_scan_crons stays as the Pydantic default; not env-driven
    # because cron expressions contain spaces (CSV parsing is fragile).
    # Override by editing the Settings default if you need a different
    # schedule.
    full_scan_crons: list[str] = [
        "0 4 * * 0-4",  # premarket warm-up
        "30 9 * * 0-4",  # market open
        "0,30 10-15 * * 0-4",  # every :00 and :30 during RTH active
        "0 16 * * 0-4",  # 4pm close
        "30 16 * * 0-4",  # 4:30pm last scan
    ]
    # Skip tickers refreshed within this many hours during full_scan (full
    # watchlist pass). Fractional allowed: 0.33 ≈ 20-min freshness. With the
    # 30-min crons over RTH, 0.33h means each cron fires a real full-watchlist
    # refresh (~1,757 UW calls) — the fresh-cards "70k" setting. The budget
    # governor caps total spend, so an aggressive value degrades gracefully
    # (cold tickers skipped) rather than 429-storming. Hot tickers get a much
    # tighter cadence via the separate hot-subset job below.
    full_scan_stale_after_hours: Annotated[
        float, EnvVar("UW_SCAN_FULL_SCAN_STALE_HOURS")
    ] = 0.33
    ohlc_pull_cron: Annotated[str, EnvVar("UW_SCAN_OHLC_PULL_CRON")] = "30 17 * * 0-4"
    positioning_refresh_cron: Annotated[
        str, EnvVar("UW_SCAN_POSITIONING_REFRESH_CRON")
    ] = "0 6 * * 0-4"
    fundamentals_refresh_cron: Annotated[
        str, EnvVar("UW_SCAN_FUNDAMENTALS_REFRESH_CRON")
    ] = "0 19 * * 0-4"
    rth_tz: Annotated[str, EnvVar("UW_SCAN_RTH_TZ")] = "America/New_York"
    worker_role: Annotated[str, EnvVar("UW_SCAN_WORKER_ROLE")] = "all"
    worker_index: Annotated[int, EnvVar("UW_SCAN_WORKER_INDEX")] = 0
    worker_count: Annotated[int, EnvVar("UW_SCAN_WORKER_COUNT")] = 1
    uw_worker_count: Annotated[int, EnvVar("UW_SCAN_UW_WORKER_COUNT")] = 0
    massive_worker_count: Annotated[int, EnvVar("UW_SCAN_MASSIVE_WORKER_COUNT")] = 0
    ai_worker_count: Annotated[int, EnvVar("UW_SCAN_AI_WORKER_COUNT")] = 0
