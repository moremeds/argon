"""Dark Pool Accumulation detector (Tier 2, confirmation-only).

Reads the 5-day rolling window from signals_repository.fetch_dark_pool_window
rather than refetching UW. Direction-neutral: signal asserts size moved at
this level, not who initiated. Excluded from raw_score via
RAW_RANKING_EXCLUDE in scanner/ranking.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from uw_scan.scanner.models import SignalHit


def detect(
    *,
    ticker: str,
    dark_pool_prints: Iterable[dict[str, Any]],
    min_print_premium: Decimal,
    min_cluster_size: int,
    price_spread_pct: Decimal,
) -> SignalHit | None:
    large = [
        p
        for p in dark_pool_prints
        if p.get("premium") is not None
        and Decimal(str(p["premium"])) >= min_print_premium
        and p.get("price") is not None
        and Decimal(str(p["price"])) > 0
    ]
    if len(large) < min_cluster_size:
        return None

    window_start = min((p["executed_at"] for p in large), default=None)
    window_end = max((p["executed_at"] for p in large), default=None)

    for anchor in large:
        anchor_price = Decimal(str(anchor["price"]))
        cluster = [
            p
            for p in large
            if abs(Decimal(str(p["price"])) - anchor_price)
            / anchor_price
            * Decimal("100")
            <= price_spread_pct
        ]
        if len(cluster) >= min_cluster_size:
            total_premium = sum(
                (Decimal(str(p["premium"])) for p in cluster), Decimal("0")
            )
            score = min(Decimal("1.0"), total_premium / Decimal("10000000"))
            return SignalHit(
                ticker=ticker.upper(),
                signal_type="dark_pool_accumulation",
                tier=2,
                score=score,
                evidence={
                    "cluster_size": len(cluster),
                    "anchor_price": str(anchor_price),
                    "total_premium": str(total_premium),
                    "window_start": (window_start.isoformat() if window_start else None),
                    "window_end": (window_end.isoformat() if window_end else None),
                    "direction_neutral": True,
                },
                freshness="stale",
            )
    return None
