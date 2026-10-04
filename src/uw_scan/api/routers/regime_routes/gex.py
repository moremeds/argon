"""/regime GEX, market tide and top net impact (live)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings, get_uw_client
from uw_scan.api.routers.regime_routes._shared import (
    _assemble_history,
    _is_market_open_now,
)
from uw_scan.api.schemas import (
    EMPTY_GEX_RESPONSE,
    GexHistoryEntry,
    GexIntradayResponse,
    GexIntradaySession,
    GexResponse,
    GexScanResponse,
    MarketTideResponse,
    MarketTideSentiment,
    MarketTideSession,
    TopNetImpactResponse,
    TopNetImpactRow,
)
from uw_scan.config import Settings
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.repository import Repository

router = APIRouter()


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


@router.get("/gex/intraday", response_model=GexIntradayResponse)
def get_gex_intraday(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
    sessions: int = Query(5, ge=1, le=20),
    rth_only: bool = Query(True),
) -> GexIntradayResponse:
    """Last N RTH sessions of intraday gex_snapshots for ``ticker``.

    Drives the intraday line chart on the GEX tab. Sessions are ET-anchored
    (UTC `data_date` straddles sessions). Empty `sessions` array is a valid
    response when no rows exist for the ticker.
    """
    t = ticker.upper()
    raw = repo.fetch_intraday_sessions(ticker=t, sessions=sessions, rth_only=rth_only)
    payload_sessions = [GexIntradaySession.model_validate(s) for s in raw]
    last_ts = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
    return GexIntradayResponse(
        ticker=t,
        sessions=payload_sessions,
        as_of=last_ts,
    )


@router.get("/market-tide", response_model=MarketTideResponse)
def get_market_tide(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: int = Query(5, ge=1, le=30),
) -> MarketTideResponse:
    """Last N sessions of market-wide 5-min net options premium + live spot.

    Reads market_tide_snapshots (worker-captured intraday + backfilled history).
    Drives the regime Market Tide tab. Empty `sessions` is a valid response.
    """
    from uw_scan.storage.market_tide_snapshot_repository import (
        MarketTideSnapshotRepository,
    )

    tide_repo = MarketTideSnapshotRepository(repo.conn, schema=repo.schema)
    raw = tide_repo.fetch_sessions(sessions=sessions)
    payload_sessions = [MarketTideSession.model_validate(s) for s in raw]
    last_ts = None
    sentiment = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
        from uw_scan.reports.market_tide_sentiment import compute_sentiment

        sentiment = MarketTideSentiment(
            **compute_sentiment(payload_sessions[-1].points).to_dict()
        )
    return MarketTideResponse(
        sessions=payload_sessions,
        spot_ticker=settings.market_tide_spot_ticker,
        as_of=last_ts,
        market_open=_is_market_open_now(),
        sentiment=sentiment,
    )


@router.get("/top-net-impact", response_model=TopNetImpactResponse)
def get_top_net_impact(
    repo: Annotated[Repository, Depends(get_repo)],
    date_str: str | None = Query(None, alias="date"),
    limit: int = Query(40, ge=1, le=100),
) -> TopNetImpactResponse:
    """Top tickers by net option premium for one session (default: latest).

    Reads top_net_impact_snapshots (worker-captured every 15 min through RTH).
    Rows sorted by net_premium DESC; each carries its per-update rank_change.
    """
    from datetime import date as _date

    from uw_scan.storage.top_net_impact_repository import TopNetImpactRepository

    parsed: _date | None = None
    if date_str:
        try:
            parsed = _date.fromisoformat(date_str)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="bad date") from exc

    tni_repo = TopNetImpactRepository(repo.conn, schema=repo.schema)
    resolved, rows = tni_repo.fetch_latest(data_date=parsed, limit=limit)
    return TopNetImpactResponse(
        rows=[TopNetImpactRow.model_validate(r) for r in rows],
        data_date=resolved,
    )


@router.post("/gex/scan", response_model=GexScanResponse)
def trigger_gex_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    uw_client: Annotated[UwClient, Depends(get_uw_client)],
    ticker: str = Query("SPX"),
) -> GexScanResponse:
    """Run a GEX scan synchronously against UW, persist it, and return the row.

    200, not 202: the scan has finished and been written when this returns.
    """
    t = ticker.upper()
    row_id = gex_scanner.run(uw_client, repo, ticker=t)
    return GexScanResponse(ticker=t, row_id=row_id)
