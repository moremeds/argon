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
}


def _enforce_db_isolation(db_host: str, db_name: str) -> None:
    allowed = _HOST_DB_RULES.get(db_host)
    if allowed is None or db_name in allowed:
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
    # Skip tickers refreshed within this many hours during full_scan. With a
    # 30-min cron over the 6h RTH window, 1h freshness gives ~6 batches/day
    # which uses ~85% of the 20k/day UW operator budget while keeping data
    # at most 1h stale. Coverage alert (8h window, 90% tickers) needs <=4.
    full_scan_stale_after_hours: int = 1
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
    # Regime / GEX scanner (port from xenon — ships GEX live; CRI/VCG pending)
    gex_scan_tickers: list[str] = ["SPX", "SPY", "TLT"]
    gex_scan_interval_minutes: int = 5
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
            # full_scan_crons stays as the Pydantic default; not env-driven
            # because cron expressions contain spaces (CSV parsing is fragile).
            # Override by editing the Settings default if you need a different
            # schedule.
            full_scan_stale_after_hours=int(
                os.environ.get("UW_SCAN_FULL_SCAN_STALE_HOURS", "1")
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
                "GEX_SCAN_TICKERS", default=["SPX", "SPY", "TLT"]
            ),
            gex_scan_interval_minutes=int(
                os.environ.get("GEX_SCAN_INTERVAL_MINUTES", "5")
            ),
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
        )

    def db_dsn(self) -> str:
        """Return a libpq-style DSN. Password omitted when blank (peer/trust auth)."""
        pw = self.db_password.get_secret_value()
        password_clause = f" password={pw}" if pw else ""
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user}{password_clause}"
        )
