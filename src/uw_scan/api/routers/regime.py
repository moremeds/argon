"""/regime — GEX, CRI, and VCG (all live)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.schemas import (
    EMPTY_CRI_RESPONSE,
    EMPTY_GEX_RESPONSE,
    EMPTY_VCG_RESPONSE,
    CriResponse,
    CriScanResponse,
    GexHistoryEntry,
    GexResponse,
    VcgResponse,
    VcgScanResponse,
    VolBackdropResponse,
)
from uw_scan.config import Settings
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import gex as gex_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

router = APIRouter(prefix="/regime")

# Tickers whose spot history is sourced from the parquet lake. UW
# /ohlc/1d is tier-blocked for indices; massive doesn't quote indices.
_SPOT_FROM_LAKE = {"SPX"}


def _is_market_open_now() -> bool:
    """Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _assemble_history(repo: Repository, ticker: str, days: int = 90) -> list[dict]:
    """Join greek_exposure_daily × (vol_index_daily | daily_ohlc) × flip history."""
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    gex_rows = g.fetch_history(ticker, days=days)
    if not gex_rows:
        return []

    if ticker in _SPOT_FROM_LAKE:
        v = VolIndexRepository(repo.conn, schema=repo._schema)
        spot_rows = v.fetch_history(ticker, days=days)
        spot_by_date = {r["trade_date"]: r["close"] for r in spot_rows}
    else:
        ohlc = repo.list_daily_ohlc(ticker, limit=days)
        spot_by_date = {r.date: float(r.close) for r in ohlc}

    flip_by_date = repo.fetch_flip_strike_history(ticker=ticker, limit=days)

    return [
        {
            "date": row["trade_date"].isoformat(),
            "net_gex": row["net_gex"],
            "net_dex": row["net_dex"],
            "gex_flip": flip_by_date.get(row["trade_date"]),
            "spot": spot_by_date.get(row["trade_date"]),
        }
        for row in gex_rows
    ]


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


@router.post("/gex/scan", status_code=202)
def trigger_gex_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    ticker: str = Query("SPX"),
) -> dict:
    """Run a GEX scan synchronously against UW and persist."""
    uw_client = UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )
    try:
        row_id = gex_scanner.run(uw_client, repo, ticker=ticker.upper())
    finally:
        uw_client.close()
    return {
        "status": "queued",
        "scanner": "gex",
        "ticker": ticker.upper(),
        "row_id": row_id,
    }


# ─── Vol backdrop ────────────────────────────────────────────────

_VOL_BACKDROP_SYMBOLS = ("VIX", "VIX3M", "VVIX", "COR1M")


@router.get("/vol-backdrop", response_model=VolBackdropResponse)
def get_vol_backdrop(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(90, ge=5, le=365),
) -> VolBackdropResponse:
    v = VolIndexRepository(repo.conn, schema=repo._schema)
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


# ─── CRI (live) ──────────────────────────────────────────────────


@router.get("", response_model=CriResponse)
def get_regime(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CriResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    if latest is None:
        return EMPTY_CRI_RESPONSE.model_copy(deep=True)
    return CriResponse.model_validate({"status": "ok", **latest})


@router.post("/scan", status_code=202, response_model=CriScanResponse)
def trigger_cri_scan(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CriScanResponse:
    """Run a CRI scan synchronously off the warm store; persist a snapshot."""
    row_id = cri_scanner.run(repo.conn, schema=repo._schema)
    if row_id is None:
        return CriScanResponse(status="skipped", reason="thin_data")
    return CriScanResponse(status="ok", row_id=row_id)


# ─── VCG (live) ──────────────────────────────────────────────────


@router.get("/vcg", response_model=VcgResponse)
def get_vcg(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
) -> VcgResponse:
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo._schema)
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
    row_id = vcg_scanner.run(repo.conn, proxy=proxy_upper, schema=repo._schema)
    if row_id is None:
        return VcgScanResponse(status="skipped", proxy=proxy_upper, reason="thin_data")
    return VcgScanResponse(status="ok", proxy=proxy_upper, row_id=row_id)
