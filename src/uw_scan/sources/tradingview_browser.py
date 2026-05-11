from __future__ import annotations

import re

from .tradingview import TradingViewParseResult, _clean_symbol, _title_label


_TV_SYMBOL_RE = re.compile(r"\b(?:NASDAQ|NYSE|AMEX|ARCA|CBOE|OTC|NASDAQCM|NASDAQGS):([A-Z0-9._-]{1,12})\b")


def parse_tradingview_rendered_html(html: str, *, source_url: str) -> TradingViewParseResult:
    label = _title_label(html)
    symbols: list[str] = []
    for match in _TV_SYMBOL_RE.finditer(html.upper()):
        cleaned = _clean_symbol(match.group(0))
        if cleaned and cleaned not in symbols:
            symbols.append(cleaned)
    if symbols:
        return TradingViewParseResult(
            source_url=source_url,
            source_label=label,
            symbols=symbols,
            failed_symbols=[],
            status="ok",
            message=f"Parsed {len(symbols)} symbols from browser-rendered HTML.",
        )
    return TradingViewParseResult(
        source_url=source_url,
        source_label=label,
        symbols=[],
        failed_symbols=[],
        status="no_symbols_found",
        message="Browser-rendered TradingView page did not expose symbols.",
    )
