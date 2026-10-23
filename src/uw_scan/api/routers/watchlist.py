"""/api/watchlist — grid GET, CRUD POST/DELETE/PATCH."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from uw_scan.api.deps import get_repo, get_settings, get_spots_broadcaster
from uw_scan.api.live_spots import SpotsBroadcaster, spots_response, sse_events
from uw_scan.config import Settings
from uw_scan.models.watchlist import (
    GammaBlock,
    PositioningBlock,
    QueueStatus,
    QueueSummary,
    ReturnsBlock,
    SetupBlock,
    SkewBlock,
    WatchlistCard,
    WatchlistChainInfo,
    WatchlistChainsResponse,
    WatchlistMutation,
    WatchlistPatch,
    WatchlistResponse,
    WatchlistSpotsResponse,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.rows import WatchlistCardRow
from uw_scan.storage.watchlist_chain import WatchlistChainRepository
from uw_scan.watchlist_taxonomy import LAYERS, layer_chains_for, layer_for_chain

router = APIRouter()


def _sync_chains(repo: Repository, ticker: str) -> None:
    """Keep one ticker's chain memberships true after a watchlist mutation.

    Without this, adding a ticker left it in no chain at all (invisible to every
    filter until somebody ran the seed script by hand), and changing a ticker's
    sector left the old inherited row behind — which is how NOV kept answering
    the Healthcare filter after it was corrected to Energy.
    """
    WatchlistChainRepository(repo.conn, schema=repo._schema).sync_ticker_memberships(
        ticker, layer_chains_for(ticker), layer_for_chain()
    )
    # WatchlistChainRepository leaves commits to its caller (the seed script does
    # the same). The watchlist write above has already committed, so this is a
    # second commit rather than one transaction — a ticker can briefly hold its
    # new sector and its old chains. Both writes are idempotent and a re-run
    # converges, which is worth more here than reworking the commit convention
    # every other watchlist mutation already follows.
    repo.conn.commit()


def _card_to_response(
    row: WatchlistCardRow, chains: list[str] | None = None
) -> WatchlistCard:
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
        chains=chains or [],
        pinned=row.pinned,
        hot=bool(row.hot),
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
    chain: str | None = Query(
        None,
        description="Industry chain (uw_scan.watchlist_chain). Selects on "
        "many-to-many membership, so a ticker in several chains matches each.",
    ),
    setup: str | None = Query(
        None,
        description="e.g. 'C-bull', 'C-bear', 'F-MULTI', 'NEUTRAL'",
    ),
    fresh_within_minutes: int | None = Query(None, ge=1),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> WatchlistResponse:
    rows, queue = repo.list_watchlist_cards_with_queue_summary()
    # One query for the whole payload; per-card lookups would be ~170 round
    # trips to render a single dashboard.
    chains_by_ticker = WatchlistChainRepository(
        repo.conn, schema=repo._schema
    ).chains_by_ticker()
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
        if chain and chain not in chains_by_ticker.get(r.ticker, ()):
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
        out.append(_card_to_response(r, chains_by_ticker.get(r.ticker)))

    scanned_times = [c.scanned_at for c in out if c.scanned_at is not None]
    # Hot-slots meter reflects ALL flagged tickers (pre sector/setup filter) so
    # the "N / max" count is stable regardless of the current grid filter.
    hot_count = sum(1 for r in rows if bool(r.hot))
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
        hot_count=hot_count,
        hot_max=settings.full_scan_hot_max_tickers,
        tickers=out,
    )


@router.get("/watchlist/queue", response_model=QueueSummary)
def get_watchlist_queue(repo: Repository = Depends(get_repo)) -> QueueSummary:
    """Lightweight queue snapshot for the dashboard's QueueProgress widget.

    Returns only the rescan-queue summary — no card joins, no meta. Designed
    for the 2.5s polling loop in QueueProgress so the dashboard doesn't
    refetch the full watchlist payload every tick.
    """
    q = repo.get_rescan_queue_summary()
    return QueueSummary(
        total=q.total,
        queued=q.queued,
        running=q.running,
        oldest_requested_at=q.oldest_requested_at,
    )


@router.get("/watchlist/spots", response_model=WatchlistSpotsResponse)
def get_watchlist_spots(
    repo: Repository = Depends(get_repo),
) -> WatchlistSpotsResponse:
    """Live spot snapshot (ticker, spot, quoted_at, source) — the lightweight
    projection the WS consumer (xenon primary / massive fallback) rewrites on
    every flush. The dashboard streams it from /watchlist/spots/stream."""
    return spots_response(repo.list_watchlist_spots())


# Not in the OpenAPI schema: an SSE body can't be typed there. Each `data:`
# event is a WatchlistSpotsResponse JSON holding only the tickers that changed
# (the first event after connect holds all of them).
@router.get("/watchlist/spots/stream", include_in_schema=False)
async def stream_watchlist_spots(
    broadcaster: SpotsBroadcaster = Depends(get_spots_broadcaster),
) -> StreamingResponse:
    return StreamingResponse(
        sse_events(broadcaster),
        media_type="text/event-stream",
        # no-transform: Next's rewrite proxy (and Cloudflare) would otherwise
        # gzip the stream for any browser that accepts gzip, and gzip holds
        # every event until its buffer fills — the page would see nothing.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/watchlist/chains", response_model=WatchlistChainsResponse)
def get_watchlist_chains(
    repo: Repository = Depends(get_repo),
) -> WatchlistChainsResponse:
    """The filter rail: every chain, its layer, and live member count.

    Declared order is preserved from the taxonomy module — the rail leads with
    Index & Macro and M7 deliberately, so alphabetising here would silently
    undo that.
    """
    counts = WatchlistChainRepository(repo.conn, schema=repo._schema).counts_by_chain()
    return WatchlistChainsResponse(
        chains=[
            WatchlistChainInfo(
                layer=layer.key,
                layer_name=layer.name,
                focus=layer.focus,
                chain=chain,
                count=counts.get(chain, 0),
            )
            for layer in LAYERS
            for chain in layer.chains
        ]
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
    _sync_chains(repo, body.ticker.upper())
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
        hot=body.hot,
        sort_rank=body.sort_rank,
    )
    # Only a sector change can invalidate memberships. Toggling pinned/hot must
    # not pay for a membership rewrite.
    if body.sector is not None:
        _sync_chains(repo, ticker.upper())
    return {"ok": True, "ticker": ticker.upper()}
