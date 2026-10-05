"""Research job flags: theta harvester, sector RS, UW alpha capture, SPX density (D6 concern group: research)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class ResearchSettings(BaseModel):
    # Theta Harvester short-strangle scan (nightly 19:45 ET, massive-0).
    # Zero UW budget — pure warm-store compute.
    # All four env vars deliberately carry the UW_SCAN_ prefix (newest
    # precedent: UW_SCAN_TECHNICAL_LIVE_ENABLED) — one convention for
    # the whole feature, no mixed-prefix mis-sets on the mini.
    theta_harvester_enabled: Annotated[
        bool, EnvVar("UW_SCAN_THETA_HARVESTER_ENABLED")
    ] = True
    # Sector RS + breadth (nightly 21:30 ET Mon–Fri, massive-0). Zero UW spend:
    # apex bars plus a daily_ohlc fallback for SPY and the 11 SPDR ETFs.
    # Default OFF: flip on the mini after scripts/backfill/sector_rs_backfill.py
    # lands (spec 2026-09-26 §5).
    sector_rs_enabled: Annotated[bool, EnvVar("UW_SCAN_SECTOR_RS_ENABLED")] = False
    # UW historical-alpha nightly capture (5 datasets, uw-0). Master kill switch.
    uw_alpha_capture_enabled: Annotated[
        bool, EnvVar("UW_SCAN_UW_ALPHA_CAPTURE_ENABLED")
    ] = False
    # Dark/lit print history backfill (daily 22:30 ET, uw-0). Re-pages every
    # active-watchlist ticker-day the one-page capture cut at 500 prints, oldest
    # first. Research pool: it also stops on research_budget_ok and the total
    # guard. Per-UW-budget-day (UTC) call caps; UTC Saturday/Sunday are the
    # Friday- and Saturday-evening ET runs.
    dark_lit_backfill_enabled: Annotated[
        bool, EnvVar("UW_SCAN_DARK_LIT_BACKFILL_ENABLED")
    ] = False
    dark_lit_backfill_weekday_max_calls: Annotated[
        int, EnvVar("UW_SCAN_DARK_LIT_BACKFILL_WEEKDAY_MAX_CALLS")
    ] = 15000
    dark_lit_backfill_saturday_max_calls: Annotated[
        int, EnvVar("UW_SCAN_DARK_LIT_BACKFILL_SATURDAY_MAX_CALLS")
    ] = 60000
    dark_lit_backfill_sunday_max_calls: Annotated[
        int, EnvVar("UW_SCAN_DARK_LIT_BACKFILL_SUNDAY_MAX_CALLS")
    ] = 60000
    # SPX 1-5d density cone (nightly 03:30 ET, massive-0). Display-only v13 port —
    # zero UW/IB spend; reads vol_index_daily only.
    spx_density_enabled: Annotated[bool, EnvVar("UW_SCAN_SPX_DENSITY_ENABLED")] = False
