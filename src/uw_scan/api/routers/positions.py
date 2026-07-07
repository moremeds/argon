"""/positions — VRP-macro trade-lifecycle read-back (issue #223).

Lists every entry-capture cohort (auto + button, open + expired) as a portfolio
with entry credit, latest mark, running P&L, and expiry status. Read-only over
the warm store; the capture/birth side lives in the worker + /regime endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models.vrp_lifecycle import (
    VrpMacroPositionDetail,
    VrpMacroPositionsResponse,
)
from uw_scan.reports.vrp_lifecycle import (
    build_position_detail,
    build_positions_response,
)
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/positions")


def _today(settings: Settings):
    return datetime.now(ZoneInfo(settings.rth_tz)).date()


@router.get("", response_model=VrpMacroPositionsResponse)
def list_positions(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> VrpMacroPositionsResponse:
    """All VRP-macro cohorts as a portfolio (newest first). Empty when none captured."""
    rows = repo.list_vrp_macro_entry_lifecycle(name=name, limit=limit)
    return build_positions_response(rows, today=_today(settings))


@router.get("/{entry_id}", response_model=VrpMacroPositionDetail)
def get_position(
    entry_id: int,
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroPositionDetail:
    """One cohort with its full per-mark P&L curve for the SVG chart."""
    headers = repo.list_vrp_macro_entry_lifecycle(entry_id=entry_id, limit=1)
    if not headers:
        raise HTTPException(status_code=404, detail=f"entry {entry_id} not found")
    series = repo.fetch_vrp_macro_entry_pnl_series(entry_id)
    return build_position_detail(headers[0], series, today=_today(settings))
