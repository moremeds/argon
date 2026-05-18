"""Dark Pool Accumulation detector (Tier 2, confirmation-only).

Reads the 5-day rolling window from signals_repository.fetch_dark_pool_window
rather than refetching UW. The cluster itself is direction-neutral (off-exchange
prints don't carry buy/sell tags), but the cluster's price *relative to spot*
is an interpretive hint: clusters below spot often imply passive accumulation
(bids hit), clusters above often imply lifting offers or distribution. Surfaced
as evidence.vs_spot for the UI; not used in scoring. Excluded from raw_score
via RAW_RANKING_EXCLUDE in scanner/ranking.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from uw_scan.scanner.models import SignalHit

# Anything within ±0.05% of spot is "at spot" — tighter than this is noise.
_VS_SPOT_TOLERANCE_PCT = Decimal("0.05")


def _classify_vs_spot(
    anchor_price: Decimal, spot: Decimal | None
) -> tuple[str, Decimal | None]:
    if spot is None or spot <= 0:
        return ("unknown", None)
    delta_pct = (anchor_price - spot) / spot * Decimal("100")
    if abs(delta_pct) <= _VS_SPOT_TOLERANCE_PCT:
        return ("at", delta_pct)
    return ("above" if delta_pct > 0 else "below", delta_pct)


def detect(
    *,
    ticker: str,
    dark_pool_prints: Iterable[dict[str, Any]],
    min_print_premium: Decimal,
    min_cluster_size: int,
    price_spread_pct: Decimal,
    spot: Decimal | None = None,
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
            cluster_prices = [Decimal(str(p["price"])) for p in cluster]
            cluster_premiums = [Decimal(str(p["premium"])) for p in cluster]
            total_premium = sum(cluster_premiums, Decimal("0"))
            price_min = min(cluster_prices)
            price_max = max(cluster_prices)
            # Premium-weighted average — more honest than the anchor as a
            # single representative price, because anchor selection is
            # order-dependent (first qualifying print wins).
            vwap = (
                sum(
                    (pr * pm for pr, pm in zip(cluster_prices, cluster_premiums)),
                    Decimal("0"),
                )
                / total_premium
            )
            score = min(Decimal("1.0"), total_premium / Decimal("10000000"))
            vs_spot, vs_spot_pct = _classify_vs_spot(vwap, spot)
            return SignalHit(
                ticker=ticker.upper(),
                signal_type="dark_pool_accumulation",
                tier=2,
                score=score,
                evidence={
                    "cluster_size": len(cluster),
                    "anchor_price": str(anchor_price),
                    "cluster_price_min": str(price_min.quantize(Decimal("0.01"))),
                    "cluster_price_max": str(price_max.quantize(Decimal("0.01"))),
                    "cluster_price_vwap": str(vwap.quantize(Decimal("0.01"))),
                    "total_premium": str(total_premium),
                    "window_start": (
                        window_start.isoformat() if window_start else None
                    ),
                    "window_end": (window_end.isoformat() if window_end else None),
                    "direction_neutral": True,
                    "vs_spot": vs_spot,
                    "vs_spot_pct": (
                        str(vs_spot_pct.quantize(Decimal("0.01")))
                        if vs_spot_pct is not None
                        else None
                    ),
                    "spot": str(spot) if spot is not None else None,
                },
                freshness="stale",
            )
    return None
