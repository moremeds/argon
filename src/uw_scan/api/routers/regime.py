"""/regime — GEX live (UW-driven), CRI/VCG pending IB-via-R2 reader."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.schemas import (
    EMPTY_GEX_RESPONSE,
    GexHistoryEntry,
    GexResponse,
    RegimePendingResponse,
)
from uw_scan.config import Settings
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vol_index_repository import VolIndexRepository

router = APIRouter(prefix="/regime")

# Tickers whose spot history is sourced from the parquet lake. UW
# /ohlc/1d is tier-blocked for indices; massive doesn't quote indices.
_SPOT_FROM_LAKE = {"SPX"}


def _is_market_open_now() -> bool:
    """Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _assemble_history(repo: Repository, ticker: str, days: int = 90) -> list[dict]:
    """Join greek_exposure_daily × (vol_index_daily | daily_ohlc) × flip history."""
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    gex_rows = g.fetch_history(ticker, days=days)
    if not gex_rows:
        return []

    if ticker in _SPOT_FROM_LAKE:
        v = VolIndexRepository(repo.conn, schema=repo._schema)
        spot_rows = v.fetch_history(ticker, days=days)
        spot_by_date = {r["trade_date"]: r["close"] for r in spot_rows}
    else:
        ohlc = repo.list_daily_ohlc(ticker, limit=days)
        spot_by_date = {r.date: float(r.close) for r in ohlc}

    flip_by_date = repo.fetch_flip_strike_history(ticker=ticker, limit=days)

    return [
        {
            "date": row["trade_date"].isoformat(),
            "net_gex": row["net_gex"],
            "net_dex": row["net_dex"],
            "gex_flip": flip_by_date.get(row["trade_date"]),
            "spot": spot_by_date.get(row["trade_date"]),
        }
        for row in gex_rows
    ]


# ─── GEX (live) ──────────────────────────────────────────────────


@router.get("/gex", response_model=GexResponse)
def get_gex(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
) -> GexResponse:
    t = ticker.upper()
    raw = repo.fetch_latest_gex(ticker=t)
    history = _assemble_history(repo, t, days=90)
    if raw is None:
        empty = EMPTY_GEX_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        empty.ticker = t
        empty.history = [GexHistoryEntry.model_validate(h) for h in history]
        return empty
    raw["market_open"] = _is_market_open_now()
    raw["history"] = history
    return GexResponse.model_validate(raw)


@router.post("/gex/scan", status_code=202)
def trigger_gex_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    ticker: str = Query("SPX"),
) -> dict:
    """Run a GEX scan synchronously against UW and persist."""
    uw_client = UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )
    try:
        row_id = gex_scanner.run(uw_client, repo, ticker=ticker.upper())
    finally:
        uw_client.close()
    return {
        "status": "queued",
        "scanner": "gex",
        "ticker": ticker.upper(),
        "row_id": row_id,
    }


# ─── CRI (pending) ───────────────────────────────────────────────


@router.get("", response_model=RegimePendingResponse)
def get_regime() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="cri")


@router.post("/scan", status_code=202, response_model=RegimePendingResponse)
def trigger_cri_scan() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="cri")


# ─── VCG (pending) ───────────────────────────────────────────────


@router.get("/vcg", response_model=RegimePendingResponse)
def get_vcg() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="vcg")


@router.post("/vcg/scan", status_code=202, response_model=RegimePendingResponse)
def trigger_vcg_scan() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="vcg")
