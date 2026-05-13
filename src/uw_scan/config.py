"""Pydantic-managed environment settings for the UW scanner."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    full_scan_cron: str = "0 9-16 * * 1-5"
    ohlc_pull_cron: str = "30 17 * * 1-5"
    rth_tz: str = "America/New_York"
    # OHLC provider (massive.com)
    massive_api_key: SecretStr | None = None
    massive_base_url: str = "https://api.massive.com"
    # Trade Insights V1.5 local Codex analysis
    trade_insights_ai_enabled: bool = False
    trade_insights_ai_model: str = ""
    trade_insights_ai_timeout_seconds: float = 90.0
    trade_insights_ai_max_output_bytes: int = 262144
    trade_insights_ai_poll_seconds: int = 3

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
            full_scan_cron=os.environ.get("UW_SCAN_FULL_SCAN_CRON", "0 9-16 * * 1-5"),
            ohlc_pull_cron=os.environ.get("UW_SCAN_OHLC_PULL_CRON", "30 17 * * 1-5"),
            rth_tz=os.environ.get("UW_SCAN_RTH_TZ", "America/New_York"),
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
            trade_insights_ai_enabled=_env_bool("TRADE_INSIGHTS_AI_ENABLED", False),
            trade_insights_ai_model=os.environ.get("TRADE_INSIGHTS_AI_MODEL", ""),
            trade_insights_ai_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_TIMEOUT_SECONDS", "90.0")
            ),
            trade_insights_ai_max_output_bytes=int(
                os.environ.get("TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES", "262144")
            ),
            trade_insights_ai_poll_seconds=int(
                os.environ.get("TRADE_INSIGHTS_AI_POLL_SECONDS", "3")
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
