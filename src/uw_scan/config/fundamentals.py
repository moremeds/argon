"""Fundamental PM lane jobs and crons (D6 concern group: fundamentals)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class FundamentalsSettings(BaseModel):
    # Fundamental lane recompute — routing + subscores + valuation anchors
    # (nightly 18:20 ET, massive-0). Zero UW/IB spend: Postgres + local parquet
    # only. Default ON because the alternative is a card that silently stops
    # updating, which is how it behaved before the job existed.
    fundamental_refresh_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED")
    ] = True
    # Statement ingest (monthly, uw-0). `fundamental_refresh` recomputes derived
    # layers nightly but deliberately does NOT pull filings, so without this job
    # the whole lane faithfully recomputes over a panel that stops advancing the
    # moment nobody runs the backfill script by hand — healthy-looking and stale,
    # the same failure shape as `fundamentals_refresh` never committing a row.
    # Monthly, not daily: statements are quarterly but filings arrive spread
    # across the calendar, so a monthly pass catches each name within weeks of
    # its filing at 4 UW calls per ticker (~1,800/month at the widened universe,
    # against a 120k/day budget).
    fundamental_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_ENABLED")
    ] = True
    fundamental_ingest_cron: Annotated[
        str, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_CRON")
    ] = "40 3 2 * *"
    fundamental_ingest_daily_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_ENABLED")
    ] = True
    fundamental_ingest_daily_cron: Annotated[
        str, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_CRON")
    ] = "20 4 * * *"
    fundamental_ingest_daily_lookback_days: Annotated[
        int, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_LOOKBACK_DAYS")
    ] = 3
    # How far AHEAD the same run reads the calendar. The lookback exists to find
    # statements that have landed; this exists so `earnings_calendar` holds rows
    # for prints that have NOT happened yet — the only thing the desk's "what
    # prints next" panel can read (`next_prints` filters `report_date >=`
    # today). Without it the backward-only scan leaves that panel structurally
    # empty forever, which reads as "nothing prints next" rather than "we never
    # asked". Costs 2 UW calls per forward day per run (~28/day at 14), against
    # a 120k/day budget. Two weeks covers the gap between runs many times over
    # while staying inside the horizon UW actually schedules.
    fundamental_ingest_daily_forward_days: Annotated[
        int, EnvVar("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_FORWARD_DAYS")
    ] = 14
    # Revenue-breakdown capture (monthly, uw-0). Default ON for the same reason
    # the job exists at all: it is an ACCRUAL job. The signal it feeds is
    # descriptive and does not pay, but if the provider's breakdown history
    # rolls, a month not captured is a quarter no future decision can use. A
    # default-off accrual job loses exactly what it was built to preserve.
    # One UW call per ticker, ~450/month at the widened universe.
    fundamental_concentration_capture_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED")
    ] = True
    company_sector_refresh_enabled: Annotated[
        bool, EnvVar("UW_SCAN_COMPANY_SECTOR_REFRESH_ENABLED")
    ] = True
    # 04:10 ET on the 3rd: a day clear of the statement ingest so the two
    # monthly uw-0 jobs never contend for the same per-minute ceiling, and an
    # hour clear of the 03:20/03:45/03:50 weekday jobs.
    fundamental_concentration_capture_cron: Annotated[
        str, EnvVar("UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_CRON")
    ] = "10 4 3 * *"
    #: 04:40 ET DAILY, not monthly like its uw-0 siblings, because this job is
    #: not an accrual — it fills a cache that is only ever missing rows. It asks
    #: names with no row, and after the first fill there are none, so every run
    #: from the second onward costs one indexed SELECT and zero UW calls. Daily
    #: buys three things a monthly cron cannot: the table is populated the
    #: morning after deploy instead of up to 31 days later; a name admitted by
    #: the monthly ingest is routed the next night rather than in the next
    #: cycle; and a provider failure retries tomorrow instead of next month.
    #: 04:40 keeps it 30 min clear of the breakdown capture on the 3rd and an
    #: hour clear of the 03:20/03:45/03:50 weekday jobs.
    company_sector_refresh_cron: Annotated[
        str, EnvVar("UW_SCAN_COMPANY_SECTOR_REFRESH_CRON")
    ] = "40 4 * * *"
    # Per-print earnings reaction history (spec §5-ii): calendar x daily_ohlc,
    # zero UW/IB spend, pinned to massive-0 at 19:40 ET daily (see schedule/fundamentals.py
    # `_should_schedule_earnings_reactions`). Default ON — same rationale as
    # the accrual jobs above: a night not computed is a print whose reaction
    # a future read can no longer distinguish from "not yet known" once the
    # calendar's lookback window scrolls past it.
    earnings_reactions_enabled: Annotated[
        bool, EnvVar("UW_SCAN_EARNINGS_REACTIONS_ENABLED")
    ] = True
    # Nightly implied-move snapshot (spec §5-iii): Brenner-Subrahmanyam
    # ATM-straddle approximation over option_surface_grid_daily, for names
    # with a known print in the next 21 calendar days. Zero UW/IB spend,
    # pinned to massive-0 at 20:45 ET weekdays -- after the 19:00/19:30
    # surface-capture jobs so tonight's grid is already written (see
    # schedule/fundamentals.py `_should_schedule_implied_move`). Default ON, same rationale
    # as earnings_reactions_enabled above: a night not snapshotted is a
    # forward-looking read the desk can never reconstruct after the fact.
    implied_move_snapshot_enabled: Annotated[
        bool, EnvVar("UW_SCAN_IMPLIED_MOVE_SNAPSHOT_ENABLED")
    ] = True
    # Delta-rail change events (Task 8, spec §5-iv): band_entry/band_exit,
    # implied_move_shift, coverage_change, bucket_flip through the discovery
    # gate. Zero UW/IB spend, pinned to massive-0 at 21:15 ET weekdays --
    # after implied_move_snapshot and fundamental_refresh so every source
    # table it reads is tonight's, not last night's (see schedule/fundamentals.py
    # `_should_schedule_fundamental_change_events`). Default ON, same
    # rationale as its siblings above: a night not derived is a change the
    # desk never learns of once the underlying row is superseded.
    fundamental_change_events_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTAL_CHANGE_EVENTS_ENABLED")
    ] = True
    # Desk matrix rollup (Task 12, spec §3c): per-name rev YoY + gross-margin
    # trajectory from the UW statement store, one row per (ticker,
    # period_end), so the chain x metric matrix reads it at request time with
    # zero recompute. Zero UW/IB spend, pinned to massive-0 at 21:30 ET daily
    # -- after fundamental_change_events (21:15) so this block's jobs stay
    # ordered even though they read unrelated tables (see schedule/fundamentals.py
    # `_should_schedule_fundamentals_desk_rollup`). Default ON, same
    # rationale as its siblings above: a night not rolled up is a period the
    # matrix cannot show until the next run recomputes it.
    fundamentals_desk_rollup_enabled: Annotated[
        bool, EnvVar("UW_SCAN_FUNDAMENTALS_DESK_ROLLUP_ENABLED")
    ] = True
