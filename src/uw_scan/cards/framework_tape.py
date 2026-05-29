"""Pure price-action ("tape") deriver for the Framework view (M6).

`derive_framework_tape` turns stored daily OHLCV rows into the bounded set of
numbers the framework's price-action axis needs — trend, moving averages,
drawdown, volume posture, support/resistance, and recent returns. The model
never computes these itself; it reasons over the numbers this function emits.

Every output is `None` ("na") when the inputs are insufficient — never a
fabricated value, never a crash. All math is `Decimal`. Rows may be
``DailyOhlcRow`` objects or plain dicts (duck-typed via ``_field``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# How many trailing trading days approximate six calendar months.
_SIX_MONTH_BARS = 126
# Tolerance band for counting a price "touch" of a support/resistance level.
_TOUCH_TOL = Decimal("0.005")  # 0.5%


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def _pct(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator - Decimal(1)


def _empty_tape() -> dict[str, Any]:
    return {
        "available": False,
        "bars": 0,
        "latest_close": None,
        "trend_3close": None,
        "dma_50": None,
        "dma_200": None,
        "price_vs_dma50": None,
        "price_vs_dma200": None,
        "drawdown_from_6m_high": None,
        "return_5d": None,
        "return_20d": None,
        "vol_vs_5d": None,
        "vol_vs_30d": None,
        "distribution_day": None,
        "nearest_support": None,
        "nearest_resistance": None,
        "support_touches": None,
        "resistance_touches": None,
        "last_overnight_gap": None,
        "days_to_earnings": None,
    }


def _trend_3close(closes: list[Decimal]) -> str | None:
    if len(closes) < 3:
        return None
    a, b, c = closes[-3], closes[-2], closes[-1]
    if a < b < c:
        return "up"
    if a > b > c:
        return "down"
    return "mixed"


def _pivot_levels(
    highs: list[Decimal], lows: list[Decimal], k: int = 2
) -> tuple[list[Decimal], list[Decimal]]:
    """Swing pivots: a high is a pivot-high if it's the max of its ±k window
    (symmetric), likewise pivot-low. Returns (pivot_highs, pivot_lows)."""
    pivot_highs: list[Decimal] = []
    pivot_lows: list[Decimal] = []
    n = len(highs)
    for i in range(k, n - k):
        window_h = highs[i - k : i + k + 1]
        window_l = lows[i - k : i + k + 1]
        if highs[i] == max(window_h):
            pivot_highs.append(highs[i])
        if lows[i] == min(window_l):
            pivot_lows.append(lows[i])
    return pivot_highs, pivot_lows


def _touches(series: list[Decimal], level: Decimal) -> int:
    if level == 0:
        return 0
    return sum(1 for v in series if abs(v - level) / level <= _TOUCH_TOL)


def derive_framework_tape(
    ohlcv_rows: list[Any],
    *,
    next_earnings_date: date | None = None,
) -> dict[str, Any]:
    """Derive price-action features from daily OHLCV rows (order-agnostic input)."""
    if not ohlcv_rows:
        return _empty_tape()

    rows = sorted(ohlcv_rows, key=lambda r: _field(r, "date"))
    closes = [c for r in rows if (c := _dec(_field(r, "close"))) is not None]
    highs = [h for r in rows if (h := _dec(_field(r, "high"))) is not None]
    lows = [low for r in rows if (low := _dec(_field(r, "low"))) is not None]
    opens = [_dec(_field(r, "open")) for r in rows]
    vols = [v for r in rows if (v := _dec(_field(r, "volume"))) is not None]

    if not closes:
        out = _empty_tape()
        out["bars"] = len(rows)
        return out

    latest_close = closes[-1]
    out = _empty_tape()
    out["available"] = True
    out["bars"] = len(rows)
    out["latest_close"] = latest_close
    out["trend_3close"] = _trend_3close(closes)

    dma_50 = _mean(closes[-50:]) if len(closes) >= 50 else None
    dma_200 = _mean(closes[-200:]) if len(closes) >= 200 else None
    out["dma_50"] = dma_50
    out["dma_200"] = dma_200
    out["price_vs_dma50"] = _pct(latest_close, dma_50)
    out["price_vs_dma200"] = _pct(latest_close, dma_200)

    if highs:
        high_6m = max(highs[-_SIX_MONTH_BARS:])
        out["drawdown_from_6m_high"] = _pct(latest_close, high_6m)

    if len(closes) >= 6:
        out["return_5d"] = _pct(latest_close, closes[-6])
    if len(closes) >= 21:
        out["return_20d"] = _pct(latest_close, closes[-21])

    if vols:
        latest_vol = vols[-1]
        avg5 = _mean(vols[-6:-1]) if len(vols) >= 6 else None
        avg30 = _mean(vols[-31:-1]) if len(vols) >= 31 else None
        out["vol_vs_5d"] = _pct(latest_vol, avg5)
        out["vol_vs_30d"] = _pct(latest_vol, avg30)
        # Distribution day: a down close on higher volume than the prior day.
        if len(closes) >= 2 and len(vols) >= 2:
            out["distribution_day"] = bool(
                closes[-1] < closes[-2] and vols[-1] > vols[-2]
            )

    # Support/resistance from swing pivots within the window.
    if len(highs) >= 5 and len(lows) >= 5:
        pivot_highs, pivot_lows = _pivot_levels(highs, lows)
        resistances = sorted(p for p in pivot_highs if p > latest_close)
        supports = sorted((p for p in pivot_lows if p < latest_close), reverse=True)
        if resistances:
            level = resistances[0]
            out["nearest_resistance"] = level
            out["resistance_touches"] = _touches(highs, level)
        if supports:
            level = supports[0]
            out["nearest_support"] = level
            out["support_touches"] = _touches(lows, level)

    # Latest overnight gap = today's open vs yesterday's close.
    if len(closes) >= 2 and opens and opens[-1] is not None:
        out["last_overnight_gap"] = _pct(opens[-1], closes[-2])

    if next_earnings_date is not None:
        latest_date = _field(rows[-1], "date")
        if isinstance(latest_date, date):
            out["days_to_earnings"] = (next_earnings_date - latest_date).days

    return out
