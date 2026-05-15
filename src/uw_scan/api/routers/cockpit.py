"""/api/cockpit — Cockpit matrix state endpoints."""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models import CockpitStateResponse
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/cockpit/{ticker}/state", response_model=CockpitStateResponse)
def get_cockpit_state(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitStateResponse:
    t = ticker.upper()
    allowed = {item.upper() for item in settings.cockpit_tickers}
    if t not in allowed:
        raise HTTPException(status_code=404, detail=f"{t} is not in Cockpit universe")

    state = (
        repo.fetch_matrix_state_snapshot(ticker=t, market_date=asof)
        if asof is not None
        else repo.fetch_latest_matrix_state_snapshot(ticker=t)
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"no Cockpit state for {t}")

    freshness = repo.fetch_matrix_source_freshness(
        ticker=t, market_date=state.market_date
    )
    return CockpitStateResponse(state=state, freshness=freshness)
