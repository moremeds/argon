"""Deep Conviction Flow detector (Tier 1).

Spec §3.1: derives ask_side_ratio / moneyness / dte from fields already
on FlowAlert rather than expanding the schema. Conservative-block on
unknown next_earnings_date - DCF must never emit during the earnings
window (this redundancy with the advisory earnings_gate is intentional).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.models import SignalHit


def _alert_qualifies(
    alert: FlowAlert,
    *,
    today: date,
    min_premium_usd: Decimal,
    min_ask_side: Decimal,
    max_moneyness: Decimal,
    min_dte: int,
    earnings_window_days: int,
) -> bool:
    # Earnings - conservative-block on unknown (xenon parity).
    if alert.next_earnings_date is None:
        return False
    if (alert.next_earnings_date - today).days <= earnings_window_days:
        return False

    if alert.volume is None or alert.open_interest is None:
        return False
    if alert.volume <= alert.open_interest:
        return False

    ask = alert.total_ask_side_prem
    bid = alert.total_bid_side_prem
    if ask is None or bid is None or (ask + bid) <= 0:
        return False
    ask_side_ratio = ask / (ask + bid)
    if ask_side_ratio < min_ask_side:
        return False

    if alert.total_premium is None or alert.total_premium < min_premium_usd:
        return False
    if alert.has_multileg is True:
        return False

    if (
        alert.strike is None
        or alert.underlying_price is None
        or alert.underlying_price <= 0
    ):
        return False
    moneyness = (alert.strike - alert.underlying_price) / alert.underlying_price
    if abs(moneyness) > max_moneyness:
        return False

    if alert.expiry is None:
        return False
    dte = (alert.expiry - today).days
    if dte < min_dte:
        return False

    return True


def detect(
    *,
    ticker: str,
    alerts: Iterable[FlowAlert],
    today: date,
    min_premium_usd: Decimal,
    min_ask_side: Decimal,
    max_moneyness: Decimal,
    min_dte: int,
    earnings_window_days: int,
) -> SignalHit | None:
    qualifying = [
        a
        for a in alerts
        if _alert_qualifies(
            a,
            today=today,
            min_premium_usd=min_premium_usd,
            min_ask_side=min_ask_side,
            max_moneyness=max_moneyness,
            min_dte=min_dte,
            earnings_window_days=earnings_window_days,
        )
    ]
    if not qualifying:
        return None

    total_premium = sum(
        (a.total_premium or Decimal("0") for a in qualifying), Decimal("0")
    )
    top = max(qualifying, key=lambda a: a.total_premium or Decimal("0"))
    premium_scale = min(total_premium / Decimal("2000000"), Decimal("1.0"))
    score = Decimal("0.5") + Decimal("0.5") * premium_scale

    top_ask = top.total_ask_side_prem or Decimal("0")
    top_bid = top.total_bid_side_prem or Decimal("0")
    top_ratio = (
        (top_ask / (top_ask + top_bid)) if (top_ask + top_bid) > 0 else Decimal("0")
    )
    top_dte = (top.expiry - today).days if top.expiry else None

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="deep_conviction_flow",
        tier=1,
        score=score,
        evidence={
            "qualifying_alerts": len(qualifying),
            "total_premium": str(total_premium),
            "top_strike": str(top.strike) if top.strike else None,
            "top_expiry": top.expiry.isoformat() if top.expiry else None,
            "top_ask_side_ratio": str(top_ratio),
            "top_dte": top_dte,
        },
        freshness="live",
    )
