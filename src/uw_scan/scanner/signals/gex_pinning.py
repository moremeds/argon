"""GEX Pinning detector (Tier 1, mega-caps during opex week only).

Port of xenon/scanners/uw/signals/gex_pinning.py + the detect_pinning
helper from xenon/analysis/gex.py:50. Reads this run's strike_gex_curve
(per-strike for the nearest expiry - during opex week the nearest IS
the opex expiry, so this is functionally equivalent to xenon's
greek_exposure_by_strike for this detector). Spec §3.4.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.scanner.calendars import is_opex_week
from uw_scan.scanner.models import SignalHit

MEGA_CAPS: frozenset[str] = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
        "GOOG",
        "AMZN",
        "META",
        "TSLA",
    }
)

MAX_DISTANCE_PCT = Decimal("1.0")  # xenon detect_pinning default


def _gamma(wall: dict[str, Any]) -> Decimal | None:
    raw = wall.get("net_gex") if "net_gex" in wall else wall.get("gamma")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None


def _rank_walls(strikes: list[dict[str, Any]], top_n: int = 5) -> list[dict]:
    scored: list[tuple[Decimal, dict[str, Any]]] = []
    for s in strikes:
        g = _gamma(s)
        if g is None or s.get("strike") is None:
            continue
        scored.append((abs(g), s))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [s for _, s in scored[:top_n]]


def _detect_pinning(
    strikes: list[dict[str, Any]],
    *,
    price: Decimal,
    min_gamma: Decimal,
    max_distance_pct: Decimal = MAX_DISTANCE_PCT,
) -> dict[str, Any] | None:
    if price <= 0:
        return None
    for wall in _rank_walls(strikes, top_n=5):
        strike = Decimal(str(wall["strike"]))
        gamma = _gamma(wall) or Decimal("0")
        if abs(gamma) < min_gamma:
            continue
        distance_pct = abs(strike - price) / price * Decimal("100")
        if distance_pct <= max_distance_pct:
            return {
                "strike": str(strike),
                "gamma": str(gamma),
                "distance_pct": str(distance_pct),
            }
    return None


def detect(
    *,
    ticker: str,
    strike_gex_curve: list[dict[str, Any]] | None,
    spot: Decimal | None,
    today: date,
    min_gamma: Decimal,
) -> SignalHit | None:
    if ticker.upper() not in MEGA_CAPS:
        return None
    if not is_opex_week(today):
        return None
    if not strike_gex_curve or spot is None:
        return None

    pin = _detect_pinning(strike_gex_curve, price=spot, min_gamma=min_gamma)
    if pin is None:
        return None

    distance_pct = Decimal(pin["distance_pct"])
    gamma = Decimal(pin["gamma"])
    distance_score = max(Decimal("0"), Decimal("1") - distance_pct)
    gamma_score = min(Decimal("1.0"), abs(gamma) / Decimal("10"))
    score = (
        Decimal("0.5") * distance_score + Decimal("0.5") * gamma_score
    ).quantize(Decimal("0.01"))

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="gex_pinning",
        tier=1,
        score=score,
        evidence={
            "strike": pin["strike"],
            "distance_pct": pin["distance_pct"],
            "gamma": pin["gamma"],
        },
        freshness="live",
    )
