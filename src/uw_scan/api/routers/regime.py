"""/regime — GEX, CRI, and VCG (all live)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
from uw_scan.api.models.vrp_macro_entry import (
    VrpMacroEntryCaptureResponse,
    VrpMacroEntryLeg,
    VrpMacroEntryPreview,
)
from uw_scan.api.schemas import (
    EMPTY_CRI_RESPONSE,
    EMPTY_DEALER_REGIME_RESPONSE,
    EMPTY_GEX_RESPONSE,
    EMPTY_GRG_RESPONSE,
    EMPTY_VCG_RESPONSE,
    ClosestLevel,
    CriDailyEntry,
    CriDailyHistoryResponse,
    CriIntradayResponse,
    CriIntradaySession,
    CriLiveResponse,
    CriResponse,
    CriScanResponse,
    DealerRegimeResponse,
    DealerRegimeSignal,
    GammaDecayBucket,
    GexHistoryEntry,
    GexIntradayResponse,
    GexIntradaySession,
    GexResponse,
    GrgResponse,
    GrgScanResponse,
    MarketTideResponse,
    MarketTideSentiment,
    MarketTideSession,
    RegimeLiveQuote,
    RegimeQuotesResponse,
    TopNetImpactResponse,
    TopNetImpactRow,
    VcgDailyEntry,
    VcgDailyHistoryResponse,
    VcgIntradayResponse,
    VcgIntradaySession,
    VcgLiveResponse,
    VcgResponse,
    VcgScanResponse,
    VolBackdropResponse,
    VrpHarvestResponse,
    VrpHarvestVerdict,
    VrpMacroSignalLiveResponse,
    VrpMacroSignalResponse,
    VrpMacroSignalRow,
)
from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION as CANARY_COMPOSITE_VERSION,
)
from uw_scan.cards.dealer_regime import compute_dealer_regime, gather_inputs
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    current_macro_signal,
    current_macro_signal_live,
)
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import gex as gex_scanner
from uw_scan.scanners import grg as grg_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import load_live_quotes
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.vrp_macro_entry import capture_entry_now

logger = logging.getLogger(__name__)

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
    raw = repo.fetch_intraday_sessions(ticker=t, sessions=sessions, rth_only=rth_only)
    payload_sessions = [GexIntradaySession.model_validate(s) for s in raw]
    last_ts = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
    return GexIntradayResponse(
        ticker=t,
        sessions=payload_sessions,
        as_of=last_ts,
    )


@router.get("/market-tide", response_model=MarketTideResponse)
def get_market_tide(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: int = Query(5, ge=1, le=30),
) -> MarketTideResponse:
    """Last N sessions of market-wide 5-min net options premium + live spot.

    Reads market_tide_snapshots (worker-captured intraday + backfilled history).
    Drives the regime Market Tide tab. Empty `sessions` is a valid response.
    """
    from uw_scan.storage.market_tide_snapshot_repository import (
        MarketTideSnapshotRepository,
    )

    tide_repo = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    raw = tide_repo.fetch_sessions(sessions=sessions)
    payload_sessions = [MarketTideSession.model_validate(s) for s in raw]
    last_ts = None
    sentiment = None
    if payload_sessions and payload_sessions[-1].points:
        last_ts = payload_sessions[-1].points[-1].ts
        from uw_scan.reports.market_tide_sentiment import compute_sentiment

        sentiment = MarketTideSentiment(
            **compute_sentiment(payload_sessions[-1].points).to_dict()
        )
    return MarketTideResponse(
        sessions=payload_sessions,
        spot_ticker=settings.market_tide_spot_ticker,
        as_of=last_ts,
        market_open=_is_market_open_now(),
        sentiment=sentiment,
    )


@router.get("/top-net-impact", response_model=TopNetImpactResponse)
def get_top_net_impact(
    repo: Annotated[Repository, Depends(get_repo)],
    date_str: str | None = Query(None, alias="date"),
    limit: int = Query(40, ge=1, le=100),
) -> TopNetImpactResponse:
    """Top tickers by net option premium for one session (default: latest).

    Reads top_net_impact_snapshots (worker-captured every 15 min through RTH).
    Rows sorted by net_premium DESC; each carries its per-update rank_change.
    """
    from datetime import date as _date

    from uw_scan.storage.top_net_impact_repository import TopNetImpactRepository

    parsed: _date | None = None
    if date_str:
        try:
            parsed = _date.fromisoformat(date_str)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="bad date") from exc

    tni_repo = TopNetImpactRepository(repo.conn, schema=repo._schema)
    resolved, rows = tni_repo.fetch_latest(data_date=parsed, limit=limit)
    return TopNetImpactResponse(
        rows=[TopNetImpactRow.model_validate(r) for r in rows],
        data_date=resolved,
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


@router.get("/vrp-harvest", response_model=VrpHarvestResponse)
def get_vrp_harvest(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VrpHarvestResponse:
    """Per-bucket VRP harvest verdicts (Spec B). Read-only over the verdict
    store written by the nightly vrp_markout job."""
    rows = repo.fetch_vrp_harvest_verdicts()
    return VrpHarvestResponse(verdicts=[VrpHarvestVerdict(**r) for r in rows])


@router.get("/vrp-macro-signal", response_model=VrpMacroSignalResponse)
def get_vrp_macro_signal(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VrpMacroSignalResponse:
    """Latest VRP macro short-vol signal per index (SPX/QQQ/IWM). Read-only over
    the daily snapshot written by the nightly vrp_macro_signal_refresh job."""
    rows = repo.fetch_latest_vrp_macro_signals()
    return VrpMacroSignalResponse(signals=[VrpMacroSignalRow(**r) for r in rows])


@router.get("/vrp-macro-signal/live", response_model=VrpMacroSignalLiveResponse)
def get_vrp_macro_signal_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroSignalLiveResponse:
    """Live SPX VRP macro short-vol signal: intraday VIX -> live vrp_z (rv20/distribution
    from EOD). Falls back to the latest nightly basis='eod' snapshot when quotes are
    stale. Mirrors /cri/live; does not persist (the 5-min job does that)."""
    today_et = datetime.now(
        ZoneInfo(settings.rth_tz)
    ).date()  # match the worker's ET date
    quotes = load_live_quotes(
        repo,
        settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
    )
    spx_q, vix_q = quotes.get("SPX"), quotes.get("VIX")
    if spx_q is not None and vix_q is not None:
        try:
            sig = current_macro_signal_live(
                repo,
                settings,
                "SPX",
                WINNER,
                live_spot=float(spx_q.price),
                live_iv=float(vix_q.price) / 100.0,
            )
        except ValueError as exc:
            logger.debug(
                "vrp live recompute failed; falling back to EOD: %s", repr(exc)
            )
            sig = None
        if sig is not None:
            # merge the static backtest headline from the latest EOD row, if present
            eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
            bt = eod_rows[0] if eod_rows else {}
            row = VrpMacroSignalRow(
                name=sig.name,
                snapshot_date=today_et,
                as_of=sig.as_of,
                spot=sig.spot,
                iv=sig.iv,
                rv20=sig.rv20,
                vrp=sig.vrp,
                vrp_z=sig.vrp_z,
                weight=sig.weight,
                action=sig.action,
                short_put=sig.short_put,
                long_put=sig.long_put,
                put_width=sig.put_width,
                credit=sig.credit,
                max_loss=sig.max_loss,
                hold_days=sig.hold_days,
                short_delta=sig.short_delta,
                wing_delta=sig.wing_delta,
                bt_n=bt.get("bt_n"),
                bt_sharpe=bt.get("bt_sharpe"),
                bt_maxdd=bt.get("bt_maxdd"),
                bt_annror=bt.get("bt_annror"),
                bt_calmar=bt.get("bt_calmar"),
            )
            return VrpMacroSignalLiveResponse(
                basis="live",
                signal=row,
                live_quotes={
                    s: RegimeLiveQuote(
                        price=float(q.price), quoted_at=q.quoted_at, source=q.source
                    )
                    for s, q in (("SPX", spx_q), ("VIX", vix_q))
                },
                active_source=_active_ws_source(repo),
            )
    eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
    if not eod_rows:
        return VrpMacroSignalLiveResponse(basis="eod", signal=None)
    return VrpMacroSignalLiveResponse(
        basis="eod",
        signal=VrpMacroSignalRow(
            **{k: eod_rows[0].get(k) for k in VrpMacroSignalRow.model_fields}
        ),
    )


# ─── VRP macro entry-capture preview + capture ───────────────────

_PREVIEW_LEG_ORDER = ("short_above", "short_below", "wing_above", "wing_below")


def _f(v: object) -> float | None:
    return float(v) if v is not None else None  # type: ignore[arg-type]


def _live_or_eod_macro_signal(repo: Repository, settings: Settings):
    """Live SPX macro signal if SPX+VIX quotes are fresh, else the EOD signal,
    else None. Reads DB only — ZERO UW, ZERO IB, ZERO writes (preview is
    browser-polled; a fetcher call would write an audit row per poll)."""
    quotes = load_live_quotes(
        repo,
        settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
    )
    spx, vix = quotes.get("SPX"), quotes.get("VIX")
    if spx is not None and vix is not None:
        try:
            return current_macro_signal_live(
                repo,
                settings,
                "SPX",
                WINNER,
                live_spot=float(spx.price),
                live_iv=float(vix.price) / 100.0,
            )
        except ValueError as exc:
            logger.debug("vrp preview live signal failed: %s", repr(exc))
    try:
        return current_macro_signal(repo, settings, "SPX")
    except ValueError as exc:
        logger.debug("vrp preview eod signal failed: %s", repr(exc))
        return None


def _persisted_preview_legs(quotes: list[dict]) -> list[VrpMacroEntryLeg]:
    """Latest-as_of snapshot legs of a persisted cohort, ordered."""
    if not quotes:
        return []
    latest = max(q["as_of"] for q in quotes)
    by_leg = {q["leg"]: q for q in quotes if q["as_of"] == latest}
    legs: list[VrpMacroEntryLeg] = []
    for name in _PREVIEW_LEG_ORDER:
        q = by_leg.get(name)
        if q is None:
            continue
        legs.append(
            VrpMacroEntryLeg(
                leg=name,
                strike=float(q["strike"]),
                nbbo_bid=_f(q["nbbo_bid"]),
                nbbo_ask=_f(q["nbbo_ask"]),
                iv=_f(q["iv"]),
                delta=_f(q["delta"]),
                gamma=_f(q["gamma"]),
                vega=_f(q["vega"]),
                theta=_f(q["theta"]),
                und_spot=_f(q["und_spot"]),
                source=q["source"],
                greeks_source=q["greeks_source"],
            )
        )
    return legs


def _leg_mid(leg: VrpMacroEntryLeg) -> float | None:
    if leg.nbbo_bid is not None and leg.nbbo_ask is not None:
        return (leg.nbbo_bid + leg.nbbo_ask) / 2.0
    return None


def _modeled_credit(legs: list[VrpMacroEntryLeg]) -> float | None:
    """short-leg mid − wing-leg mid using the consistent 'above' bracket (the
    continuous-strike MacroSignal.credit won't match the snapped legs)."""
    by = {leg.leg: leg for leg in legs}
    s, w = by.get("short_above"), by.get("wing_above")
    if s is None or w is None:
        return None
    sm, wm = _leg_mid(s), _leg_mid(w)
    if sm is None or wm is None:
        return None
    return sm - wm


@router.get("/vrp-macro-signal/entry/preview", response_model=VrpMacroEntryPreview)
def get_vrp_macro_entry_preview(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroEntryPreview:
    """SPX entry preview. ZERO IB, ZERO new UW, ZERO writes — browser-polled.
    Serves today's persisted auto-cohort snapshot legs (real strikes + NBBO) if
    present, else empty legs — never a fabricated indicative grid (a synthetic
    strike/mid is worse than none). Degrades to action=None + empty legs when no
    signal resolves (never 500)."""
    today_et = datetime.now(ZoneInfo(settings.rth_tz)).date()
    sig = _live_or_eod_macro_signal(repo, settings)
    today_cohort = next(
        (
            c
            for c in repo.fetch_open_vrp_macro_entries("SPX", today_et)
            if c["birth_date"] == today_et
        ),
        None,
    )
    if today_cohort is not None:
        quotes = repo.fetch_vrp_macro_entry_quotes(today_cohort["entry_id"])
        legs = _persisted_preview_legs(quotes)
        return VrpMacroEntryPreview(
            name="SPX",
            as_of=max((q["as_of"] for q in quotes), default=None),
            spot=float(sig.spot) if sig else _f(today_cohort["spot_at_birth"]),
            expiry=today_cohort["expiry"],
            hold_days=today_cohort["hold_days"],
            action=sig.action if sig else today_cohort["action_at_birth"],
            vrp_z=(
                float(sig.vrp_z)
                if sig and sig.vrp_z is not None
                else _f(today_cohort["vrp_z_at_birth"])
            ),
            weight=float(sig.weight) if sig else _f(today_cohort["weight_at_birth"]),
            modeled_credit=_modeled_credit(legs),
            legs=legs,
        )
    if sig is None:
        return VrpMacroEntryPreview(name="SPX", legs=[])
    # No cohort born/captured today → no real strikes or quotes exist yet. Do NOT
    # fabricate an indicative grid: synthetic strikes + flat-vol BS mids are not
    # market data, and a fake number is worse than none. Surface the real signal
    # context with empty legs; the card renders "No entry preview yet" + "ETD —".
    return VrpMacroEntryPreview(
        name="SPX",
        spot=float(sig.spot),
        hold_days=sig.hold_days,
        action=sig.action,
        vrp_z=float(sig.vrp_z) if sig.vrp_z is not None else None,
        weight=float(sig.weight),
        legs=[],
    )


@router.post(
    "/vrp-macro-signal/entry/capture", response_model=VrpMacroEntryCaptureResponse
)
def post_vrp_macro_entry_capture(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroEntryCaptureResponse:
    """Capture the current SPX entry now (IB-primary): persists a one-shot 'button'
    cohort + its 4 legs, then returns them read back from the persisted rows."""
    entry_id = capture_entry_now(repo, settings)
    header = repo.fetch_vrp_macro_entry(entry_id)
    quotes = repo.fetch_vrp_macro_entry_quotes(entry_id)
    legs = _persisted_preview_legs(quotes)
    preview = VrpMacroEntryPreview(
        name="SPX",
        as_of=max((q["as_of"] for q in quotes), default=None),
        spot=_f(header["spot_at_birth"]) if header else None,
        expiry=header["expiry"] if header else None,
        hold_days=header["hold_days"] if header else None,
        action=header["action_at_birth"] if header else None,
        vrp_z=_f(header["vrp_z_at_birth"]) if header else None,
        weight=_f(header["weight_at_birth"]) if header else None,
        modeled_credit=_modeled_credit(legs),
        legs=legs,
    )
    return VrpMacroEntryCaptureResponse(entry_id=entry_id, preview=preview)


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


# ─── CRI / VCG live (WS-quote-driven) ────────────────────────────


def _active_ws_source(repo: Repository) -> str | None:
    state = repo.get_ws_consumer_state()
    return state.active_source if state is not None else None


@router.get("/cri/live", response_model=CriLiveResponse)
def get_cri_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CriLiveResponse:
    """Request-time CRI with live quotes spliced as today's provisional
    close. Does NOT persist (the 5-min regime_live_scan job owns writes).
    Falls back to the latest basis='eod' snapshot when quotes are stale."""
    quotes = load_live_quotes(
        repo,
        settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
    )
    payload = None
    if quotes:
        payload = cri_scanner.run_live(repo.conn, schema=repo._schema, quotes=quotes)
    if payload is None:
        snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
        latest = snap_repo.fetch_latest()
        if latest is None:
            return CriLiveResponse(basis="eod")
        return CriLiveResponse.model_validate(
            {"status": "ok", "basis": "eod", **latest}
        )
    return CriLiveResponse.model_validate(
        {
            "status": "ok",
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "active_source": _active_ws_source(repo),
            **payload,
        }
    )


@router.get("/cri/intraday", response_model=CriIntradayResponse)
def get_cri_intraday(
    repo: Annotated[Repository, Depends(get_repo)],
    sessions: int = Query(5, ge=1, le=20),
    rth_only: bool = Query(True),
) -> CriIntradayResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
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
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
    rows = snap_repo.fetch_daily_history(days=days)
    return CriDailyHistoryResponse(rows=[CriDailyEntry.model_validate(r) for r in rows])


@router.get("/vcg/live", response_model=VcgLiveResponse)
def get_vcg_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    proxy: str = Query("HYG"),
) -> VcgLiveResponse:
    proxy_upper = proxy.upper()
    quotes = load_live_quotes(
        repo,
        settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
    )
    payload = None
    if quotes:
        payload = vcg_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, proxy=proxy_upper
        )
    if payload is None:
        snap_repo = VcgSnapshotRepository(repo.conn, schema=repo._schema)
        latest = snap_repo.fetch_latest(proxy=proxy_upper)
        if latest is None:
            empty = VcgLiveResponse(basis="eod")
            empty.credit_proxy = proxy_upper
            return empty
        return VcgLiveResponse.model_validate(
            {"status": "ok", "basis": "eod", **latest}
        )
    return VcgLiveResponse.model_validate(
        {
            "status": "ok",
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "active_source": _active_ws_source(repo),
            **payload,
        }
    )


@router.get("/vcg/intraday", response_model=VcgIntradayResponse)
def get_vcg_intraday(
    repo: Annotated[Repository, Depends(get_repo)],
    proxy: str = Query("HYG"),
    sessions: int = Query(5, ge=1, le=20),
    rth_only: bool = Query(True),
) -> VcgIntradayResponse:
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo._schema)
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
    snap_repo = VcgSnapshotRepository(repo.conn, schema=repo._schema)
    rows = snap_repo.fetch_daily_history(proxy=proxy.upper(), days=days)
    return VcgDailyHistoryResponse(
        credit_proxy=proxy.upper(),
        rows=[VcgDailyEntry.model_validate(r) for r in rows],
    )


