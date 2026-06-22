from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.models.vrp import (
    VrpBacktestResponse,
    VrpBacktestRow,
    VrpCandidateRow,
    VrpCandidatesResponse,
    VrpPaperPositionRow,
    VrpPaperResponse,
)
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/vrp")


@router.get("/candidates", response_model=VrpCandidatesResponse)
def get_vrp_candidates(repo: Repository = Depends(get_repo)) -> VrpCandidatesResponse:
    rows = repo.fetch_vrp_candidates()
    return VrpCandidatesResponse(candidates=[VrpCandidateRow(**r) for r in rows])


@router.get("/backtest", response_model=VrpBacktestResponse)
def get_vrp_backtest(
    hold_days: int | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> VrpBacktestResponse:
    rows = repo.fetch_vrp_backtest_results(hold_days=hold_days)
    return VrpBacktestResponse(results=[VrpBacktestRow(**r) for r in rows])


@router.get("/paper", response_model=VrpPaperResponse)
def get_vrp_paper(
    status: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> VrpPaperResponse:
    rows = repo.fetch_vrp_paper_positions(status=status)
    total = sum(
        (
            Decimal(str(r["realized_pnl"]))
            for r in rows
            if r.get("realized_pnl") is not None
        ),
        Decimal(0),
    )
    return VrpPaperResponse(
        positions=[VrpPaperPositionRow(**r) for r in rows],
        total_realized_pnl=total,
    )
