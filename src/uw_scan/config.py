"""Pydantic-managed environment settings for the UW scanner."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

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


class Settings(BaseModel):
    """Strongly-typed configuration. Raises on missing required fields."""

    api_key: SecretStr = Field(...)
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "option_wizard"
    db_schema: str = "uw_scan"
    db_user: str = "chenxi"
    db_password: SecretStr = SecretStr("")
    max_requests_per_minute: int = 110
    request_timeout_seconds: float = 30.0
    base_url: str = "https://api.unusualwhales.com"
    # Scheduler — consumed by uw_scan.worker.scheduler and uw_scan.api.routers.health
    spot_refresh_seconds: int = 300
    full_scan_cron: str = "0 5-16 * * 1-5"
    ohlc_pull_cron: str = "30 17 * * 1-5"
    rth_tz: str = "America/New_York"
    worker_role: str = "all"
    worker_index: int = 0
    worker_count: int = 1
    uw_worker_count: int = 0
    massive_worker_count: int = 0
    # OHLC provider (massive.com)
    massive_api_key: SecretStr | None = None
    massive_base_url: str = "https://api.massive.com"
    # WGC Goldhub authenticated downloads. Keep secrets in environment only.
    wgc_goldhub_cookie: SecretStr | None = None
    wgc_etf_flows_workbook_path: str = ""
    # Trade Insights V1.5 local Codex analysis
    trade_insights_ai_enabled: bool = False
    trade_insights_ai_model: str = ""
    trade_insights_ai_timeout_seconds: float = 300.0
    trade_insights_ai_max_output_bytes: int = 262144
    trade_insights_ai_poll_seconds: int = 3
    # Cockpit (6-dim matrix) — see docs/superpowers/research/six-dimension-matrix/
    cockpit_tickers: list[str] = ["SPX", "SPY", "QQQ", "IWM"]
    cockpit_snapshot_cron: str = "30 16 * * 1-5"
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
    scanner_dp_min_print_premium_usd: Decimal = Decimal("1000000")
    scanner_dp_min_cluster_size: int = 3
    scanner_dp_price_spread_pct: Decimal = Decimal("0.5")
    scanner_eic_min_iv_rank: Decimal = Decimal("75.0")
    scanner_gex_pin_min_gamma: Decimal = Decimal("1.0")
    scanner_liquidity_min_option_volume: int = 1000
    scanner_earnings_window_days: int = 14
    # Regime / GEX scanner (port from xenon — ships GEX live; CRI/VCG pending)
    gex_scan_tickers: list[str] = ["SPX", "SPY"]
    gex_scan_interval_minutes: int = 5
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

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        """Load Settings from process env, auto-loading .env at repo root if present."""
        if env_path is None:
            env_path = Path(__file__).resolve().parents[2] / ".env"
        _load_dotenv(env_path)

        api_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "UW_SCAN_API_KEY is not set. Add it to .env or export it before running."
            )

        return cls(
            api_key=SecretStr(api_key),
            db_host=os.environ.get("UW_SCAN_DB_HOST", "127.0.0.1"),
            db_port=int(os.environ.get("UW_SCAN_DB_PORT", "5432")),
            db_name=os.environ.get("UW_SCAN_DB_NAME", "option_wizard"),
            db_schema=os.environ.get("UW_SCAN_DB_SCHEMA", "uw_scan"),
            db_user=os.environ.get("UW_SCAN_DB_USER", "") or "chenxi",
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
            spot_refresh_seconds=int(
                os.environ.get("UW_SCAN_SPOT_REFRESH_SECONDS", "300")
            ),
            full_scan_cron=os.environ.get("UW_SCAN_FULL_SCAN_CRON", "0 5-16 * * 1-5"),
            ohlc_pull_cron=os.environ.get("UW_SCAN_OHLC_PULL_CRON", "30 17 * * 1-5"),
            rth_tz=os.environ.get("UW_SCAN_RTH_TZ", "America/New_York"),
            worker_role=os.environ.get("UW_SCAN_WORKER_ROLE", "all"),
            worker_index=int(os.environ.get("UW_SCAN_WORKER_INDEX", "0")),
            worker_count=int(os.environ.get("UW_SCAN_WORKER_COUNT", "1")),
            uw_worker_count=int(os.environ.get("UW_SCAN_UW_WORKER_COUNT", "0")),
            massive_worker_count=int(
                os.environ.get("UW_SCAN_MASSIVE_WORKER_COUNT", "0")
            ),
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
            wgc_goldhub_cookie=(
                SecretStr(_wgc_cookie)
                if (_wgc_cookie := os.environ.get("WGC_GOLDHUB_COOKIE", "").strip())
                else None
            ),
            wgc_etf_flows_workbook_path=os.environ.get(
                "WGC_ETF_FLOWS_WORKBOOK_PATH", ""
            ).strip(),
            trade_insights_ai_enabled=_env_bool("TRADE_INSIGHTS_AI_ENABLED", False),
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
            cockpit_tickers=_parse_csv_env(
                "COCKPIT_TICKERS", default=["SPX", "SPY", "QQQ", "IWM"]
            ),
            cockpit_snapshot_cron=os.environ.get(
                "COCKPIT_SNAPSHOT_CRON", "30 16 * * 1-5"
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
            gex_scan_tickers=_parse_csv_env("GEX_SCAN_TICKERS", default=["SPX", "SPY"]),
            gex_scan_interval_minutes=int(
                os.environ.get("GEX_SCAN_INTERVAL_MINUTES", "5")
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
        )

    def db_dsn(self) -> str:
        """Return a libpq-style DSN. Password omitted when blank (peer/trust auth)."""
        pw = self.db_password.get_secret_value()
        password_clause = f" password={pw}" if pw else ""
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user}{password_clause}"
        )
