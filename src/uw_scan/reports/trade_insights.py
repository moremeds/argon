"""Deterministic Trade Insights assembler.

V1 is intentionally rule-based. Codex/LLM commentary is a later optional layer
that consumes this structured output but does not alter status or risk checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ParsedOptionSymbol:
    root: str
    expiry: date
    right: str
    strike: Decimal


def parse_option_symbol(symbol: str) -> ParsedOptionSymbol | None:
    """Parse OCC/OSI-style compact symbols like TSLA260515C00430000."""
    if len(symbol) < 15:
        return None
    right_index = max(symbol.rfind("C"), symbol.rfind("P"))
    if right_index < 6:
        return None
    right = symbol[right_index]
    ymd = symbol[right_index - 6 : right_index]
    strike_raw = symbol[right_index + 1 :]
    root = symbol[: right_index - 6]
    if not root or len(ymd) != 6 or len(strike_raw) != 8:
        return None
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        strike = Decimal(str(int(strike_raw))) / Decimal("1000")
    except (ValueError, ArithmeticError):
        return None
    return ParsedOptionSymbol(root=root, expiry=expiry, right=right, strike=strike)


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _mid(contract: dict) -> Decimal | None:
    bid = _dec(contract.get("nbbo_bid"))
    ask = _dec(contract.get("nbbo_ask"))
    if bid is not None and ask is not None and bid >= 0 and ask >= bid:
        return (bid + ask) / Decimal("2")
    return _dec(contract.get("last_price"))


def _credit_spread_math(
    *, short_mid: Decimal, long_mid: Decimal, width: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    net_credit = short_mid - long_mid
    max_profit = net_credit
    max_loss = width - net_credit
    return net_credit, max_loss, max_profit
