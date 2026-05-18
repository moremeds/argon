"""Earnings IV Crush detector (Tier 1).

Reads iv_rank directly (0-100 scale) - NOT iv_percentile_30d from
interpolated_iv_snapshots, which is a different metric. (Spec §3.3.)
Earnings unknown -> no fire (matches DCF conservative-block).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.scanner.models import SignalHit


def detect(
    *,
    ticker: str,
    iv_rank: Decimal | None,
    next_earnings_date: date | None,
    today: date,
    min_iv_rank: Decimal,
    earnings_window_days: int,
) -> SignalHit | None:
    if iv_rank is None or iv_rank < min_iv_rank:
        return None
    if next_earnings_date is None:
        return None
    days = (next_earnings_date - today).days
    if days <= 0 or days > earnings_window_days:
        return None

    delta = (iv_rank - min_iv_rank) / Decimal("25") + Decimal("0.5")
    score = min(Decimal("1.0"), delta)

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="earnings_iv_crush",
        tier=1,
        score=score,
        evidence={
            "iv_rank": str(iv_rank),
            "earnings_date": next_earnings_date.isoformat(),
            "earnings_within_days": days,
        },
        freshness="live",
    )
