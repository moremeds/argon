"""US rates mirror API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import RatesSnapshotResponse
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/rates", tags=["rates"])


@router.get("/snapshot", response_model=RatesSnapshotResponse)
def rates_snapshot(repo: Repository = Depends(get_repo)) -> RatesSnapshotResponse:
    row = repo.fetch_latest_rates_snapshot()
    if row is None:
        raise HTTPException(status_code=404, detail="rates snapshot not computed")
    return RatesSnapshotResponse.model_validate(row["payload"])
