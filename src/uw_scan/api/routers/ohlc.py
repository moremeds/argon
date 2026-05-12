"""/api/ohlc/{ticker} — daily bars from the local cache."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import OhlcRow
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/ohlc/{ticker}", response_model=list[OhlcRow])
def get_ohlc(
    ticker: str,
    days: int = Query(30, ge=1, le=365),
    repo: Repository = Depends(get_repo),
) -> list[OhlcRow]:
    rows = repo.list_daily_ohlc(ticker.upper(), limit=days)
    return [
        OhlcRow(
            date=r.date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
        )
        for r in rows
    ]