# ─── GRG (Gamma Rotation Gap) ────────────────────────────────────


@router.get("/grg", response_model=GrgResponse)
def get_grg(
    repo: Annotated[Repository, Depends(get_repo)],
) -> GrgResponse:
    """Latest GRG snapshot (self-contained: embeds 90-session history).

    GRG is EOD/periodic-rescan — the worker owns UW fetches; this read is
    cheap (one snapshot row). No per-request UW spend."""
    snap_repo = GrgSnapshotRepository(repo.conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    if latest is None:
        return EMPTY_GRG_RESPONSE.model_copy(deep=True)
    return GrgResponse.model_validate({"status": "ok", **latest})


@router.post("/grg/scan", status_code=202, response_model=GrgScanResponse)
def trigger_grg_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GrgScanResponse:
    """Run a GRG scan synchronously against UW and persist a snapshot."""
    uw_client = UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )
    try:
        row_id = grg_scanner.run(uw_client, repo, schema=repo._schema)
    finally:
        uw_client.close()
    if row_id is None:
        return GrgScanResponse(status="skipped", reason="thin_data")
    return GrgScanResponse(status="ok", row_id=row_id)


@router.get("/quotes", response_model=RegimeQuotesResponse)
def get_regime_quotes(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegimeQuotesResponse:
    rows = repo.get_intraday_quotes([s.upper() for s in settings.regime_ws_symbols])
    quotes = {
        r.ticker: RegimeLiveQuote(
            price=float(r.price), quoted_at=r.quoted_at, source=r.source
        )
        for r in rows
    }
    as_of = max((r.quoted_at for r in rows), default=None)
    return RegimeQuotesResponse(
        quotes=quotes,
        active_source=_active_ws_source(repo),
        as_of=as_of,
        fresh_within_seconds=settings.regime_live_quote_max_age_seconds,
    )


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
