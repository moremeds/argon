"""/api/watchlist — grid GET, CRUD POST/DELETE/PATCH."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import (
    GammaBlock,
    PositioningBlock,
    QueueStatus,
    QueueSummary,
    ReturnsBlock,
    SetupBlock,
    SkewBlock,
    WatchlistCard,
    WatchlistMutation,
    WatchlistPatch,
    WatchlistResponse,
)
from uw_scan.storage.repository import Repository, WatchlistCardRow

router = APIRouter()


def _card_to_response(row: WatchlistCardRow) -> WatchlistCard:
    """Map a joined watchlist_card + watchlist row to the API shape."""
    queue = None
    if row.active_job_id is not None:
        queue = QueueStatus(
            job_id=str(row.active_job_id),
            status=row.active_job_status,
            queue_position=row.active_job_queue_position,
            requested_at=row.active_job_requested_at,
            started_at=row.active_job_started_at,
        )
    return WatchlistCard(
        ticker=row.ticker,
        sector=row.sector,
        pinned=row.pinned,
        sort_rank=row.sort_rank,
        spot=row.spot,
        spot_quoted_at=row.spot_quoted_at,
        spot_source=row.spot_source,
        scanned_at=row.scanned_at,
        iv_atm=row.iv_atm,
        iv_rank=row.iv_rank,
        market_cap=row.market_cap,
        aum=row.aum,
        setup=SetupBlock(
            type=row.setup_type,
            direction=row.setup_direction,
            score=row.setup_score,
        ),
        aggression_pct=row.aggression_pct,
        returns=ReturnsBlock(d1=row.ret_1d, w1=row.ret_1w, d30=row.ret_30d),
        gamma=GammaBlock(
            flip_distance=row.gex_flip_distance,
            flip_price=row.gex_flip_price,
            per_1pct_move=row.gex_per_1pct_move,
            max_strike=row.max_gex_strike,
            expiring_pct=row.gex_expiring_pct,
            expiring_date=row.gex_expiring_date,
        ),
        skew=SkewBlock(rr25d_30dte=row.skew_25d_30dte),
        positioning=PositioningBlock(
            call_oi=row.call_oi_total,
            put_oi=row.put_oi_total,
            pcr_oi=row.pcr_oi,
            pcr_vol=row.pcr_vol,
            pcr_delta_30d=row.pcr_delta_30d,
        ),
        queue=queue,
    )


@router.get("/watchlist", response_model=WatchlistResponse)
def get_watchlist(
    sector: str | None = Query(None),
    setup: str | None = Query(
        None,
        description="e.g. 'C-bull', 'C-bear', 'F-MULTI', 'NEUTRAL'",
    ),
    fresh_within_minutes: int | None = Query(None, ge=1),
    repo: Repository = Depends(get_repo),
) -> WatchlistResponse:
    rows, queue = repo.list_watchlist_cards_with_queue_summary()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=fresh_within_minutes)
        if fresh_within_minutes
        else None
    )

    setup_type: str | None = None
    setup_dir: str | None = None
    if setup is not None:
        if setup.upper() != "NEUTRAL":
            if "-" in setup:
                t, d = setup.split("-", 1)
                setup_type, setup_dir = t.upper(), d.lower()
            else:
                setup_type = setup.upper()

    out: list[WatchlistCard] = []
    for r in rows:
        if sector and r.sector != sector:
            continue
        # `scanned_at` is None for tickers that haven't been scanned yet
        # (LEFT JOIN from watchlist). A fresh-within filter naturally
        # excludes them; an unfiltered request keeps them as placeholders.
        if cutoff is not None and (r.scanned_at is None or r.scanned_at < cutoff):
            continue
        if setup is not None:
            if setup.upper() == "NEUTRAL":
                if r.setup_type is not None:
                    continue
            else:
                if r.setup_type != setup_type:
                    continue
                if setup_dir and r.setup_direction != setup_dir:
                    continue
        out.append(_card_to_response(r))

    scanned_times = [c.scanned_at for c in out if c.scanned_at is not None]
    return WatchlistResponse(
        scanned_at_min=min(scanned_times, default=None),
        scanned_at_max=max(scanned_times, default=None),
        scheduler_lag_seconds=None,
        queue=QueueSummary(
            total=queue.total,
            queued=queue.queued,
            running=queue.running,
            oldest_requested_at=queue.oldest_requested_at,
        ),
        tickers=out,
    )


@router.post("/watchlist", status_code=201)
def post_watchlist(
    body: WatchlistMutation,
    repo: Repository = Depends(get_repo),
) -> dict[str, object]:
    repo.add_watchlist_ticker(
        ticker=body.ticker.upper(),
        sector=body.sector,
        notes=body.notes,
        sort_rank=body.sort_rank,
        pinned=body.pinned,
    )
    return {"ok": True, "ticker": body.ticker.upper()}


@router.delete("/watchlist/{ticker}", status_code=204)
def delete_watchlist(ticker: str, repo: Repository = Depends(get_repo)) -> None:
    repo.soft_delete_watchlist_ticker(ticker.upper())


@router.patch("/watchlist/{ticker}")
def patch_watchlist(
    ticker: str,
    body: WatchlistPatch,
    repo: Repository = Depends(get_repo),
) -> dict[str, object]:
    repo.patch_watchlist_ticker(
        ticker.upper(),
        sector=body.sector,
        notes=body.notes,
        pinned=body.pinned,
        sort_rank=body.sort_rank,
    )
    return {"ok": True, "ticker": ticker.upper()}
