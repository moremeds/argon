"""Pydantic-managed environment settings for the UW scanner."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, model_validator

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(name: str, *, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _parse_int_csv_env(name: str, *, default: list[int]) -> list[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader. We deliberately do not depend on python-dotenv.

    Reads KEY=VALUE lines, ignores comments and blanks, only sets keys that are
    not already present in the process environment. This makes `set -a; source .env`
    take precedence over our own loader.
    """
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        logger.exception("failed to read .env file %s: %s", env_path, repr(exc))


# Host → set of legal db names. Refuses to start on (host, db_name) mismatch
# so a stray .env on the wrong machine cannot write into the wrong tier.
#   100.66.147.98 = Mac mini Tailscale (prodlike): option_wizard for the live
#                   data feed; option_wizard_test allowed too because
#                   integration tests on the macbook (with .env.local active)
#                   reach the mini's test DB via migrate.sh.
#   127.0.0.1     = local Postgres on macbook / CI: option_wizard_local for
#                   dev work, option_wizard_test for pytest (wiped by
#                   integration fixtures via DROP SCHEMA CASCADE).
# Override with UW_SCAN_ALLOW_DB_MISMATCH=1 for one-off ad-hoc scripts
# (e.g. backfilling from R2 into a scratch DB on the macbook).
_HOST_DB_RULES: dict[str, frozenset[str]] = {
    "100.66.147.98": frozenset({"option_wizard", "option_wizard_test"}),
    "127.0.0.1": frozenset({"option_wizard_local", "option_wizard_test"}),
    "localhost": frozenset({"option_wizard_local", "option_wizard_test"}),
    # Docker: containers reach host-native Postgres via host.docker.internal.
    # On the mini that host DB is prodlike `option_wizard`; local/CI Docker
    # smoke runs target `option_wizard_local`; integration tests use the test
    # tier. Keeping this rule meaningful means the container `.env` must NOT
    # carry UW_SCAN_ALLOW_DB_MISMATCH=1 (which bypasses ALL isolation checks) —
    # the clean container path is a legal pair here, no override.
    "host.docker.internal": frozenset(
        {"option_wizard", "option_wizard_local", "option_wizard_test"}
    ),
}


def _enforce_db_isolation(db_host: str, db_name: str) -> None:
    allowed = _HOST_DB_RULES.get(db_host)
    if allowed is None or db_name in allowed:
        return
    # pytest-xdist gives each worker its own per-worker test DB
    # (option_wizard_test_gw0, option_wizard_test_gw1, …). These are the same
    # isolated test tier as option_wizard_test — wiped per fixture, never prod — so
    # allow the prefix wherever the bare test DB is allowed.
    if "option_wizard_test" in allowed and db_name.startswith("option_wizard_test_"):
        return
    if _env_bool("UW_SCAN_ALLOW_DB_MISMATCH"):
        logger.warning(
            "DB isolation override active: host=%s db_name=%s "
            "(UW_SCAN_ALLOW_DB_MISMATCH=1)",
            db_host,
            db_name,
        )
        return
    raise RuntimeError(
        f"Refusing to start: UW_SCAN_DB_HOST={db_host!r} is not allowed to "
        f"target UW_SCAN_DB_NAME={db_name!r}. Allowed on this host: "
        f"{sorted(allowed)}. Set UW_SCAN_ALLOW_DB_MISMATCH=1 to override "
        "(one-off scripts only)."
    )


