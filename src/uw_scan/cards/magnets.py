"""Magnet-view geometry (spec 2026-08-08 §4).

The ZigZag threshold is in ATR(14) units rather than a fixed percentage, which
is why this is worth keeping over the reference's own detector: an ATR threshold
adapts to each ticker's volatility instead of applying one percentage to a $20
stock and a $900 one.

The 0.618 extension levels this module computes have **no measured edge**. The
Phase-1 first-passage study (`docs/research/2026-08-08-magnet-cone-calibration/`)
tested whether price reaches STRETCH before it reaches the opposite pivot more
often than a random level at the same distance would, and it does not. They are
kept as chart geometry because the reference chart draws them and because a
reader who knows the construction can place them; they are never a target.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pandas as pd

from uw_scan.cards.technicals import atr14


class Pivot(NamedTuple):
    index: int  # bar the extreme occurred on
    kind: str  # "top" | "bottom"
    price: float  # close at `index`
    confirmed_index: int  # bar the reversal threshold was crossed — the FIRST bar
    # on which this pivot was knowable. Never backtest from
    # `index`; measured lag is 3-25 bars and 8-14% of price.


def all_pivots(df: pd.DataFrame, k: float = 3.0) -> list[Pivot]:
    """Every confirmed ATR-zigzag pivot, oldest first.

    A pivot is a swing extreme that LATER reverses by >= k * ATR(14). Confirmation
    is retrospective by construction, so the newest extreme is never a pivot until
    price has moved away from it — that lag is the price of not repainting.

    Each pivot therefore carries TWO indices. `index` is where the extreme sits on
    the chart; `confirmed_index` is where a live system would first have known
    about it. Drawing uses `index`; any forward test MUST use `confirmed_index`.
    """
    if len(df) < 30:
        return []
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    pivots: list[Pivot] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(Pivot(ext_i, "top", float(close[ext_i]), i))
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(Pivot(ext_i, "bottom", float(close[ext_i]), i))
                direction, ext_i = 1, i
    return pivots


FIB = 0.618


def magnet_levels(df: pd.DataFrame, k: float = 3.0) -> dict | None:
    """The four levels, SMA20 and leg state from the last two ZigZag pivots.

    `leg_state` is "rising" when the LATER pivot is the bottom (price is working
    up off support) and "falling" otherwise. Returns None when fewer than two
    pivots exist — a chart with no measurable swing has no magnet levels, and
    fabricating them from the window's min/max would invent a swing.

    Uses `Pivot.index`, not `confirmed_index`: this draws where the extreme sits
    on the chart. Any forward test must use `confirmed_index` instead.
    """
    pivots = all_pivots(df, k=k)
    if len(pivots) < 2:
        return None
    a, b = pivots[-2], pivots[-1]
    rising = b.kind == "bottom"
    resistance = a.price if rising else b.price
    support = b.price if rising else a.price
    if resistance <= support:
        return None
    leg = resistance - support
    close = df["close"].astype(float)
    return {
        "resistance": float(resistance),
        "support": float(support),
        "stretch": float(resistance + FIB * leg),
        "down": float(support - FIB * leg),
        "sma20": float(close.tail(20).mean()) if len(close) >= 20 else None,
        "last": float(close.iloc[-1]),
        "leg_state": "rising" if rising else "falling",
        "pivot_a": {"index": a.index, "kind": a.kind, "price": float(a.price)},
        "pivot_b": {"index": b.index, "kind": b.kind, "price": float(b.price)},
    }
