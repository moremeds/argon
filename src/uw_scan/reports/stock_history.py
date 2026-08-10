"""Daily stock-history rollup → `StockHistoryResponse`.

Shared by `/api/stock/{ticker}/history` and the Trade Insights assembler. Both
routers previously carried byte-identical copies of this loop, so the
`net_dex=None` placeholder had to be fixed in two places.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from uw_scan.cards.gex import classify_bias, find_flip_strike
from uw_scan.models import StockHistoryResponse, StockHistoryRow, StrikeGexBucket
from uw_scan.storage.repository import Repository


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def build_curve(raw: list[dict]) -> list[StrikeGexBucket]:
    return [
        StrikeGexBucket(
            strike=Decimal(str(row["strike"])),
            expiry=_date.fromisoformat(str(row["expiry"])),
            net_gex=_dec(row.get("net_gex")),
            call_gex=_dec(row.get("call_gex")),
            put_gex=_dec(row.get("put_gex")),
        )
        for row in raw
    ]


def build_stock_history_response(
    ticker: str, repo: Repository, *, limit: int = 30
) -> StockHistoryResponse:
    """One row per trading day, newest-first.

    Today's row may have spot=None if the post-close OHLC pull hasn't fired yet.
    `net_dex` is always None — the daily rollup carries no DEX column, and no
    router surfaces one (docs/research/six-dimension-matrix/08-implementation-gaps.md).
    Callers normalise the ticker; this passes it through verbatim.
    """
    rows: list[StockHistoryRow] = []
    for r in repo.fetch_stock_history_rollup(ticker, limit=limit):
        curve = build_curve(r["strike_gex_curve"] or [])
        net_gex = sum((b.net_gex for b in curve if b.net_gex is not None), Decimal("0"))
        flip = find_flip_strike(curve)
        spot = _dec(r.get("spot"))
        rows.append(
            StockHistoryRow(
                market_date=r["market_date"],
                spot=spot,
                gex_flip=flip,
                net_gex=net_gex if curve else None,
                net_dex=None,
                iv30d=_dec(r.get("iv30d")),
                pcr_vol=_dec(r.get("pcr_vol")),
                bias=classify_bias(spot, flip, net_gex if curve else None),
            )
        )
    return StockHistoryResponse(ticker=ticker, rows=rows)