class Settings(BaseModel):
    """Strongly-typed configuration. Raises on missing required fields."""

    api_key: SecretStr = Field(...)
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "option_wizard_local"
    db_schema: str = "uw_scan"
    db_user: str = "argon_app"
    db_password: SecretStr = SecretStr("")
    max_requests_per_minute: int = 110
    request_timeout_seconds: float = 30.0
    base_url: str = "https://api.unusualwhales.com"
    # Scheduler — consumed by uw_scan.worker.scheduler and uw_scan.api.routers.health.
    # (spot_refresh_seconds removed in Phase 7 — WS consumer is the spot writer now.)
    # Multiple crons so we hit: 04:00 ET premarket warm-up, 09:30 open,
    # every :00 and :30 during RTH active hours, and the 16:00 + 16:30
    # close-of-day batches. UW option data only updates during RTH, so
    # outside-RTH fires are intentionally sparse. The freshness gate below
    # still skips tickers that were refreshed within the last N hours.
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
    full_scan_stale_after_hours: float = 0.33
    # Grace period for the health "expected full scans missed" liveness alarm.
    # Decoupled from card freshness on purpose: the budget governor may
    # deliberately throttle/skip full_scan under UW-budget pressure, which ages
    # last_scan without meaning the scheduler is dead. Keep this loose (~1h) so
    # the alarm signals a genuinely stuck worker, not a governed skip.
    health_full_scan_missed_grace_hours: float = 1.0
    # Sliding-window for the per-table coverage check on tables that only
    # update once per day (cockpit + nightly vol rollup). Anything below
    # 24h would always alert on those tables; 26h gives a small grace gap.
    record_health_daily_window_hours: int = 26
    ohlc_pull_cron: str = "30 17 * * 0-4"
    positioning_refresh_cron: str = "0 6 * * 0-4"
    fundamentals_refresh_cron: str = "0 19 * * 0-4"
    rth_tz: str = "America/New_York"
    worker_role: str = "all"
    worker_index: int = 0
    worker_count: int = 1
    uw_worker_count: int = 0
    massive_worker_count: int = 0
    ai_worker_count: int = 0
    # OHLC provider (massive.com)
    massive_api_key: SecretStr | None = None
    massive_base_url: str = "https://api.massive.com"
    # massive.com WebSocket consumer (replaces REST per-ticker spot polling).
    # Default URL points at the DELAYED tier (matches the dev plan and the
    # current massive subscription). Real-time tier upgrade: set
    # MASSIVE_WS_URL=wss://socket.massive.com/stocks in the environment.
    massive_ws_enabled: bool = False
    massive_ws_url: str = "wss://delayed.massive.com/stocks"
    massive_ws_channel: str = "A"  # A=per-second, AM=per-minute, T=trades
    massive_ws_flush_interval_seconds: float = 1.0
    massive_ws_watchlist_poll_interval_seconds: float = 30.0
    massive_ws_reconnect_backoff_initial_seconds: float = 1.0
    massive_ws_reconnect_backoff_max_seconds: float = 60.0
    massive_ws_heartbeat_stale_after_seconds: float = 120.0
    # xenon IB realtime WS (primary live spot feed when enabled; the massive
    # WS above becomes the automatic fallback). Served by the sibling xenon
    # project's ib_realtime_server.js — streams 24h whenever IB Gateway is
    # connected, not just the massive 04:00-20:00 ET window. Port may drift
    # if 8765 is taken — the server writes the actual port to
    # xenon_ws_port_file; discovery only applies when the URL host is local.
    xenon_ws_enabled: bool = False
    xenon_ws_url: str = "ws://127.0.0.1:8765"
    xenon_ws_port_file: str = "/tmp/xenon-ib-realtime.json"
    # After a xenon failure, stay on massive for this long before re-probing.
    xenon_ws_retry_primary_seconds: float = 300.0
    # In-session silence threshold before failing over (0 disables watchdog).
    xenon_ws_quiet_failover_seconds: float = 120.0
    # FRED official API. Required by the US rates mirror ingest path.
    fred_api_key: SecretStr | None = None
    # Free/delayed fed funds futures path source used by the rates dashboard.
    rates_policy_path_url: str = "https://www.frenzycap.com/fedwatch"
    # MC1 official macro evidence polling.  Off until the source probe and
    # release migration are explicitly enabled in an environment.
    macro_fomc_ingest_enabled: bool = False
    macro_sep_ingest_enabled: bool = False
    macro_sme_ingest_enabled: bool = False
    # WGC Goldhub authenticated downloads. Keep secrets in environment only.
    wgc_goldhub_cookie: SecretStr | None = None
    wgc_etf_flows_workbook_path: str = ""
    wgc_cb_reserves_workbook_path: str = ""
    # Trade Insights V1.5 local Codex analysis
    trade_insights_ai_enabled: bool = True
    trade_insights_ai_model: str = ""
    trade_insights_ai_timeout_seconds: float = 300.0
    trade_insights_ai_max_output_bytes: int = 262144
    trade_insights_ai_poll_seconds: int = 3
    # Ops alert sink — one webhook (Discord/Pushover-compatible JSON POST).
    # Empty = no-op (send_alert returns False without a call).
    ops_alert_webhook_url: str = ""
    # Trade Insights AI Claude provider (alongside Codex)
    trade_insights_ai_claude_enabled: bool = True
    trade_insights_ai_claude_model: str = ""
    trade_insights_ai_claude_timeout_seconds: float = 300.0
    # Per-provider worker counts (informational — read by /api/health to render
    # the per-provider health block). Defaults match scripts/dev.sh.
    trade_insights_ai_codex_worker_count: int = 2
    trade_insights_ai_claude_worker_count: int = 2
    # Trade Insights AI DeepSeek provider (alongside Codex + Claude)
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
    # Regime live feed — symbols the WS consumer always subscribes IN ADDITION
    # to the watchlist (indexes route via XENON_INDEX_SYMBOLS → CBOE; HYG is a
    # plain ETF symbol). Drives the live CRI/VCG compute + 5-min snapshots.
    regime_ws_symbols: list[str] = ["VIX", "VVIX", "VIX3M", "COR1M", "SPX", "HYG"]
    # Cadence of the regime_live_scan job (basis='live' snapshot writes).
    regime_live_scan_interval_minutes: int = 5
    # Quotes older than this are ignored by the live compute (stale feed →
    # the live endpoints fall back to the latest basis='eod' snapshot).
    regime_live_quote_max_age_seconds: int = 900
    # Parquet lake root for CBOE vol indices and SPX daily OHLC.
    # Maintained by the peer ``market-data-warehouse`` project. Symbol subdirs
    # are named ``symbol=<TICKER>`` with a ``1d.parquet`` payload inside.
    lake_vol_index_root: Path = Field(
        default=Path.home()
        / "market-warehouse/data-lake/bronze/asset_class=volatility",
        description=(
            "Local parquet lake root for CBOE vol indices and SPX daily OHLC. "
            "Symbol subdirs are named symbol=<TICKER>."
        ),
    )
    # Parquet lake root for equity-asset credit-proxy ETFs (HYG, JNK, LQD),
    # used by the VCG scanner. Same layout as the vol-index lake.
    lake_credit_etf_root: Path = Field(
        default=Path.home() / "market-warehouse/data-lake/bronze/asset_class=equity",
        description=(
            "Local parquet lake root for credit-proxy ETF daily OHLC "
            "(HYG/JNK/LQD). Symbol subdirs are named symbol=<TICKER>."
        ),
    )
    # Parquet lake root for FX dailies. Same layout as the vol-index lake;
    # `USD<CCY>` holds <CCY> per one USD. Used to translate foreign filers'
    # statements before any valuation anchor is computed — see
    # `fundamentals/fx.py` for why an unconverted band is worse than no band.
    lake_fx_root: Path = Field(
        default=Path.home() / "market-warehouse/data-lake/bronze/asset_class=fx",
        description=(
            "Local parquet lake root for FX daily rates. Symbol subdirs are "
            "named symbol=USD<CCY> and hold <CCY> per one USD."
        ),
    )
    # Root of the whole market-warehouse lake (parent of bronze/silver/gold).
    # Distinct from the two asset-class roots above, which point at specific
    # bronze partitions. Read by reports/vrp_macro_drawdown.py.
    market_warehouse_lake_root: Path = Field(
        default=Path.home() / "market-warehouse" / "data-lake",
        description=(
            "Root of the market-warehouse parquet lake (contains bronze/). "
            "Set MARKET_WAREHOUSE_LAKE=/lake in containers."
        ),
    )
    # Credit-proxy ETFs synced from the equity lake into vol_index_daily.
    # The VCG scanner reads from this list; the first entry is the default
    # proxy unless overridden by the API caller.
    credit_etf_symbols: list[str] = ["HYG", "JNK", "LQD"]
    # Cloudflare R2 parquet lake — primary source for EOD/backfill reads per
    # the 2026-05-25 standing rule (see docs/research/regime/closure-2026-05-24.md
    # §4 and the [[feedback-r2-primary-for-eod-backfill]] memory). All four core
    # fields must be set for R2 reads to engage; if any is None, the resolver
    # falls back to the local mirror at lake_vol_index_root / lake_credit_etf_root.
    # R2_ENDPOINT_OVERRIDE is optional — defaults to
    # https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com.
    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_endpoint_override: str | None = None
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
    # UW historical-alpha nightly capture (5 datasets, uw-0). Master kill switch.
    uw_alpha_capture_enabled: bool = False
    # SPX 1-5d density cone (nightly 03:30 ET, massive-0). Display-only v13 port —
    # zero UW/IB spend; reads vol_index_daily only.
    spx_density_enabled: bool = False
    # Chanlun Phase B lifecycle engine (nightly 03:10 ET Tue-Sat, massive-0).
    chanlun_lifecycle_enabled: bool = False
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
    chanlun_anchor_tol: float = 0.0
    chanlun_stale_sessions: int = 20
    # Empty by DESIGN (2026-07-15 walk-forward probe): all 4 candidate
    # categories (vertex/divergence/3B/3S) failed the survival gate in both
    # ticker-halves (~8-17% actual vs >=70% required) — most sub-level-
    # confirmed marks are superseded within 1-2 sessions rather than surviving
    # to native confirmation. See docs/research/2026-07-14-chanlun-signal-
    # lifecycle/phaseb_probe/summary.md for the full gate table.
    chanlun_promotable_categories: str = ""
    # Nightly data gap healer (8pm ET, after UW quota reset). Only UW is capped.
    data_gap_healer_enabled: bool = False
    data_gap_healer_cron_et: str = (
        "0 20 * * 0-4"  # 20:00 ET Mon-Fri (APScheduler Mon=0)
    )
    data_gap_healer_datasets: str = ""  # empty = all healable datasets
    data_gap_healer_start: str = "2026-01-01"
    data_gap_healer_max_uw_calls: int = 20000
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
    # xenon read-only query API (IB option greeks via GET /options/greeks).
    # Default = the mini's authenticated localhost port (verified listening 2026-06-24;
    # the old :8421 was dead → the surface canary silently no-op'd). Key REQUIRED even
    # on localhost. MacBook dev points over Tailscale: http://100.66.147.98:8321.
    xenon_query_api_url: str = "http://127.0.0.1:8321"
    xenon_query_api_key: SecretStr | None = None

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
            repo_root = Path(__file__).resolve().parents[2]
            _load_dotenv(repo_root / ".env.local")
            _load_dotenv(repo_root / ".env")

        api_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "UW_SCAN_API_KEY is not set. Add it to .env or export it before running."
            )

        db_host = os.environ.get("UW_SCAN_DB_HOST", "127.0.0.1")
        db_name = os.environ.get("UW_SCAN_DB_NAME", "option_wizard_local")
        _enforce_db_isolation(db_host, db_name)

        return cls(
            api_key=SecretStr(api_key),
            db_host=db_host,
            db_port=int(os.environ.get("UW_SCAN_DB_PORT", "5432")),
            db_name=db_name,
            db_schema=os.environ.get("UW_SCAN_DB_SCHEMA", "uw_scan"),
            db_user=os.environ.get("UW_SCAN_DB_USER", "") or "argon_app",
            db_password=SecretStr(os.environ.get("UW_SCAN_DB_PASSWORD", "")),
            max_requests_per_minute=int(
                os.environ.get("UW_SCAN_MAX_REQUESTS_PER_MINUTE", "110")
            ),
            request_timeout_seconds=float(
                os.environ.get("UW_SCAN_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            base_url=os.environ.get(
                "UW_SCAN_BASE_URL", "https://api.unusualwhales.com"
            ),
            ops_alert_webhook_url=os.environ.get("UW_SCAN_OPS_ALERT_WEBHOOK_URL", ""),
            # full_scan_crons stays as the Pydantic default; not env-driven
            # because cron expressions contain spaces (CSV parsing is fragile).
            # Override by editing the Settings default if you need a different
            # schedule.
            full_scan_stale_after_hours=float(
                os.environ.get("UW_SCAN_FULL_SCAN_STALE_HOURS", "0.33")
            ),
            health_full_scan_missed_grace_hours=float(
                os.environ.get("UW_SCAN_HEALTH_FULL_SCAN_MISSED_GRACE_HOURS", "1.0")
            ),
            ohlc_pull_cron=os.environ.get("UW_SCAN_OHLC_PULL_CRON", "30 17 * * 0-4"),
            positioning_refresh_cron=os.environ.get(
                "UW_SCAN_POSITIONING_REFRESH_CRON", "0 6 * * 0-4"
            ),
            fundamentals_refresh_cron=os.environ.get(
                "UW_SCAN_FUNDAMENTALS_REFRESH_CRON", "0 19 * * 0-4"
            ),
            rth_tz=os.environ.get("UW_SCAN_RTH_TZ", "America/New_York"),
            worker_role=os.environ.get("UW_SCAN_WORKER_ROLE", "all"),
            worker_index=int(os.environ.get("UW_SCAN_WORKER_INDEX", "0")),
            worker_count=int(os.environ.get("UW_SCAN_WORKER_COUNT", "1")),
            uw_worker_count=int(os.environ.get("UW_SCAN_UW_WORKER_COUNT", "0")),
            massive_worker_count=int(
                os.environ.get("UW_SCAN_MASSIVE_WORKER_COUNT", "0")
            ),
            ai_worker_count=int(os.environ.get("UW_SCAN_AI_WORKER_COUNT", "0")),
            # SecretStr("") is truthy and not None — would silently allow the
            # scheduler to instantiate a Massive client with a blank bearer and
            # generate a stream of 401s. Coerce blank to None before wrapping.
            massive_api_key=(
                SecretStr(_mkey)
                if (_mkey := os.environ.get("MASSIVE_API_KEY", "").strip())
                else None
            ),
            massive_base_url=os.environ.get(
                "MASSIVE_BASE_URL", "https://api.massive.com"
            ),
            massive_ws_enabled=os.environ.get("MASSIVE_WS_ENABLED", "false").lower()
            == "true",
            massive_ws_url=os.environ.get(
                "MASSIVE_WS_URL", "wss://delayed.massive.com/stocks"
            ),
            massive_ws_channel=os.environ.get("MASSIVE_WS_CHANNEL", "A"),
            massive_ws_flush_interval_seconds=float(
                os.environ.get("MASSIVE_WS_FLUSH_INTERVAL_SECONDS", "1.0")
            ),
            massive_ws_watchlist_poll_interval_seconds=float(
                os.environ.get("MASSIVE_WS_WATCHLIST_POLL_INTERVAL_SECONDS", "30.0")
            ),
            massive_ws_reconnect_backoff_initial_seconds=float(
                os.environ.get("MASSIVE_WS_RECONNECT_BACKOFF_INITIAL_SECONDS", "1.0")
            ),
            massive_ws_reconnect_backoff_max_seconds=float(
                os.environ.get("MASSIVE_WS_RECONNECT_BACKOFF_MAX_SECONDS", "60.0")
            ),
            massive_ws_heartbeat_stale_after_seconds=float(
                os.environ.get("MASSIVE_WS_HEARTBEAT_STALE_AFTER_SECONDS", "120.0")
            ),
            xenon_ws_enabled=os.environ.get("XENON_WS_ENABLED", "false").lower()
            == "true",
            xenon_ws_url=os.environ.get("XENON_WS_URL", "ws://127.0.0.1:8765"),
            xenon_ws_port_file=os.environ.get(
                "XENON_WS_PORT_FILE", "/tmp/xenon-ib-realtime.json"
            ),
            xenon_ws_retry_primary_seconds=float(
                os.environ.get("XENON_WS_RETRY_PRIMARY_SECONDS", "300")
            ),
            xenon_ws_quiet_failover_seconds=float(
                os.environ.get("XENON_WS_QUIET_FAILOVER_SECONDS", "120")
            ),
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
            trade_insights_ai_enabled=_env_bool("TRADE_INSIGHTS_AI_ENABLED", True),
            trade_insights_ai_model=os.environ.get("TRADE_INSIGHTS_AI_MODEL", ""),
            trade_insights_ai_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_TIMEOUT_SECONDS", "300.0")
            ),
            trade_insights_ai_max_output_bytes=int(
                os.environ.get("TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES", "262144")
            ),
            trade_insights_ai_poll_seconds=int(
                os.environ.get("TRADE_INSIGHTS_AI_POLL_SECONDS", "3")
            ),
            trade_insights_ai_claude_enabled=_env_bool(
                "TRADE_INSIGHTS_AI_CLAUDE_ENABLED", True
            ),
            trade_insights_ai_claude_model=os.environ.get(
                "TRADE_INSIGHTS_AI_CLAUDE_MODEL", ""
            ),
            trade_insights_ai_claude_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS", "300.0")
            ),
            trade_insights_ai_codex_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT", "2")
            ),
            trade_insights_ai_claude_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT", "2")
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
            regime_ws_symbols=_parse_csv_env(
                "REGIME_WS_SYMBOLS",
                default=["VIX", "VVIX", "VIX3M", "COR1M", "SPX", "HYG"],
            ),
            regime_live_scan_interval_minutes=int(
                os.environ.get("REGIME_LIVE_SCAN_INTERVAL_MINUTES", "5")
            ),
            regime_live_quote_max_age_seconds=int(
                os.environ.get("REGIME_LIVE_QUOTE_MAX_AGE_SECONDS", "900")
            ),
            # Parquet-lake roots are env-overridable so deployments without
            # the user's home-dir layout (containers, CI) can point at their
            # own mount. Blank/unset → fall back to the field-level defaults.
            lake_vol_index_root=(
                Path(_lake_vol)
                if (_lake_vol := os.environ.get("LAKE_VOL_INDEX_ROOT", "").strip())
                else Path.home()
                / "market-warehouse/data-lake/bronze/asset_class=volatility"
            ),
            lake_credit_etf_root=(
                Path(_lake_credit)
                if (_lake_credit := os.environ.get("LAKE_CREDIT_ETF_ROOT", "").strip())
                else Path.home()
                / "market-warehouse/data-lake/bronze/asset_class=equity"
            ),
            market_warehouse_lake_root=(
                Path(_mw_lake)
                if (_mw_lake := os.environ.get("MARKET_WAREHOUSE_LAKE", "").strip())
                else Path.home() / "market-warehouse" / "data-lake"
            ),
            credit_etf_symbols=_parse_csv_env(
                "CREDIT_ETF_SYMBOLS", default=["HYG", "JNK", "LQD"]
            ),
            r2_account_id=(
                _r2_acc
                if (_r2_acc := os.environ.get("R2_ACCOUNT_ID", "").strip())
                else None
            ),
            r2_access_key_id=(
                SecretStr(_r2_key)
                if (_r2_key := os.environ.get("R2_ACCESS_KEY_ID", "").strip())
                else None
            ),
            r2_secret_access_key=(
                SecretStr(_r2_sec)
                if (_r2_sec := os.environ.get("R2_SECRET_ACCESS_KEY", "").strip())
                else None
            ),
            r2_bucket=(
                _r2_bkt
                if (_r2_bkt := os.environ.get("R2_BUCKET", "").strip())
                else None
            ),
            r2_endpoint_override=(
                _r2_ep
                if (_r2_ep := os.environ.get("R2_ENDPOINT_OVERRIDE", "").strip())
                else None
            ),
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
            uw_alpha_capture_enabled=_env_bool(
                "UW_SCAN_UW_ALPHA_CAPTURE_ENABLED", False
            ),
            spx_density_enabled=_env_bool("UW_SCAN_SPX_DENSITY_ENABLED", False),
            chanlun_lifecycle_enabled=_env_bool(
                "UW_SCAN_CHANLUN_LIFECYCLE_ENABLED", False
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
            chanlun_anchor_tol=float(
                os.environ.get("UW_SCAN_CHANLUN_ANCHOR_TOL", "0.0")
            ),
            chanlun_stale_sessions=int(
                os.environ.get("UW_SCAN_CHANLUN_STALE_SESSIONS", "20")
            ),
            chanlun_promotable_categories=os.environ.get(
                "UW_SCAN_CHANLUN_PROMOTABLE_CATEGORIES", ""
            ),
            data_gap_healer_enabled=_env_bool("DATA_GAP_HEALER_ENABLED", False),
            data_gap_healer_cron_et=os.environ.get(
                "DATA_GAP_HEALER_CRON_ET", "0 20 * * 0-4"
            ),
            data_gap_healer_datasets=os.environ.get("DATA_GAP_HEALER_DATASETS", ""),
            data_gap_healer_start=os.environ.get("DATA_GAP_HEALER_START", "2026-01-01"),
            data_gap_healer_max_uw_calls=int(
                os.environ.get("DATA_GAP_HEALER_MAX_UW_CALLS", "20000")
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
            xenon_query_api_url=os.environ.get(
                "XENON_QUERY_API_URL", "http://127.0.0.1:8321"
            ),
            xenon_query_api_key=(
                SecretStr(v)
                if (v := os.environ.get("XENON_QUERY_API_KEY", "").strip())
                else None
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

    def db_dsn(self) -> str:
        """Return a libpq-style DSN. Password omitted when blank (peer/trust auth)."""
        pw = self.db_password.get_secret_value()
        password_clause = f" password={pw}" if pw else ""
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user}{password_clause}"
        )
