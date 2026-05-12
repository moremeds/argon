"""Hardcoded S2 universe: ~40 liquid tickers spanning indexes, sectors, big tech,
finance, commodity ETFs, vol proxies, ADRs.

S4 replaces this with a TradingView import. Some entries (BABA, NIO, VIX) will not be
returned by `/api/screener/stocks?is_s_p_500=true` — they are silently dropped with a
log warning by the pipeline.
"""

from __future__ import annotations

S2_UNIVERSE: tuple[str, ...] = (
    # Index / sector ETFs
    "SPY",
    "QQQ",
    "IWM",
    "XLF",
    "XLE",
    "XLK",
    "XLV",
    "XLY",
    "XLI",
    # Mega-cap tech
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "META",
    "AMZN",
    "GOOGL",
    # Semi / software / cloud
    "AMD",
    "INTC",
    "MU",
    "AVGO",
    "ORCL",
    "CRM",
    "ADBE",
    # High-beta / retail favorites
    "PLTR",
    "COIN",
    "HOOD",
    "ROKU",
    "SHOP",
    "DDOG",
    "SNOW",
    # Banks / financials
    "JPM",
    "BAC",
    "GS",
    "MS",
    "C",
    # Commodity / rate / credit / vol proxies
    "GLD",
    "SLV",
    "TLT",
    "HYG",
    "VIX",
    # ADRs
    "BABA",
    "NIO",
)

assert 40 <= len(S2_UNIVERSE) <= 45, (
    f"S2_UNIVERSE expected ~40 names, got {len(S2_UNIVERSE)}"
)
