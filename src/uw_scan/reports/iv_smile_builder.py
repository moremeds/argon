"""Pivot greeks_by_expiry_strike rows into iv_smile_snapshots rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def build_iv_smile_snapshot_rows(
    *,
    ticker: str,
    market_date: date,
    greeks_rows: list[dict],
) -> list[dict]:
    """Average call/put IV per strike; fall back to whichever is present."""
    out: list[dict] = []
    for r in greeks_rows:
        c = r.get("call_volatility")
        p = r.get("put_volatility")
        if c is not None and p is not None:
            iv = (Decimal(str(c)) + Decimal(str(p))) / Decimal("2")
        elif c is not None:
            iv = Decimal(str(c))
        elif p is not None:
            iv = Decimal(str(p))
        else:
            continue
        out.append(
            {
                "ticker": ticker,
                "market_date": market_date,
                "expiry": r["expiry"],
                "strike": Decimal(str(r["strike"])),
                "iv": iv,
            }
        )
    return out
