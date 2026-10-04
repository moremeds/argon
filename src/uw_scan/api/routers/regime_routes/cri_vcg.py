"""/regime CRI and VCG (EOD, scan, live, intraday, history)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.routers.regime_routes._shared import (
    _active_ws_source,
)
from uw_scan.api.schemas import (
    EMPTY_CRI_RESPONSE,
    EMPTY_VCG_RESPONSE,
    CriDailyEntry,
    CriDailyHistoryResponse,
    CriIntradayResponse,
    CriIntradaySession,
    CriLiveResponse,
    CriResponse,
    CriScanResponse,
    VcgDailyEntry,
    VcgDailyHistoryResponse,
    VcgIntradayResponse,
    VcgIntradaySession,
    VcgLiveResponse,
    VcgResponse,
    VcgScanResponse,
)
from uw_scan.config import Settings
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import LiveQuote, live_or_eod
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository

router = APIRouter()


@router.get("", response_model=CriResponse)
def get_regime(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CriResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo.schema)
    latest = snap_repo.fetch_latest()
    if latest is None:
        return EMPTY_CRI_RESPONSE.model_copy(deep=True)
    return CriResponse.model_validate({"status": "ok", **latest})


@router.post("/scan", status_code=202, response_model=CriScanResponse)
def trigger_cri_scan(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CriScanResponse:
    """Run a CRI scan synchronously off the warm store; persist a snapshot."""
    row_id = cri_scanner.run(repo.conn, schema=repo.schema)
    if row_id is None:
        return CriScanResponse(status="skipped", reason="thin_data")
    return CriScanResponse(status="ok", row_id=row_id)


# ─── VCG (live) ──────────────────────────────────────────────────


@router.get("/vcg", response_model=VcgResponse)
def get_vcg(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
) -> VcgResponse:
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo.schema)
    latest = snap_repo.fetch_latest(proxy=proxy.upper())
    if latest is None:
        empty = EMPTY_VCG_RESPONSE.model_copy(deep=True)
        empty.credit_proxy = proxy.upper()
        return empty
    return VcgResponse.model_validate({"status": "ok", **latest})


@router.post("/vcg/scan", status_code=202, response_model=VcgScanResponse)
def trigger_vcg_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
) -> VcgScanResponse:
    """Run a VCG scan synchronously off the warm store; persist a snapshot."""
    proxy_upper = proxy.upper()
    row_id = vcg_scanner.run(repo.conn, proxy=proxy_upper, schema=repo.schema)
    if row_id is None:
        return VcgScanResponse(status="skipped", proxy=proxy_upper, reason="thin_data")
    return VcgScanResponse(status="ok", proxy=proxy_upper, row_id=row_id)


# ─── CRI / VCG live (WS-quote-driven) ────────────────────────────


@router.get("/cri/live", response_model=CriLiveResponse)
def get_cri_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CriLiveResponse:
    """Request-time CRI with live quotes spliced as today's provisional
    close. Does NOT persist (the 5-min regime_live_scan job owns writes).
    Falls back to the latest basis='eod' snapshot when quotes are stale."""

    def live(quotes: dict[str, LiveQuote]) -> CriLiveResponse | None:
        if not quotes:
            return None
        payload = cri_scanner.run_live(repo.conn, schema=repo.schema, quotes=quotes)
        if payload is None:
            return None
        return CriLiveResponse.model_validate(
            {
                "status": "ok",
                "scan_time": datetime.now(timezone.utc).isoformat(),
                "active_source": _active_ws_source(repo),
                **payload,
            }
        )

    def eod() -> CriLiveResponse:
        snap_repo = CriSnapshotRepository(repo.conn, schema=repo.schema)
        latest = snap_repo.fetch_latest()
        if latest is None:
            return CriLiveResponse(basis="eod")
        return CriLiveResponse.model_validate(
            {"status": "ok", "basis": "eod", **latest}
        )

    return live_or_eod(repo, settings, live, eod)


@router.get("/cri/intraday", response_model=CriIntradayResponse)
def get_cri_intraday(
    repo: Annotated[Repository, Depends(get_repo)],
    sessions: int = Query(5, ge=1, le=20),
    rth_only: bool = Query(True),
) -> CriIntradayResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo.schema)
    raw = snap_repo.fetch_intraday_sessions(sessions=sessions, rth_only=rth_only)
    payload_sessions = [CriIntradaySession.model_validate(s) for s in raw]
    last_ts = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
    return CriIntradayResponse(sessions=payload_sessions, as_of=last_ts)


@router.get("/cri/history", response_model=CriDailyHistoryResponse)
def get_cri_history(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(90, ge=5, le=365),
) -> CriDailyHistoryResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo.schema)
    rows = snap_repo.fetch_daily_history(days=days)
    return CriDailyHistoryResponse(rows=[CriDailyEntry.model_validate(r) for r in rows])


@router.get("/vcg/live", response_model=VcgLiveResponse)
def get_vcg_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    proxy: str = Query("HYG"),
) -> VcgLiveResponse:
    proxy_upper = proxy.upper()

    def live(quotes: dict[str, LiveQuote]) -> VcgLiveResponse | None:
        if not quotes:
            return None
        payload = vcg_scanner.run_live(
            repo.conn, schema=repo.schema, quotes=quotes, proxy=proxy_upper
        )
        if payload is None:
            return None
        return VcgLiveResponse.model_validate(
            {
                "status": "ok",
                "scan_time": datetime.now(timezone.utc).isoformat(),
                "active_source": _active_ws_source(repo),
                **payload,
            }
        )

    def eod() -> VcgLiveResponse:
        snap_repo = VcgSnapshotRepository(repo.conn, schema=repo.schema)
        latest = snap_repo.fetch_latest(proxy=proxy_upper)
        if latest is None:
            empty = VcgLiveResponse(basis="eod")
            empty.credit_proxy = proxy_upper
            return empty
        return VcgLiveResponse.model_validate(
            {"status": "ok", "basis": "eod", **latest}
        )

    return live_or_eod(repo, settings, live, eod)


@router.get("/vcg/intraday", response_model=VcgIntradayResponse)
def get_vcg_intraday(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
    sessions: int = Query(5, ge=1, le=20),
    rth_only: bool = Query(True),
) -> VcgIntradayResponse:
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo.schema)
    raw = snap_repo.fetch_intraday_sessions(
        proxy=proxy.upper(), sessions=sessions, rth_only=rth_only
    )
    payload_sessions = [VcgIntradaySession.model_validate(s) for s in raw]
    last_ts = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
    return VcgIntradayResponse(
        credit_proxy=proxy.upper(), sessions=payload_sessions, as_of=last_ts
    )


@router.get("/vcg/history", response_model=VcgDailyHistoryResponse)
def get_vcg_history(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
    days: int = Query(90, ge=5, le=365),
) -> VcgDailyHistoryResponse:
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo.schema)
    rows = snap_repo.fetch_daily_history(proxy=proxy.upper(), days=days)
    return VcgDailyHistoryResponse(
        credit_proxy=proxy.upper(),
        rows=[VcgDailyEntry.model_validate(r) for r in rows],
    )
