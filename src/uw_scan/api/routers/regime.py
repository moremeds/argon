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
    GexResponse,
    RegimePendingResponse,
)
from uw_scan.config import Settings
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/regime")


def _is_market_open_now() -> bool:
    """Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


# ─── GEX (live) ──────────────────────────────────────────────────


@router.get("/gex", response_model=GexResponse)
def get_gex(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
) -> GexResponse:
    raw = repo.fetch_latest_gex(ticker=ticker.upper())
    if raw is None:
        empty = EMPTY_GEX_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        empty.ticker = ticker.upper()
        return empty
    raw["market_open"] = _is_market_open_now()
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
