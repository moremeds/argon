"""/regime vol backdrop, dispersion and VRP harvest verdicts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import (
    DispersionResponse,
    VolBackdropResponse,
    VrpHarvestResponse,
    VrpHarvestVerdict,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.vol_index_repository import VolIndexRepository

router = APIRouter()


# ─── Vol backdrop ────────────────────────────────────────────────

_VOL_BACKDROP_SYMBOLS = ("VIX", "VIX3M", "VVIX", "COR1M")


@router.get("/vol-backdrop", response_model=VolBackdropResponse)
def get_vol_backdrop(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(90, ge=5, le=365),
) -> VolBackdropResponse:
    v = VolIndexRepository(repo.conn, schema=repo.schema)
    multi = v.fetch_multi_history(_VOL_BACKDROP_SYMBOLS, days=days)

    series = {
        sym: [{"date": r["trade_date"], "close": r["close"]} for r in rows]
        for sym, rows in multi.items()
    }

    latest_vix = series["VIX"][-1]["close"] if series.get("VIX") else None
    latest_vix3m = series["VIX3M"][-1]["close"] if series.get("VIX3M") else None
    ratio = None
    state = None
    as_of = None
    if latest_vix is not None and latest_vix3m:
        ratio = latest_vix / latest_vix3m
        state = "contango" if ratio < 1 else "backwardation"
        as_of = series["VIX"][-1]["date"]

    return VolBackdropResponse(
        series=series,
        term_structure_ratio=ratio,
        term_structure_state=state,
        as_of=as_of,
    )


@router.get("/dispersion", response_model=DispersionResponse)
def get_dispersion(
    repo: Annotated[Repository, Depends(get_repo)],
) -> DispersionResponse:
    """Correlation/dispersion CONTEXT for the CRI view (descriptive, not a signal).

    COR1M 20yr percentile + VIX/COR1M ratio and its trailing-252 z-score. See
    docs/research/2026-07-19-dispersion-signals-eval.md — low correlation is NOT
    a warning; this is regime context only."""
    v = VolIndexRepository(repo.conn, schema=repo.schema)
    return DispersionResponse(**v.fetch_dispersion_context())


@router.get("/vrp-harvest", response_model=VrpHarvestResponse)
def get_vrp_harvest(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VrpHarvestResponse:
    """Per-bucket VRP harvest verdicts (Spec B). Read-only over the verdict
    store written by the nightly vrp_markout job."""
    rows = repo.fetch_vrp_harvest_verdicts()
    return VrpHarvestResponse(verdicts=[VrpHarvestVerdict(**r) for r in rows])
