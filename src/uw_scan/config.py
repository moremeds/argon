from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _dotenv_values(path: Path | str = Path(".env")) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str, default: str = "", *, dotenv_path: Path = Path(".env")) -> str:
    dotenv = _dotenv_values(dotenv_path)
    return os.environ.get(name) or dotenv.get(name, default)


def _int_env(name: str, default: int, *, dotenv_path: Path = Path(".env")) -> int:
    raw = _env(name, dotenv_path=dotenv_path)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class UwScanConfig:
    api_key: str | None = None
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "option_wizard"
    db_schema: str = "uw_scan"
    db_user: str = ""
    db_password: str = ""
    poll_seconds: int = 60
    max_requests_per_cycle: int = 250
    max_flow_rows: int = 100
    max_tv_symbols_per_source: int = 200
    max_watchlist_tickers: int = 50
    max_analysis_tickers: int = 3
    max_deep_surface_tickers: int = 8
    max_expiries_per_ticker: int = 4
    max_option_contract_pages: int = 2

    @classmethod
    def from_env(cls, *, dotenv_path: Path = Path(".env")) -> "UwScanConfig":
        return cls(
            api_key=_env("UW_SCAN_API_KEY", dotenv_path=dotenv_path) or None,
            db_host=_env("UW_SCAN_DB_HOST", cls.db_host, dotenv_path=dotenv_path),
            db_port=_int_env("UW_SCAN_DB_PORT", cls.db_port, dotenv_path=dotenv_path),
            db_name=_env("UW_SCAN_DB_NAME", cls.db_name, dotenv_path=dotenv_path),
            db_schema=_env("UW_SCAN_DB_SCHEMA", cls.db_schema, dotenv_path=dotenv_path),
            db_user=_env("UW_SCAN_DB_USER", cls.db_user, dotenv_path=dotenv_path),
            db_password=_env("UW_SCAN_DB_PASSWORD", cls.db_password, dotenv_path=dotenv_path),
            poll_seconds=_int_env("UW_SCAN_POLL_SECONDS", cls.poll_seconds, dotenv_path=dotenv_path),
            max_requests_per_cycle=_int_env("UW_SCAN_MAX_REQUESTS_PER_CYCLE", cls.max_requests_per_cycle, dotenv_path=dotenv_path),
            max_flow_rows=_int_env("UW_SCAN_MAX_FLOW_ROWS", cls.max_flow_rows, dotenv_path=dotenv_path),
            max_tv_symbols_per_source=_int_env("UW_SCAN_MAX_TV_SYMBOLS_PER_SOURCE", cls.max_tv_symbols_per_source, dotenv_path=dotenv_path),
            max_watchlist_tickers=_int_env("UW_SCAN_MAX_WATCHLIST_TICKERS", cls.max_watchlist_tickers, dotenv_path=dotenv_path),
            max_analysis_tickers=_int_env("UW_SCAN_MAX_ANALYSIS_TICKERS", cls.max_analysis_tickers, dotenv_path=dotenv_path),
            max_deep_surface_tickers=_int_env("UW_SCAN_MAX_DEEP_SURFACE_TICKERS", cls.max_deep_surface_tickers, dotenv_path=dotenv_path),
            max_expiries_per_ticker=_int_env("UW_SCAN_MAX_EXPIRIES_PER_TICKER", cls.max_expiries_per_ticker, dotenv_path=dotenv_path),
            max_option_contract_pages=_int_env("UW_SCAN_MAX_OPTION_CONTRACT_PAGES", cls.max_option_contract_pages, dotenv_path=dotenv_path),
        )
