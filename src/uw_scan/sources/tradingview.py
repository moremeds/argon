from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape


@dataclass(frozen=True)
class TradingViewParseResult:
    source_url: str
    source_label: str
    symbols: list[str]
    failed_symbols: list[str]
    status: str
    message: str


def _clean_symbol(raw: str) -> str:
    symbol = raw.split(":")[-1].strip().upper()
    return re.sub(r"[^A-Z0-9._-]", "", symbol)


def _title_label(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return "TradingView Watchlist"
    title = unescape(match.group(1)).strip()
    return re.sub(r"\s+[-\u2014]\s+TradingView$", "", title).strip()


def _symbols_from_json_scripts(html: str) -> list[str]:
    symbols: list[str] = []
    for script_match in re.finditer(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        content = script_match.group(1).strip()
        if not content.startswith("{"):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        raw_symbols = payload.get("symbols")
        if isinstance(raw_symbols, list):
            for raw in raw_symbols:
                if isinstance(raw, str):
                    cleaned = _clean_symbol(raw)
                    if cleaned and cleaned not in symbols:
                        symbols.append(cleaned)
    return symbols


def parse_tradingview_watchlist_html(html: str, *, source_url: str) -> TradingViewParseResult:
    label = _title_label(html)
    symbols = _symbols_from_json_scripts(html)
    if symbols:
        return TradingViewParseResult(
            source_url=source_url,
            source_label=label,
            symbols=symbols,
            failed_symbols=[],
            status="ok",
            message=f"Parsed {len(symbols)} symbols from static HTML.",
        )
    return TradingViewParseResult(
        source_url=source_url,
        source_label=label,
        symbols=[],
        failed_symbols=[],
        status="no_symbols_found",
        message="Static HTML did not expose symbols; use browser-rendered retrieval or keep this source degraded.",
    )
