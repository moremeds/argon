"""UW daily budget governor and the hot full_scan lane (D6 concern group: uw_budget)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar, _true_1_yes


class UwBudgetSettings(BaseModel):
    # ---- UW daily budget governor (shared 120k account counter) ----
    # The account-wide daily counter (resets 00:00 UTC / 20:00 ET). Live jobs
    # (full_scan, hot subset) get priority up to `live_ceiling`; research jobs
    # (intraday GEX, tide, backfill) yield first at `research_ceiling`; the
    # `total_guard` keeps a safety margin below the hard `daily_limit`.
    uw_budget_governor_enabled: Annotated[
        bool, EnvVar("UW_BUDGET_GOVERNOR_ENABLED", parse=_true_1_yes)
    ] = True
    uw_daily_limit: Annotated[int, EnvVar("UW_DAILY_LIMIT")] = 120000
    uw_live_daily_ceiling: Annotated[int, EnvVar("UW_LIVE_DAILY_CEILING")] = 80000
    uw_research_daily_ceiling: Annotated[int, EnvVar("UW_RESEARCH_DAILY_CEILING")] = (
        30000
    )
    uw_total_daily_guard: Annotated[int, EnvVar("UW_TOTAL_DAILY_GUARD")] = 105000
    # ---- Hot-subset full_scan (UI-toggled fast lane) ----
    # Tickers flagged `hot` in the watchlist get a tight-freshness intraday
    # refresh on this cron. `hot_stale_minutes` < cron interval so every fire
    # does real work; `hot_max_tickers` is the soft cap the UI meter shows (the
    # governor enforces it — flagging more than this just means the overflow
    # waits for budget).
    full_scan_hot_enabled: Annotated[
        bool, EnvVar("FULL_SCAN_HOT_ENABLED", parse=_true_1_yes)
    ] = True
    full_scan_hot_cron: Annotated[str, EnvVar("FULL_SCAN_HOT_CRON")] = (
        "*/5 9-16 * * 0-4"
    )
    full_scan_hot_stale_minutes: Annotated[
        int, EnvVar("FULL_SCAN_HOT_STALE_MINUTES")
    ] = 4
    full_scan_hot_max_tickers: Annotated[int, EnvVar("FULL_SCAN_HOT_MAX_TICKERS")] = 25
