"""Live regime quotes and credit ETF symbols (D6 concern group: regime)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar, _split_upper


class RegimeSettings(BaseModel):
    # Regime live feed — symbols the WS consumer always subscribes IN ADDITION
    # to the watchlist (indexes route via XENON_INDEX_SYMBOLS → CBOE; HYG is a
    # plain ETF symbol). Drives the live CRI/VCG compute + 5-min snapshots.
    regime_ws_symbols: Annotated[
        list[str],
        EnvVar(
            "REGIME_WS_SYMBOLS", strip=True, blank_is_default=True, parse=_split_upper
        ),
    ] = ["VIX", "VVIX", "VIX3M", "COR1M", "SPX", "HYG"]
    # Cadence of the regime_live_scan job (basis='live' snapshot writes).
    regime_live_scan_interval_minutes: Annotated[
        int, EnvVar("REGIME_LIVE_SCAN_INTERVAL_MINUTES")
    ] = 5
    # Quotes older than this are ignored by the live compute (stale feed →
    # the live endpoints fall back to the latest basis='eod' snapshot).
    regime_live_quote_max_age_seconds: Annotated[
        int, EnvVar("REGIME_LIVE_QUOTE_MAX_AGE_SECONDS")
    ] = 900
    # Credit-proxy ETFs synced from the equity lake into vol_index_daily.
    # The VCG scanner reads from this list; the first entry is the default
    # proxy unless overridden by the API caller.
    credit_etf_symbols: Annotated[
        list[str],
        EnvVar(
            "CREDIT_ETF_SYMBOLS", strip=True, blank_is_default=True, parse=_split_upper
        ),
    ] = ["HYG", "JNK", "LQD"]
