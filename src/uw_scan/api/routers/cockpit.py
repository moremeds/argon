"""/api/cockpit — Cockpit matrix state endpoints."""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models import (
    CockpitDealerResponse,
    CockpitFlowImResponse,
    CockpitStateResponse,
    CockpitSurfaceResponse,
    CockpitVrpResponse,
)
from uw_scan.storage.repository import Repository

router = APIRouter()


def _guard_ticker(ticker: str, settings: Settings) -> str:
    t = ticker.upper()
    allowed = {item.upper() for item in settings.cockpit_tickers}
    if t not in allowed:
        raise HTTPException(status_code=404, detail=f"{t} is not in Cockpit universe")
    return t


def _state_for(
    ticker: str,
    *,
    asof: _date | None,
    repo: Repository,
):
    state = (
        repo.fetch_matrix_state_snapshot(ticker=ticker, market_date=asof)
        if asof is not None
        else repo.fetch_latest_matrix_state_snapshot(ticker=ticker)
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"no Cockpit state for {ticker}")
    return state


def _tab_market_date_for(
    ticker: str,
    *,
    asof: _date | None,
    repo: Repository,
) -> _date:
    if asof is not None:
        return asof
    source_date = repo.fetch_latest_cockpit_source_market_date(ticker=ticker)
    if source_date is not None:
        return source_date
    state = repo.fetch_latest_matrix_state_snapshot(ticker=ticker)
    if state is not None:
        return state.market_date
    raise HTTPException(status_code=404, detail=f"no Cockpit source data for {ticker}")


@router.get("/cockpit/{ticker}/state", response_model=CockpitStateResponse)
def get_cockpit_state(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitStateResponse:
    t = _guard_ticker(ticker, settings)
    state = _state_for(t, asof=asof, repo=repo)

    freshness = repo.fetch_matrix_source_freshness(
        ticker=t, market_date=state.market_date
    )
    return CockpitStateResponse(state=state, freshness=freshness)


@router.get("/cockpit/{ticker}/dealer", response_model=CockpitDealerResponse)
def get_cockpit_dealer(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitDealerResponse:
    t = _guard_ticker(ticker, settings)
    market_date = _tab_market_date_for(t, asof=asof, repo=repo)
    return CockpitDealerResponse(
        ticker=t,
        market_date=market_date,
        metrics=repo.fetch_cockpit_dealer_metrics(
            ticker=t, market_date=market_date
        ),
        points=repo.fetch_cockpit_dealer_points(
            ticker=t, market_date=market_date
        ),
    )


@router.get("/cockpit/{ticker}/surface", response_model=CockpitSurfaceResponse)
def get_cockpit_surface(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitSurfaceResponse:
    t = _guard_ticker(ticker, settings)
    market_date = _tab_market_date_for(t, asof=asof, repo=repo)
    skew, term = repo.fetch_cockpit_surface(ticker=t, market_date=market_date)
    return CockpitSurfaceResponse(
        ticker=t, market_date=market_date, skew=skew, term=term
    )


@router.get("/cockpit/{ticker}/flow-im", response_model=CockpitFlowImResponse)
def get_cockpit_flow_im(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitFlowImResponse:
    t = _guard_ticker(ticker, settings)
    market_date = _tab_market_date_for(t, asof=asof, repo=repo)
    return CockpitFlowImResponse(
        ticker=t,
        market_date=market_date,
        alerts=repo.fetch_cockpit_flow_alerts(ticker=t),
        implied_moves=repo.fetch_cockpit_implied_moves(
            ticker=t, market_date=market_date
        ),
    )


@router.get("/cockpit/{ticker}/vrp", response_model=CockpitVrpResponse)
def get_cockpit_vrp(
    ticker: str,
    asof: _date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CockpitVrpResponse:
    t = _guard_ticker(ticker, settings)
    market_date = _tab_market_date_for(t, asof=asof, repo=repo)
    return CockpitVrpResponse(
        ticker=t,
        market_date=market_date,
        points=repo.fetch_cockpit_vrp_points(ticker=t, market_date=market_date),
    )
