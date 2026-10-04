"""Pydantic-managed environment settings for the UW scanner."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr, model_validator

from uw_scan.config._env import (
    _env_bool,
    _load_dotenv,
    _parse_csv_env,
    _parse_int_csv_env,
    env_raw,
    read_env_fields,
)
from uw_scan.config.apex import ApexSettings
from uw_scan.config.db import DbSettings
from uw_scan.config.db_isolation import _enforce_db_isolation
from uw_scan.config.health import HealthSettings
from uw_scan.config.lake import LAKE_ROOT_FALLBACK, LakeSettings
from uw_scan.config.massive import MassiveSettings
from uw_scan.config.regime import RegimeSettings
from uw_scan.config.uw_api import UwApiSettings
from uw_scan.config.worker import WorkerSettings
from uw_scan.config.xenon import XenonSettings


class Settings(
    UwApiSettings,
    DbSettings,
    WorkerSettings,
    HealthSettings,
    MassiveSettings,
    XenonSettings,
    ApexSettings,
    RegimeSettings,
    LakeSettings,
):
    """Strongly-typed configuration. Raises on missing required fields."""

    # FRED official API. Required by the US rates mirror ingest path.
    fred_api_key: SecretStr | None = None
    # Free/delayed fed funds futures path source used by the rates dashboard.
    rates_policy_path_url: str = "https://www.frenzycap.com/fedwatch"
    # MC1 official macro evidence polling.  Off until the source probe and
    # release migration are explicitly enabled in an environment.
    macro_fomc_ingest_enabled: bool = False
    macro_sep_ingest_enabled: bool = False
    macro_sme_ingest_enabled: bool = False
    macro_market_shadow_ingest_enabled: bool = False
    # MC2 vintage-bearing series evidence + the domain-state engines that read it.
    # Off until an environment has a FRED key and has run the series backfill: a state
    # job with no evidence abstains, which is correct but not worth scheduling.
    macro_series_ingest_enabled: bool = False
    # MC3 rates market layer (supply + positioning) as evidence.  Off until an
    # environment has run the deep backfill: the engine's supply rule needs five new
    # issues per term before it can call a multi-quarter high, so a first scheduled run
    # on an empty store produces sub-states that correctly say UNKNOWN and nothing else.
    macro_market_layer_ingest_enabled: bool = False
    # MC3 gold evidence: GLD_CLOSE and GLD_HOLDINGS_OZ promoted from the warm store into
    # macro_observations.  Off by default like its siblings, and load-bearing rather than
    # cosmetic: the gold state's REQUIRED anchor is GLD_CLOSE, so with this off the gold
    # state job abstains every night -- correctly, but silently.
    macro_gold_ingest_enabled: bool = False
    macro_state_compute_enabled: bool = False
    # Dual-read: attach the policy/rates domain state to the legacy rates snapshot.
    # Separate from the compute flag so the state can accrue a history before the
    # surface that reads it changes shape.
    rates_snapshot_state_block_enabled: bool = False
    # WGC Goldhub authenticated downloads. Keep secrets in environment only.
    wgc_goldhub_cookie: SecretStr | None = None
    wgc_etf_flows_workbook_path: str = ""
    wgc_cb_reserves_workbook_path: str = ""
    # Trade Insights AI shared runner knobs (DeepSeek is the only provider)
    trade_insights_ai_max_output_bytes: int = 262144
    trade_insights_ai_poll_seconds: int = 3
    # Trade Insights AI DeepSeek provider
    trade_insights_ai_deepseek_enabled: bool = True
    trade_insights_ai_deepseek_model: str = ""
    trade_insights_ai_deepseek_timeout_seconds: float = 300.0
    trade_insights_ai_deepseek_worker_count: int = 2
    deepseek_api_key: SecretStr | None = None
    # Cockpit (6-dim matrix) — see docs/research/six-dimension-matrix/
    cockpit_tickers: list[str] = ["SPX", "SPY", "QQQ", "IWM"]
    cockpit_snapshot_cron: str = "30 16 * * 0-4"
    cockpit_target_dtes: list[int] = [0, 14, 30, 90]
    cockpit_oi_band_pct: Decimal = Decimal("0.10")
    cockpit_oi_max_dte: int = 7
    # Scanner (spec §10). Keep a wider weekend/overnight window so the page
    # does not go blank when no fresh scans have run in the last market session.
    scanner_freshness_hours: int = 72
    scanner_dp_lookback_days: int = 5
    scanner_dcf_min_premium_usd: Decimal = Decimal("500000")
    scanner_dcf_min_ask_side: Decimal = Decimal("0.80")
    scanner_dcf_max_moneyness: Decimal = Decimal("0.12")
    scanner_dcf_min_dte: int = 6
    # Discovery uses a looser bar than the watchlist DCF — it answers "worth a
    # look?" rather than "high-conviction trade." Moneyness/DTE/earnings stay
    # the same (those are about valid options, not conviction).
    scanner_discover_min_premium_usd: Decimal = Decimal("100000")
    scanner_discover_min_ask_side: Decimal = Decimal("0.65")
    # /api/scanner/discover serves a cached re-derivation when a successful
    # _DISCOVER run finished within this many seconds, so concurrent page loads
    # / auto-refresh don't burst the UW rate budget. Set to 0 to disable.
    scanner_discover_freshness_seconds: int = 30
    scanner_dp_min_print_premium_usd: Decimal = Decimal("1000000")
    scanner_dp_min_cluster_size: int = 3
    scanner_dp_price_spread_pct: Decimal = Decimal("0.5")
    scanner_eic_min_iv_rank: Decimal = Decimal("75.0")
    scanner_gex_pin_min_gamma: Decimal = Decimal("1.0")
    scanner_liquidity_min_option_volume: int = 1000
    scanner_earnings_window_days: int = 14
    # Discovery edge-quality scoring (radon parity). Weights must sum to 100.
    scanner_edge_quality_weight_dp_strength: Decimal = Decimal("30")
    scanner_edge_quality_weight_dp_sustained: Decimal = Decimal("20")
    scanner_edge_quality_weight_confluence: Decimal = Decimal("20")
    scanner_edge_quality_weight_vol_oi: Decimal = Decimal("15")
    scanner_edge_quality_weight_sweeps: Decimal = Decimal("15")
    scanner_discover_dp_top_n: int = 50
    scanner_discover_dp_lookback_days: int = 3
    scanner_discover_dp_sleep_ms: int = (
        0  # optional inter-DP-fetch throttle (rate guard)
    )
    scanner_discover_alerts_limit: int = 200
    scanner_discover_scan_enabled: bool = True
    # Offset off the top-of-hour so discovery doesn't contend with full_scan
    # (cron `0 5-16`). Covers ~09:15–16:45 ET (RTH + post-close settle).
    scanner_discover_scan_cron: str = "15,45 9-16 * * 0-4"
    # Regime / GEX scanner (port from xenon — ships GEX live; CRI/VCG pending).
    # Expanded from the SPX/SPY/TLT core to the index family + M7 so the
    # append-only intraday GEX/DEX series (gex_snapshots) covers the names that
    # actually move dealer positioning intraday. UW serves GEX history only at
    # EOD, so the intraday evolution is buildable *only* by live capture —
    # spend research budget here. Override with UW_SCAN_GEX_SCAN_TICKERS.
    gex_scan_tickers: list[str] = [
        "SPX",
        "SPY",
        "QQQ",
        "IWM",
        "TLT",
        "NVDA",
        "AAPL",
        "MSFT",
        "AMZN",
        "META",
        "GOOGL",
        "TSLA",
    ]
    # Split intraday GEX cadence: tight during RTH (genuinely new data each
    # tick), slow off-hours (US options don't trade → GEX is ~static). Weekends
    # are skipped entirely by the trigger. Research pool under the governor.
    gex_scan_rth_interval_minutes: int = 2
    gex_scan_offhours_interval_minutes: int = 15
    # ---- UW daily budget governor (shared 120k account counter) ----
    # The account-wide daily counter (resets 00:00 UTC / 20:00 ET). Live jobs
    # (full_scan, hot subset) get priority up to `live_ceiling`; research jobs
    # (intraday GEX, tide, backfill) yield first at `research_ceiling`; the
    # `total_guard` keeps a safety margin below the hard `daily_limit`.
    uw_budget_governor_enabled: bool = True
    uw_daily_limit: int = 120000
    uw_live_daily_ceiling: int = 80000
    uw_research_daily_ceiling: int = 30000
    uw_total_daily_guard: int = 105000
    # ---- Hot-subset full_scan (UI-toggled fast lane) ----
    # Tickers flagged `hot` in the watchlist get a tight-freshness intraday
    # refresh on this cron. `hot_stale_minutes` < cron interval so every fire
    # does real work; `hot_max_tickers` is the soft cap the UI meter shows (the
    # governor enforces it — flagging more than this just means the overflow
    # waits for budget).
    full_scan_hot_enabled: bool = True
    full_scan_hot_cron: str = "*/5 9-16 * * 0-4"
    full_scan_hot_stale_minutes: int = 4
    full_scan_hot_max_tickers: int = 25
    # Market-tide capture (UW /market/market-tide, ~81 calls/day at 5-min RTH).
    # Kill switch + the index whose live spot overlays the premium chart.
    market_tide_capture_enabled: bool = True
    market_tide_spot_ticker: str = "SPY"
    # Top-net-impact capture (UW /market/top-net-impact, ~32 calls/day at
    # 15-min RTH). Kill switch for the market-wide net-premium ranking.
    top_net_impact_capture_enabled: bool = True
    # Option surface capture (durable full-chain IV/greeks grid) + IB-vs-UW IV canary
    option_surface_capture_enabled: bool = True
    option_surface_backfill_days: int = 4
    option_surface_iv_canary_enabled: bool = True
    option_surface_iv_canary_warn_threshold: float = 0.02
    # Nightly full-chain capture for a research cohort (uw_scan.research_universe).
    # Default-on is safe: the job self-gates on the cohort being seeded, so an
    # un-seeded deployment spends nothing.
    option_surface_research_capture_enabled: bool = True
    option_surface_research_cohort: str = "liquid_sector_balanced_v1"
    # Nightly catch-up that fills the cohort's *history* (the capture above only
    # writes tonight). Self-terminating: once the ~180-day window is complete it
    # finds no gaps and spends nothing, so it needs no switching off. The cap is
    # per night — ~7,950 calls of work at 1,500/night finishes in ~6 nights while
    # staying well inside the 30k research pool.
    option_surface_research_catchup_enabled: bool = True
    option_surface_research_catchup_max_calls: int = 1500
    # Nightly technicals refresh (apex daily bars -> technical_daily, massive-0 18:40 ET).
    technicals_refresh_enabled: bool = True
    # Live technicals coverage (WS-spot splice -> technical_live cache, massive-0).
    technical_live_enabled: bool = False
    technical_live_scan_interval_minutes: int = 5
    technical_live_quote_max_age_seconds: int = 900
    # Theta Harvester short-strangle scan (nightly 19:45 ET, massive-0).
    # Zero UW budget — pure warm-store compute.
    theta_harvester_enabled: bool = True
    # Sector RS + breadth (nightly 21:30 ET Mon–Fri, massive-0). Zero UW spend:
    # apex bars plus a daily_ohlc fallback for SPY and the 11 SPDR ETFs.
    # Default OFF: flip on the mini after scripts/backfill/sector_rs_backfill.py
    # lands (spec 2026-09-26 §5).
    sector_rs_enabled: bool = False
    # UW historical-alpha nightly capture (5 datasets, uw-0). Master kill switch.
    uw_alpha_capture_enabled: bool = False
    # SPX 1-5d density cone (nightly 03:30 ET, massive-0). Display-only v13 port —
    # zero UW/IB spend; reads vol_index_daily only.
    spx_density_enabled: bool = False
    # Economic-release calendar capture + FRED actual fill (daily, uw-0,
    # 1 UW call/day). See reports/macro_releases.py.
    macro_release_calendar_enabled: bool = False
    # Fundamental lane recompute — routing + subscores + valuation anchors
    # (nightly 18:20 ET, massive-0). Zero UW/IB spend: Postgres + local parquet
    # only. Default ON because the alternative is a card that silently stops
    # updating, which is how it behaved before the job existed.
    fundamental_refresh_enabled: bool = True
    # Statement ingest (monthly, uw-0). `fundamental_refresh` recomputes derived
    # layers nightly but deliberately does NOT pull filings, so without this job
    # the whole lane faithfully recomputes over a panel that stops advancing the
    # moment nobody runs the backfill script by hand — healthy-looking and stale,
    # the same failure shape as `fundamentals_refresh` never committing a row.
    # Monthly, not daily: statements are quarterly but filings arrive spread
    # across the calendar, so a monthly pass catches each name within weeks of
    # its filing at 4 UW calls per ticker (~1,800/month at the widened universe,
    # against a 120k/day budget).
    fundamental_ingest_enabled: bool = True
    fundamental_ingest_cron: str = "40 3 2 * *"
    fundamental_ingest_daily_enabled: bool = True
    fundamental_ingest_daily_cron: str = "20 4 * * *"
    fundamental_ingest_daily_lookback_days: int = 3
    # How far AHEAD the same run reads the calendar. The lookback exists to find
    # statements that have landed; this exists so `earnings_calendar` holds rows
    # for prints that have NOT happened yet — the only thing the desk's "what
    # prints next" panel can read (`next_prints` filters `report_date >=`
    # today). Without it the backward-only scan leaves that panel structurally
    # empty forever, which reads as "nothing prints next" rather than "we never
    # asked". Costs 2 UW calls per forward day per run (~28/day at 14), against
    # a 120k/day budget. Two weeks covers the gap between runs many times over
    # while staying inside the horizon UW actually schedules.
    fundamental_ingest_daily_forward_days: int = 14
    # Revenue-breakdown capture (monthly, uw-0). Default ON for the same reason
    # the job exists at all: it is an ACCRUAL job. The signal it feeds is
    # descriptive and does not pay, but if the provider's breakdown history
    # rolls, a month not captured is a quarter no future decision can use. A
    # default-off accrual job loses exactly what it was built to preserve.
    # One UW call per ticker, ~450/month at the widened universe.
    fundamental_concentration_capture_enabled: bool = True
    company_sector_refresh_enabled: bool = True
    # 04:10 ET on the 3rd: a day clear of the statement ingest so the two
    # monthly uw-0 jobs never contend for the same per-minute ceiling, and an
    # hour clear of the 03:20/03:45/03:50 weekday jobs.
    fundamental_concentration_capture_cron: str = "10 4 3 * *"
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
    company_sector_refresh_cron: str = "40 4 * * *"
    # Per-print earnings reaction history (spec §5-ii): calendar x daily_ohlc,
    # zero UW/IB spend, pinned to massive-0 at 19:40 ET daily (see schedule/fundamentals.py
    # `_should_schedule_earnings_reactions`). Default ON — same rationale as
    # the accrual jobs above: a night not computed is a print whose reaction
    # a future read can no longer distinguish from "not yet known" once the
    # calendar's lookback window scrolls past it.
    earnings_reactions_enabled: bool = True
    # Nightly implied-move snapshot (spec §5-iii): Brenner-Subrahmanyam
    # ATM-straddle approximation over option_surface_grid_daily, for names
    # with a known print in the next 21 calendar days. Zero UW/IB spend,
    # pinned to massive-0 at 20:45 ET weekdays -- after the 19:00/19:30
    # surface-capture jobs so tonight's grid is already written (see
    # schedule/fundamentals.py `_should_schedule_implied_move`). Default ON, same rationale
    # as earnings_reactions_enabled above: a night not snapshotted is a
    # forward-looking read the desk can never reconstruct after the fact.
    implied_move_snapshot_enabled: bool = True
    # Delta-rail change events (Task 8, spec §5-iv): band_entry/band_exit,
    # implied_move_shift, coverage_change, bucket_flip through the discovery
    # gate. Zero UW/IB spend, pinned to massive-0 at 21:15 ET weekdays --
    # after implied_move_snapshot and fundamental_refresh so every source
    # table it reads is tonight's, not last night's (see schedule/fundamentals.py
    # `_should_schedule_fundamental_change_events`). Default ON, same
    # rationale as its siblings above: a night not derived is a change the
    # desk never learns of once the underlying row is superseded.
    fundamental_change_events_enabled: bool = True
    # Desk matrix rollup (Task 12, spec §3c): per-name rev YoY + gross-margin
    # trajectory from the UW statement store, one row per (ticker,
    # period_end), so the chain x metric matrix reads it at request time with
    # zero recompute. Zero UW/IB spend, pinned to massive-0 at 21:30 ET daily
    # -- after fundamental_change_events (21:15) so this block's jobs stay
    # ordered even though they read unrelated tables (see schedule/fundamentals.py
    # `_should_schedule_fundamentals_desk_rollup`). Default ON, same
    # rationale as its siblings above: a night not rolled up is a period the
    # matrix cannot show until the next run recomputes it.
    fundamentals_desk_rollup_enabled: bool = True
    # Nightly data gap healer (8pm ET, after UW quota reset). Only UW is capped.
    data_gap_healer_enabled: bool = False
    data_gap_healer_cron_et: str = (
        "0 20 * * 0-5"  # 20:00 ET Mon-Sat (APScheduler Mon=0)
    )
    data_gap_healer_datasets: str = ""  # empty = all healable datasets
    data_gap_healer_start: str = "2026-01-01"
    data_gap_healer_max_uw_calls: int = 20000
    # The UW budget day runs 20:00 ET -> 20:00 ET and the healer fires AT 20:00, so a
    # run bills the day that FOLLOWS it. Friday's and Saturday's runs therefore bill to
    # Saturday and Sunday -- no session, so the live pool needs nothing and the healer
    # can take most of the account. Sunday is deliberately NOT scheduled: that run would
    # bill Monday, a full trading day. Measured 2026-08 on UW's own counter: weekday
    # burn 64k-82k against a 105k guard, weekends ~1k.
    data_gap_healer_max_uw_calls_weekend: int = 90000
    # No single dataset may take more than this share of one night's UW cap.
    # execute_run groups items by dataset and runs each group to completion
    # against one shared budget, so the first big UW spender in REGISTRY drains
    # the whole night and every dataset behind it records skipped_budget. 0.4
    # lets a large backfill make real progress (~7 nights for a 4.2k-item
    # surface backlog at 12k/night) without blocking everything else for the
    # week. Set to 1.0 to restore the old drain-it-all behaviour.
    data_gap_healer_dataset_share: float = 0.4
    # Consecutive nightly no_data verdicts before the scope is auto-caveated.
    # The audit is a set-difference against the real table, so a date the
    # provider genuinely cannot serve reappears as a fresh item and is
    # re-attempted at full cost every night, forever. 0 disables.
    data_gap_healer_no_data_caveat_after: int = 3
    # Freshness-monitor autoheal: a same-night "second chance" trigger for a
    # table the 20:00 ET gap-healer left frozen (budget exhaustion / a
    # transient failure) -- NOT a substitute for the nightly job, which
    # already audits+heals every registered dataset. Off by default; a
    # circuit breaker stops re-triggering a table frozen N nights running
    # (a real, unfixable block -- missing credential, licensed data source)
    # so it doesn't burn budget forever on something a heal can't solve.
    data_freshness_autoheal_enabled: bool = False
    data_freshness_autoheal_circuit_breaker_nights: int = 3
    data_freshness_autoheal_max_uw_calls: int = 500

    # --- VRP tradable iron-condor + backtest (plan 2026-06-22) ----------------
    # hold is in TRADING days to stay unit-consistent with the harvest measurement
    # (HORIZON=20). t_years = hold_days / 252 feeds Black-Scholes.
    vrp_hold_days: int = 20
    vrp_short_delta: float = 0.16  # short put/call strike target |delta|
    vrp_wing_delta: float = 0.08  # long wing strike target |delta|
    vrp_risk_free_rate: float = 0.04  # flat r for BS; tiny effect at short DTE
    vrp_cost_per_contract: float = 0.65  # commission per leg per side
    vrp_slippage_frac: float = 0.01  # half-spread as fraction of leg mid
    vrp_slippage_min: float = 0.05  # half-spread floor per leg (price points)
    vrp_cost_round_trip: bool = True  # charge open + close (conservative)

    # --- VRP macro forward entry-capture (plan 2026-06-24) --------------------
    vrp_macro_entry_capture_enabled: bool = True
    vrp_macro_entry_taper_calendar_days: int = 30  # > this → EOD-only marks
    vrp_macro_entry_quote_timeout_s: float = 8.0  # per-leg xenon/IB snapshot timeout
    vrp_macro_entry_mark_budget_s: float = (
        600.0  # per-mark wall-clock; overrun → UW-only
    )

    @property
    def ws_spot_enabled(self) -> bool:
        """True when ANY WS feed owns intraday spot.

        Use this (not ``massive_ws_enabled``) wherever the question is "does
        the WS pipeline own spot writes" — e.g. the scheduler's
        ``preserve_spot`` guard. A xenon-only deployment must still stop UW
        scan jobs from overwriting WS-written spot.
        """
        return self.massive_ws_enabled or self.xenon_ws_enabled

    def scanner_edge_quality_weights(self) -> dict[str, Decimal]:
        return {
            "dp_strength": self.scanner_edge_quality_weight_dp_strength,
            "dp_sustained": self.scanner_edge_quality_weight_dp_sustained,
            "confluence": self.scanner_edge_quality_weight_confluence,
            "vol_oi": self.scanner_edge_quality_weight_vol_oi,
            "sweeps": self.scanner_edge_quality_weight_sweeps,
        }

    @model_validator(mode="after")
    def _check_edge_quality_weights(self) -> "Settings":
        total = sum(self.scanner_edge_quality_weights().values(), Decimal("0"))
        if total != Decimal("100"):
            raise ValueError(
                f"scanner edge-quality weights must sum to 100, got {total}"
            )
        return self

    @model_validator(mode="after")
    def _check_vrp(self) -> "Settings":
        if not (0.0 < self.vrp_wing_delta < self.vrp_short_delta < 0.5):
            raise ValueError("require 0 < vrp_wing_delta < vrp_short_delta < 0.5")
        if self.vrp_hold_days <= 0:
            raise ValueError("vrp_hold_days must be positive")
        return self

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        """Load Settings from process env, auto-loading .env at repo root.

        When called without an explicit env_path, loads .env.local first, then
        .env, both from repo root. .env.local is a gitignored per-machine
        override — used to point the MacBook at the mini's DB host without
        editing the committed .env. Because _load_dotenv only sets keys not
        already present in os.environ, .env.local wins on conflicts.
        """
        if env_path is not None:
            _load_dotenv(env_path)
        else:
            repo_root = Path(__file__).resolve().parents[3]
            _load_dotenv(repo_root / ".env.local")
            _load_dotenv(repo_root / ".env")

        api_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "UW_SCAN_API_KEY is not set. Add it to .env or export it before running."
            )

        # Before any field is parsed, as before the env table: a wrong-tier pair is
        # refused even when another value would also fail to parse.
        _enforce_db_isolation(env_raw(cls, "db_host"), env_raw(cls, "db_name"))

        env = read_env_fields(cls)
        # Lake roots without their own env var fall back under the warehouse root
        # (LAKE_ROOT_FALLBACK), resolved here at call time as before the env table.
        mw_lake_root = env.setdefault(
            "market_warehouse_lake_root", Path.home() / "market-warehouse" / "data-lake"
        )
        for field, sub in LAKE_ROOT_FALLBACK.items():
            env.setdefault(field, mw_lake_root / sub)

        return cls(
            api_key=SecretStr(api_key),
            **env,
            fred_api_key=(
                SecretStr(_fred_key)
                if (_fred_key := os.environ.get("FRED_API_KEY", "").strip())
                else None
            ),
            rates_policy_path_url=os.environ.get(
                "RATES_POLICY_PATH_URL", "https://www.frenzycap.com/fedwatch"
            ).strip()
            or "https://www.frenzycap.com/fedwatch",
            macro_fomc_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_FOMC_INGEST_ENABLED", False
            ),
            macro_sep_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_SEP_INGEST_ENABLED", False
            ),
            macro_sme_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_SME_INGEST_ENABLED", False
            ),
            macro_market_shadow_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_MARKET_SHADOW_INGEST_ENABLED", False
            ),
            macro_series_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_SERIES_INGEST_ENABLED", False
            ),
            macro_market_layer_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_MARKET_LAYER_INGEST_ENABLED", False
            ),
            macro_gold_ingest_enabled=_env_bool(
                "UW_SCAN_MACRO_GOLD_INGEST_ENABLED", False
            ),
            macro_state_compute_enabled=_env_bool(
                "UW_SCAN_MACRO_STATE_COMPUTE_ENABLED", False
            ),
            rates_snapshot_state_block_enabled=_env_bool(
                "UW_SCAN_RATES_SNAPSHOT_STATE_BLOCK_ENABLED", False
            ),
            wgc_goldhub_cookie=(
                SecretStr(_wgc_cookie)
                if (_wgc_cookie := os.environ.get("WGC_GOLDHUB_COOKIE", "").strip())
                else None
            ),
            wgc_etf_flows_workbook_path=os.environ.get(
                "WGC_ETF_FLOWS_WORKBOOK_PATH", ""
            ).strip(),
            wgc_cb_reserves_workbook_path=os.environ.get(
                "WGC_CB_RESERVES_WORKBOOK_PATH", ""
            ).strip(),
            trade_insights_ai_max_output_bytes=int(
                os.environ.get("TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES", "262144")
            ),
            trade_insights_ai_poll_seconds=int(
                os.environ.get("TRADE_INSIGHTS_AI_POLL_SECONDS", "3")
            ),
            trade_insights_ai_deepseek_enabled=_env_bool(
                "TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED", True
            ),
            trade_insights_ai_deepseek_model=os.environ.get(
                "TRADE_INSIGHTS_AI_DEEPSEEK_MODEL", ""
            ),
            trade_insights_ai_deepseek_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS", "300.0")
            ),
            trade_insights_ai_deepseek_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT", "2")
            ),
            deepseek_api_key=(
                SecretStr(_ds_key)
                if (_ds_key := os.environ.get("DEEPSEEK_API_KEY", "").strip())
                else None
            ),
            cockpit_tickers=_parse_csv_env(
                "COCKPIT_TICKERS", default=["SPX", "SPY", "QQQ", "IWM"]
            ),
            cockpit_snapshot_cron=os.environ.get(
                "COCKPIT_SNAPSHOT_CRON", "30 16 * * 0-4"
            ),
            cockpit_target_dtes=_parse_int_csv_env(
                "COCKPIT_TARGET_DTES", default=[0, 14, 30, 90]
            ),
            cockpit_oi_band_pct=Decimal(os.environ.get("COCKPIT_OI_BAND_PCT", "0.10")),
            cockpit_oi_max_dte=int(os.environ.get("COCKPIT_OI_MAX_DTE", "7")),
            scanner_freshness_hours=int(
                os.environ.get("SCANNER_FRESHNESS_HOURS", "72")
            ),
            scanner_dp_lookback_days=int(
                os.environ.get("SCANNER_DP_LOOKBACK_DAYS", "5")
            ),
            scanner_dcf_min_premium_usd=Decimal(
                os.environ.get("SCANNER_DCF_MIN_PREMIUM_USD", "500000")
            ),
            scanner_dcf_min_ask_side=Decimal(
                os.environ.get("SCANNER_DCF_MIN_ASK_SIDE", "0.80")
            ),
            scanner_dcf_max_moneyness=Decimal(
                os.environ.get("SCANNER_DCF_MAX_MONEYNESS", "0.12")
            ),
            scanner_dcf_min_dte=int(os.environ.get("SCANNER_DCF_MIN_DTE", "6")),
            scanner_discover_min_premium_usd=Decimal(
                os.environ.get("SCANNER_DISCOVER_MIN_PREMIUM_USD", "100000")
            ),
            scanner_discover_min_ask_side=Decimal(
                os.environ.get("SCANNER_DISCOVER_MIN_ASK_SIDE", "0.65")
            ),
            scanner_discover_freshness_seconds=int(
                os.environ.get("SCANNER_DISCOVER_FRESHNESS_SECONDS", "30")
            ),
            scanner_dp_min_print_premium_usd=Decimal(
                os.environ.get("SCANNER_DP_MIN_PRINT_PREMIUM_USD", "1000000")
            ),
            scanner_dp_min_cluster_size=int(
                os.environ.get("SCANNER_DP_MIN_CLUSTER_SIZE", "3")
            ),
            scanner_dp_price_spread_pct=Decimal(
                os.environ.get("SCANNER_DP_PRICE_SPREAD_PCT", "0.5")
            ),
            scanner_eic_min_iv_rank=Decimal(
                os.environ.get("SCANNER_EIC_MIN_IV_RANK", "75.0")
            ),
            scanner_gex_pin_min_gamma=Decimal(
                os.environ.get("SCANNER_GEX_PIN_MIN_GAMMA", "1.0")
            ),
            scanner_liquidity_min_option_volume=int(
                os.environ.get("SCANNER_LIQUIDITY_MIN_OPTION_VOLUME", "1000")
            ),
            scanner_earnings_window_days=int(
                os.environ.get("SCANNER_EARNINGS_WINDOW_DAYS", "14")
            ),
            scanner_edge_quality_weight_dp_strength=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_DP_STRENGTH", "30")
            ),
            scanner_edge_quality_weight_dp_sustained=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_DP_SUSTAINED", "20")
            ),
            scanner_edge_quality_weight_confluence=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_CONFLUENCE", "20")
            ),
            scanner_edge_quality_weight_vol_oi=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_VOL_OI", "15")
            ),
            scanner_edge_quality_weight_sweeps=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_SWEEPS", "15")
            ),
            scanner_discover_dp_top_n=int(
                os.environ.get("SCANNER_DISCOVER_DP_TOP_N", "50")
            ),
            scanner_discover_dp_lookback_days=int(
                os.environ.get("SCANNER_DISCOVER_DP_LOOKBACK_DAYS", "3")
            ),
            scanner_discover_dp_sleep_ms=int(
                os.environ.get("SCANNER_DISCOVER_DP_SLEEP_MS", "0")
            ),
            scanner_discover_alerts_limit=int(
                os.environ.get("SCANNER_DISCOVER_ALERTS_LIMIT", "200")
            ),
            scanner_discover_scan_enabled=os.environ.get(
                "SCANNER_DISCOVER_SCAN_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            scanner_discover_scan_cron=os.environ.get(
                "SCANNER_DISCOVER_SCAN_CRON", "15,45 9-16 * * 0-4"
            ),
            gex_scan_tickers=_parse_csv_env(
                "GEX_SCAN_TICKERS",
                default=[
                    "SPX",
                    "SPY",
                    "QQQ",
                    "IWM",
                    "TLT",
                    "NVDA",
                    "AAPL",
                    "MSFT",
                    "AMZN",
                    "META",
                    "GOOGL",
                    "TSLA",
                ],
            ),
            gex_scan_rth_interval_minutes=int(
                os.environ.get("GEX_SCAN_RTH_INTERVAL_MINUTES", "2")
            ),
            gex_scan_offhours_interval_minutes=int(
                os.environ.get("GEX_SCAN_OFFHOURS_INTERVAL_MINUTES", "15")
            ),
            uw_budget_governor_enabled=os.environ.get(
                "UW_BUDGET_GOVERNOR_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            uw_daily_limit=int(os.environ.get("UW_DAILY_LIMIT", "120000")),
            uw_live_daily_ceiling=int(os.environ.get("UW_LIVE_DAILY_CEILING", "80000")),
            uw_research_daily_ceiling=int(
                os.environ.get("UW_RESEARCH_DAILY_CEILING", "30000")
            ),
            uw_total_daily_guard=int(os.environ.get("UW_TOTAL_DAILY_GUARD", "105000")),
            full_scan_hot_enabled=os.environ.get(
                "FULL_SCAN_HOT_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            full_scan_hot_cron=os.environ.get("FULL_SCAN_HOT_CRON", "*/5 9-16 * * 0-4"),
            full_scan_hot_stale_minutes=int(
                os.environ.get("FULL_SCAN_HOT_STALE_MINUTES", "4")
            ),
            full_scan_hot_max_tickers=int(
                os.environ.get("FULL_SCAN_HOT_MAX_TICKERS", "25")
            ),
            market_tide_capture_enabled=os.environ.get(
                "MARKET_TIDE_CAPTURE_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            market_tide_spot_ticker=os.environ.get(
                "MARKET_TIDE_SPOT_TICKER", "SPY"
            ).upper(),
            top_net_impact_capture_enabled=os.environ.get(
                "TOP_NET_IMPACT_CAPTURE_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            option_surface_capture_enabled=_env_bool(
                "OPTION_SURFACE_CAPTURE_ENABLED", True
            ),
            option_surface_backfill_days=int(
                os.environ.get("OPTION_SURFACE_BACKFILL_DAYS", "4")
            ),
            option_surface_iv_canary_enabled=_env_bool(
                "OPTION_SURFACE_IV_CANARY_ENABLED", True
            ),
            option_surface_research_capture_enabled=_env_bool(
                "OPTION_SURFACE_RESEARCH_CAPTURE_ENABLED", True
            ),
            option_surface_research_cohort=os.environ.get(
                "OPTION_SURFACE_RESEARCH_COHORT", "liquid_sector_balanced_v1"
            ),
            option_surface_research_catchup_enabled=_env_bool(
                "OPTION_SURFACE_RESEARCH_CATCHUP_ENABLED", True
            ),
            option_surface_research_catchup_max_calls=int(
                os.environ.get("OPTION_SURFACE_RESEARCH_CATCHUP_MAX_CALLS", "1500")
            ),
            option_surface_iv_canary_warn_threshold=float(
                os.environ.get("OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD", "0.02")
            ),
            technicals_refresh_enabled=_env_bool(
                "UW_SCAN_TECHNICALS_REFRESH_ENABLED", True
            ),
            technical_live_enabled=_env_bool("UW_SCAN_TECHNICAL_LIVE_ENABLED", False),
            technical_live_scan_interval_minutes=int(
                os.environ.get("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES", "5")
            ),
            technical_live_quote_max_age_seconds=int(
                os.environ.get("TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS", "900")
            ),
            # All four env vars deliberately carry the UW_SCAN_ prefix (newest
            # precedent: UW_SCAN_TECHNICAL_LIVE_ENABLED) — one convention for
            # the whole feature, no mixed-prefix mis-sets on the mini.
            theta_harvester_enabled=_env_bool("UW_SCAN_THETA_HARVESTER_ENABLED", True),
            sector_rs_enabled=_env_bool("UW_SCAN_SECTOR_RS_ENABLED", False),
            uw_alpha_capture_enabled=_env_bool(
                "UW_SCAN_UW_ALPHA_CAPTURE_ENABLED", False
            ),
            spx_density_enabled=_env_bool("UW_SCAN_SPX_DENSITY_ENABLED", False),
            macro_release_calendar_enabled=_env_bool(
                "UW_SCAN_MACRO_RELEASE_CALENDAR_ENABLED", False
            ),
            fundamental_refresh_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED", True
            ),
            fundamental_ingest_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTAL_INGEST_ENABLED", True
            ),
            fundamental_ingest_cron=os.environ.get(
                "UW_SCAN_FUNDAMENTAL_INGEST_CRON", "40 3 2 * *"
            ),
            fundamental_ingest_daily_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTAL_INGEST_DAILY_ENABLED", True
            ),
            fundamental_ingest_daily_cron=os.environ.get(
                "UW_SCAN_FUNDAMENTAL_INGEST_DAILY_CRON", "20 4 * * *"
            ),
            fundamental_ingest_daily_lookback_days=int(
                os.environ.get("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_LOOKBACK_DAYS", "3")
            ),
            fundamental_ingest_daily_forward_days=int(
                os.environ.get("UW_SCAN_FUNDAMENTAL_INGEST_DAILY_FORWARD_DAYS", "14")
            ),
            fundamental_concentration_capture_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED", True
            ),
            fundamental_concentration_capture_cron=os.environ.get(
                "UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_CRON", "10 4 3 * *"
            ),
            company_sector_refresh_enabled=_env_bool(
                "UW_SCAN_COMPANY_SECTOR_REFRESH_ENABLED", True
            ),
            company_sector_refresh_cron=os.environ.get(
                "UW_SCAN_COMPANY_SECTOR_REFRESH_CRON", "40 4 * * *"
            ),
            earnings_reactions_enabled=_env_bool(
                "UW_SCAN_EARNINGS_REACTIONS_ENABLED", True
            ),
            implied_move_snapshot_enabled=_env_bool(
                "UW_SCAN_IMPLIED_MOVE_SNAPSHOT_ENABLED", True
            ),
            fundamental_change_events_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTAL_CHANGE_EVENTS_ENABLED", True
            ),
            fundamentals_desk_rollup_enabled=_env_bool(
                "UW_SCAN_FUNDAMENTALS_DESK_ROLLUP_ENABLED", True
            ),
            data_gap_healer_enabled=_env_bool("DATA_GAP_HEALER_ENABLED", False),
            data_gap_healer_cron_et=os.environ.get(
                "DATA_GAP_HEALER_CRON_ET", "0 20 * * 0-5"
            ),
            data_gap_healer_datasets=os.environ.get("DATA_GAP_HEALER_DATASETS", ""),
            data_gap_healer_start=os.environ.get("DATA_GAP_HEALER_START", "2026-01-01"),
            data_gap_healer_max_uw_calls=int(
                os.environ.get("DATA_GAP_HEALER_MAX_UW_CALLS", "20000")
            ),
            data_gap_healer_max_uw_calls_weekend=int(
                os.environ.get("DATA_GAP_HEALER_MAX_UW_CALLS_WEEKEND", "90000")
            ),
            data_gap_healer_dataset_share=float(
                os.environ.get("DATA_GAP_HEALER_DATASET_SHARE", "0.4")
            ),
            data_gap_healer_no_data_caveat_after=int(
                os.environ.get("DATA_GAP_HEALER_NO_DATA_CAVEAT_AFTER", "3")
            ),
            data_freshness_autoheal_enabled=_env_bool(
                "DATA_FRESHNESS_AUTOHEAL_ENABLED", False
            ),
            data_freshness_autoheal_circuit_breaker_nights=int(
                os.environ.get("DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS", "3")
            ),
            data_freshness_autoheal_max_uw_calls=int(
                os.environ.get("DATA_FRESHNESS_AUTOHEAL_MAX_UW_CALLS", "500")
            ),
            vrp_hold_days=int(os.environ.get("UW_SCAN_VRP_HOLD_DAYS", "20")),
            vrp_short_delta=float(os.environ.get("UW_SCAN_VRP_SHORT_DELTA", "0.16")),
            vrp_wing_delta=float(os.environ.get("UW_SCAN_VRP_WING_DELTA", "0.08")),
            vrp_risk_free_rate=float(
                os.environ.get("UW_SCAN_VRP_RISK_FREE_RATE", "0.04")
            ),
            vrp_cost_per_contract=float(
                os.environ.get("UW_SCAN_VRP_COST_PER_CONTRACT", "0.65")
            ),
            vrp_slippage_frac=float(
                os.environ.get("UW_SCAN_VRP_SLIPPAGE_FRAC", "0.01")
            ),
            vrp_slippage_min=float(os.environ.get("UW_SCAN_VRP_SLIPPAGE_MIN", "0.05")),
            vrp_cost_round_trip=_env_bool("UW_SCAN_VRP_COST_ROUND_TRIP", True),
            vrp_macro_entry_capture_enabled=_env_bool(
                "UW_SCAN_VRP_MACRO_ENTRY_CAPTURE_ENABLED", True
            ),
            vrp_macro_entry_taper_calendar_days=int(
                os.environ.get("UW_SCAN_VRP_MACRO_ENTRY_TAPER_CALENDAR_DAYS", "30")
            ),
            vrp_macro_entry_quote_timeout_s=float(
                os.environ.get("UW_SCAN_VRP_MACRO_ENTRY_QUOTE_TIMEOUT_S", "8.0")
            ),
            vrp_macro_entry_mark_budget_s=float(
                os.environ.get("UW_SCAN_VRP_MACRO_ENTRY_MARK_BUDGET_S", "600.0")
            ),
        )
