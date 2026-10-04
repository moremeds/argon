"""Research-pool UW capture: intraday GEX, market tide, top net impact (D6 concern group: uw_capture)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar, _split_upper, _true_1_yes


class UwCaptureSettings(BaseModel):
    # Regime / GEX scanner (port from xenon — ships GEX live; CRI/VCG pending).
    # Expanded from the SPX/SPY/TLT core to the index family + M7 so the
    # append-only intraday GEX/DEX series (gex_snapshots) covers the names that
    # actually move dealer positioning intraday. UW serves GEX history only at
    # EOD, so the intraday evolution is buildable *only* by live capture —
    # spend research budget here. Override with UW_SCAN_GEX_SCAN_TICKERS.
    gex_scan_tickers: Annotated[
        list[str],
        EnvVar(
            "GEX_SCAN_TICKERS", strip=True, blank_is_default=True, parse=_split_upper
        ),
    ] = [
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
    gex_scan_rth_interval_minutes: Annotated[
        int, EnvVar("GEX_SCAN_RTH_INTERVAL_MINUTES")
    ] = 2
    gex_scan_offhours_interval_minutes: Annotated[
        int, EnvVar("GEX_SCAN_OFFHOURS_INTERVAL_MINUTES")
    ] = 15
    # Market-tide capture (UW /market/market-tide, ~81 calls/day at 5-min RTH).
    # Kill switch + the index whose live spot overlays the premium chart.
    market_tide_capture_enabled: Annotated[
        bool, EnvVar("MARKET_TIDE_CAPTURE_ENABLED", parse=_true_1_yes)
    ] = True
    market_tide_spot_ticker: Annotated[
        str, EnvVar("MARKET_TIDE_SPOT_TICKER", parse=str.upper)
    ] = "SPY"
    # Top-net-impact capture (UW /market/top-net-impact, ~32 calls/day at
    # 15-min RTH). Kill switch for the market-wide net-premium ranking.
    top_net_impact_capture_enabled: Annotated[
        bool, EnvVar("TOP_NET_IMPACT_CAPTURE_ENABLED", parse=_true_1_yes)
    ] = True
