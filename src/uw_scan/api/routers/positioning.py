"""/api/positioning — read-only surface over the banked ``uw_positioning`` table.

- ``GET /positioning/screener`` — one row per active-watchlist ticker with the
  squeeze / insider / analyst / pre-ER signal labels.
- ``GET /positioning/{ticker}`` — the full per-ticker snapshot for the stock card.

Zero UW fetch — everything is served from the daily-banked warm store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends

from uw_scan.api.deps import get_repo
from uw_scan.models import PositioningScreenerResponse, PositioningSnapshot
from uw_scan.reports.positioning import build_screener_row, build_snapshot
from uw_scan.storage.repository import Repository

router = APIRouter()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _spot_for(repo: Repository, ticker: str) -> Decimal | None:
    card = repo.get_watchlist_card(ticker)
    return card.spot if card is not None else None


@router.get("/positioning/screener", response_model=PositioningScreenerResponse)
def get_positioning_screener(
    repo: Repository = Depends(get_repo),
) -> PositioningScreenerResponse:
    raw = repo.list_uw_positioning_latest()
    rows = [build_screener_row(r) for r in raw]
    # Highest squeeze score first, then most-recent snapshot, then ticker.
    rows.sort(
        key=lambda r: (
            -(r.squeeze_score or 0),
            r.snapshot_date.toordinal() if r.snapshot_date else 0,
            r.ticker,
        )
    )
    as_of = max((r.snapshot_date for r in rows if r.snapshot_date), default=None)
    return PositioningScreenerResponse(rows=rows, generated_at=_now_utc(), as_of=as_of)


@router.get("/positioning/{ticker}", response_model=PositioningSnapshot)
def get_positioning(
    ticker: str, repo: Repository = Depends(get_repo)
) -> PositioningSnapshot:
    t = ticker.upper()
    row = repo.get_uw_positioning(t)
    return build_snapshot(t, row, _spot_for(repo, t))
