"""/regime — GEX, CRI, and VCG (all live)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.models.canary import (
    CanaryHistoryResponse,
    CanaryHistoryRow,
    CanaryLatestResponse,
    CanaryValidationResponse,
)
from uw_scan.api.schemas import (
    EMPTY_CRI_RESPONSE,
    EMPTY_DEALER_REGIME_RESPONSE,
    EMPTY_GEX_RESPONSE,
    EMPTY_VCG_RESPONSE,
    ClosestLevel,
    CriResponse,
    CriScanResponse,
    DealerRegimeResponse,
    DealerRegimeSignal,
    GammaDecayBucket,
    GexHistoryEntry,
    GexIntradayResponse,
    GexIntradaySession,
    GexResponse,
    VcgResponse,
    VcgScanResponse,
    VolBackdropResponse,
)
from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION as CANARY_COMPOSITE_VERSION,
)
from uw_scan.cards.dealer_regime import compute_dealer_regime, gather_inputs
from uw_scan.config import Settings
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import gex as gex_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
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
    """Join greek_exposure_daily × (vol_index_daily | daily_ohlc) × gex_snapshots.

    The per-day gex_snapshots lookup carries flip + iv_30d + vol_pc + bias
    in one round-trip via ``fetch_metrics_history``. Days without a
    snapshot still surface (net_gex / net_dex / spot from the upstream
    tables); the snapshot-derived columns just come through as None so
    the table renders ``"---"`` per cell instead of dropping the row.

    Returned list is ASC by date — the SVG chart in HistoryChart.tsx
    consumes this directly with ``xScale(i)``, so flipping the order
    here would draw time right-to-left. The history table sorts
    client-side and defaults to date DESC.
    """
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

    metrics_by_date = repo.fetch_metrics_history(ticker=ticker, limit=days)

    return [
        {
            "date": row["trade_date"].isoformat(),
            "net_gex": row["net_gex"],
            "net_dex": row["net_dex"],
            "gex_flip": (metrics_by_date.get(row["trade_date"]) or {}).get("flip"),
            "spot": spot_by_date.get(row["trade_date"]),
            "atm_iv": (metrics_by_date.get(row["trade_date"]) or {}).get("iv_30d"),
            "vol_pc": (metrics_by_date.get(row["trade_date"]) or {}).get("vol_pc"),
            "bias": (metrics_by_date.get(row["trade_date"]) or {}).get("bias"),
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
    raw = repo.fetch_intraday_sessions(
        ticker=t, sessions=sessions, rth_only=rth_only
    )
    payload_sessions = [GexIntradaySession.model_validate(s) for s in raw]
    last_ts = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
    return GexIntradayResponse(
        ticker=t,
        sessions=payload_sessions,
        as_of=last_ts,
    )


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


# ─── Dealer regime (per-ticker, live) ─────────────────────────────


@router.get("/dealer", response_model=DealerRegimeResponse)
def get_dealer_regime(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query(..., min_length=1, max_length=10),
) -> DealerRegimeResponse:
    """Per-ticker dealer Greek regime — feeds the Magnet/Gamma summary bar
    and the Volatility tab regime panel. Uses the same `gather_inputs`
    helper the report assembler uses so both paths see the same upstream.
    """
    t = ticker.upper()
    inputs = gather_inputs(repo, ticker=t)
    if inputs["run_id"] == 0:
        empty = EMPTY_DEALER_REGIME_RESPONSE.model_copy(deep=True)
        empty.ticker = t
        return empty

    out = compute_dealer_regime(
        ticker=t,
        spot=inputs["spot"],
        net_gex=inputs["net_gex"],
        prev_close_net_gex=inputs["prev_close_net_gex"],
        per_expiry_vanna=inputs["per_expiry_vanna"],
        per_expiry_charm=inputs["per_expiry_charm"],
        strike_gex_curve=inputs["strike_gex_curve"],
        levels=inputs["levels"],
        today=inputs["today"],
    )

    return DealerRegimeResponse(
        status="ok",
        ticker=t,
        scan_time="",
        spot=out.spot,
        net_gex=out.net_gex,
        prev_close_net_gex=out.prev_close_net_gex,
        signal=DealerRegimeSignal(
            label=out.signal.label,
            score=out.signal.score,
            gamma_score=out.signal.gamma_score,
            vanna_score=out.signal.vanna_score,
            charm_score=out.signal.charm_score,
            headline=out.signal.headline,
            subtitle=out.signal.subtitle,
        ),
        closest_levels=[
            ClosestLevel(
                label=lv.label,
                direction=lv.direction,
                role=lv.role,
                strike=lv.strike,
                distance_pct=lv.distance_pct,
                gamma=lv.gamma,
                rank_kind=lv.rank_kind,
            )
            for lv in out.closest_levels
        ],
        odte_gex=out.odte_gex,
        odte_share_pct=out.odte_share_pct,
        gamma_decay=[
            GammaDecayBucket(
                dte=b.dte,
                expiry=b.expiry,
                net_gex=b.net_gex,
                share_pct=b.share_pct,
                gross_abs_gex=b.gross_abs_gex,
                gross_share_pct=b.gross_share_pct,
            )
            for b in out.gamma_decay
        ],
    )


# ─── 5% Canary (live) ────────────────────────────────────────────


@router.get("/canary", response_model=CanaryLatestResponse)
def get_canary_latest(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CanaryLatestResponse:
    snap_repo = CanarySnapshotRepository(repo.conn, schema=repo._schema)
    row = snap_repo.fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="no canary snapshot at current composite_version",
        )
    return CanaryLatestResponse(
        data_date=row["data_date"],
        composite_version=CANARY_COMPOSITE_VERSION,
        score_form=row["score_form"],
        score=float(row["score"]),
        raw_score=float(row["raw_score"]),
        band=row["band"],
        tactical_score=float(row["tactical_score"]),
        structural_score=float(row["structural_score"]),
        speed_score=int(row["speed_score"]),
        warning_state=row["warning_state"],
        payload=row["payload"],
    )


@router.get("/canary/history", response_model=CanaryHistoryResponse)
def get_canary_history(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(30, ge=1, le=365),
) -> CanaryHistoryResponse:
    snap_repo = CanarySnapshotRepository(repo.conn, schema=repo._schema)
    rows = snap_repo.fetch_history(
        composite_version=CANARY_COMPOSITE_VERSION, days=days
    )
    return CanaryHistoryResponse(
        rows=[
            CanaryHistoryRow(
                data_date=r["data_date"],
                score=float(r["score"]),
                band=r["band"],
                tactical_score=float(r["tactical_score"]),
                structural_score=float(r["structural_score"]),
                speed_score=int(r["speed_score"]),
                warning_state=r["warning_state"],
                spx_close=(
                    float(r["spx_close"]) if r.get("spx_close") is not None else None
                ),
            )
            for r in rows
        ]
    )


def _fmt_metric(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError) as exc:
        _ = repr(exc)
        return str(value)


def _render_canary_validation_markdown(summary: dict) -> str:
    daily = summary.get("daily_aucs", {})
    events = summary.get("events", {})
    bands = summary.get("band_distribution", {})
    btd = events.get("buy_the_dip", {})
    cc = events.get("confirmed_canary", {})
    lines = [
        "# 5% Canary validation",
        "",
        f"Score form: `{summary.get('score_form', 'unknown')}`",
        "",
        "## Daily AUCs",
        f"- up5d_2pct: {_fmt_metric(daily.get('up5d_2pct'))}",
        f"- up20d_5pct: {_fmt_metric(daily.get('up20d_5pct'))}",
        f"- up60d_10pct: {_fmt_metric(daily.get('up60d_10pct'))}",
        "",
        "## Band distribution",
        f"- NONE: {bands.get('NONE', 0)}",
        f"- WATCH: {bands.get('WATCH', 0)}",
        f"- BUY: {bands.get('BUY', 0)}",
        f"- STRONG_BUY: {bands.get('STRONG_BUY', 0)}",
        "",
        "## Event validation",
        f"- Buy The Dip events: {btd.get('n_events', 0)}, "
        f"median 42d drawup: {_fmt_metric(btd.get('median_fwd_42d_drawup'))}",
        f"- Confirmed Canary events: {cc.get('n_events', 0)}, "
        f"median 42d drawdown: {_fmt_metric(cc.get('median_fwd_42d_drawdown'))}",
    ]
    return "\n".join(lines)


@router.get("/canary/validation", response_model=CanaryValidationResponse)
def get_canary_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CanaryValidationResponse:
    """v0.4 patch I4 + C6: use the existing `find_latest_run` (which already
    filters on `completed_at IS NOT NULL`) and post-filter for the winning
    form in summary JSON. composite_version is stringified at the DB boundary.
    """
    bt_repo = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    row = bt_repo.find_latest_run(
        indicator="canary",
        composite_version=str(CANARY_COMPOSITE_VERSION),
    )
    if row is None or not row.get("summary", {}).get("is_winning_form"):
        raise HTTPException(
            status_code=503,
            detail=(
                "no completed canary backtest at current composite_version "
                "(or row missing is_winning_form)"
            ),
        )
    summary = row["summary"]
    return CanaryValidationResponse(
        run_id=row["id"],
        composite_version=int(row["composite_version"]),
        score_form=summary.get("score_form", "linear"),
        summary=summary,
        rendered_markdown=_render_canary_validation_markdown(summary),
    )
