"""/api/stock/{ticker} — latest report + run history."""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from datetime import date as _date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.cards.gex import classify_bias, find_flip_strike
from uw_scan.cards.magnets import (
    CONE_HORIZONS,
    all_pivots,
    build_read,
    cone,
    magnet_levels,
)
from uw_scan.config import Settings
from uw_scan.models import (
    ChanlunLifecycleMark,
    ChanlunLifecycleResponse,
    FundamentalCardResponse,
    MagnetsResponse,
    SingleStockReport,
    StockHistoryResponse,
    StockHistoryRow,
    StrikeGexBucket,
    TechnicalsLiveResponse,
    TechnicalsResponse,
    TechnicalsVwapAnchor,
    VwapAnchorRequest,
    VwapPoint,
)
from uw_scan.reports.magnet_data import (
    atm_iv_at_horizon,
    load_adjusted_closes,
    load_all_expiry_iv_curves,
    load_all_session_spots,
    trim_to_clean_segment,
)
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.reports.technicals import assemble_technicals
from uw_scan.storage.repository import Repository

router = APIRouter()

# Response cache for the two polled stock-page endpoints. Keyed on
# (ticker, run_id); a new scan mints a new run_id so old keys age out on their
# own (TTL/LRU) — no explicit invalidation. Short TTL so intraday-bucket
# refreshes (worker cadence) surface within a poll cycle. Set the TTL to 0 to
# disable (incident escape hatch).
# ponytail: naive TTL+LRU dict guarded by one lock — ~20 lines beats a
# cachetools dep. Swap in cachetools.TTLCache only if we need per-key TTLs.
_REPORT_CACHE_TTL_S = float(os.getenv("SINGLE_STOCK_REPORT_CACHE_TTL_S", "20"))
_REPORT_CACHE_MAXSIZE = 256
_report_cache: OrderedDict[tuple[str, int], tuple[float, SingleStockReport]] = (
    OrderedDict()
)
_report_cache_lock = threading.Lock()

# Cheap hit/miss counters so we can see the cache actually earning its keep.
_report_cache_hits = 0
_report_cache_misses = 0


def report_cache_stats() -> dict[str, int | float]:
    """Cumulative cache hit/miss counts + hit rate (for logging / debugging)."""
    with _report_cache_lock:
        hits, misses = _report_cache_hits, _report_cache_misses
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 3) if total else 0.0,
    }


def _report_cache_clear() -> None:
    """Drop all cached reports and reset counters (used by tests for isolation)."""
    global _report_cache_hits, _report_cache_misses
    with _report_cache_lock:
        _report_cache.clear()
        _report_cache_hits = 0
        _report_cache_misses = 0


def _assemble_cached(ticker: str, run_id: int, repo: Repository) -> SingleStockReport:
    """assemble_single_stock_report with a per-(ticker, run_id) TTL cache.

    Always returns a deep copy so the caller (``_with_latest_spot``) can mutate
    the report in place without corrupting the shared cache entry.
    """
    global _report_cache_hits, _report_cache_misses

    if _REPORT_CACHE_TTL_S <= 0:
        return assemble_single_stock_report(ticker, run_id, repo)

    key = (ticker, run_id)
    now = time.monotonic()
    with _report_cache_lock:
        hit = _report_cache.get(key)
        if hit is not None:
            expires_at, cached = hit
            if expires_at > now:
                _report_cache.move_to_end(key)
                _report_cache_hits += 1
                return cached.model_copy(deep=True)
            _report_cache.pop(key, None)
        _report_cache_misses += 1

    report = assemble_single_stock_report(ticker, run_id, repo)
    with _report_cache_lock:
        _report_cache[key] = (now + _REPORT_CACHE_TTL_S, report)
        _report_cache.move_to_end(key)
        while len(_report_cache) > _REPORT_CACHE_MAXSIZE:
            _report_cache.popitem(last=False)
    return report.model_copy(deep=True)


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _build_curve(raw: list[dict]) -> list[StrikeGexBucket]:
    return [
        StrikeGexBucket(
            strike=Decimal(str(row["strike"])),
            expiry=_date.fromisoformat(row["expiry"]),
            net_gex=_dec(row.get("net_gex")),
            call_gex=_dec(row.get("call_gex")),
            put_gex=_dec(row.get("put_gex")),
        )
        for row in raw
    ]


@router.get("/stock/{ticker}", response_model=SingleStockReport)
def get_stock(ticker: str, repo: Repository = Depends(get_repo)) -> SingleStockReport:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")
    return _with_latest_spot(_assemble_cached(t, run_id, repo), repo)


@router.get("/stock/{ticker}/history", response_model=StockHistoryResponse)
def get_stock_history(
    ticker: str, repo: Repository = Depends(get_repo)
) -> StockHistoryResponse:
    """Daily rollup for the Market Structure tab's history table.

    One row per trading day, sorted newest-first. Today's row may have
    spot=None if the post-close OHLC pull hasn't fired yet.
    """
    t = ticker.upper()
    raw_rows = repo.fetch_stock_history_rollup(t, limit=30)
    rows: list[StockHistoryRow] = []
    for r in raw_rows:
        curve = _build_curve(r["strike_gex_curve"] or [])
        net_gex = sum((b.net_gex for b in curve if b.net_gex is not None), Decimal("0"))
        flip = find_flip_strike(curve)
        spot = _dec(r.get("spot"))
        rows.append(
            StockHistoryRow(
                market_date=r["market_date"],
                spot=spot,
                gex_flip=flip,
                net_gex=net_gex if curve else None,
                net_dex=None,
                iv30d=_dec(r.get("iv30d")),
                pcr_vol=_dec(r.get("pcr_vol")),
                bias=classify_bias(spot, flip, net_gex if curve else None),
            )
        )
    return StockHistoryResponse(ticker=t, rows=rows)


@router.get("/stock/{ticker}/runs")
def list_runs(ticker: str, repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_runs_for_ticker(ticker.upper(), limit=50)


@router.get("/stock/{ticker}/runs/{run_id}", response_model=SingleStockReport)
def get_specific_run(
    ticker: str, run_id: int, repo: Repository = Depends(get_repo)
) -> SingleStockReport:
    report = _assemble_cached(ticker.upper(), run_id, repo)
    return _with_latest_spot(report, repo)


def _with_latest_spot(report: SingleStockReport, repo: Repository) -> SingleStockReport:
    """Keep the detail header aligned with the dashboard card's delayed quote."""
    card = repo.get_watchlist_card(report.ticker)
    quote = repo.get_intraday_quote(report.ticker)

    best_spot = report.market_structure.spot
    best_at = report.spot_quoted_at or report.generated_at
    best_source = report.spot_source or "uw_scan"

    if card is not None and card.spot is not None:
        best_spot = card.spot
        best_at = card.spot_quoted_at or best_at
        best_source = card.spot_source or best_source

    if quote is not None and (best_at is None or quote.quoted_at >= best_at):
        best_spot = quote.price
        best_at = quote.quoted_at
        # R7: use the quote's own source label so WS writes surface as
        # "massive.com_ws" instead of the legacy hardcoded "massive.com_intraday".
        best_source = quote.source

    report.market_structure.spot = best_spot
    report.spot_quoted_at = best_at
    report.spot_source = best_source
    return report


@router.get("/stock/{ticker}/technicals", response_model=TechnicalsResponse)
def get_stock_technicals(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsResponse:
    return assemble_technicals(ticker, repo, schema=settings.db_schema)


@router.get("/stock/{ticker}/technicals/live", response_model=TechnicalsLiveResponse)
def get_stock_technicals_live(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsLiveResponse:
    from uw_scan.storage.technical_live_repository import TechnicalLiveRepository

    t = ticker.upper()
    row = TechnicalLiveRepository(repo.conn, schema=settings.db_schema).fetch(t)
    if row is None:
        return TechnicalsLiveResponse(ticker=t, available=False)
    p = row["payload"]
    return TechnicalsLiveResponse(
        ticker=t,
        available=True,
        captured_at=row["captured_at"],
        spot=row["spot"],
        spot_source=row["spot_source"],
        forming_ohlc=p.get("forming_ohlc"),
        z=p.get("z"),
        z_band=p.get("z_band"),
        rsi14=p.get("rsi14"),
        rsi_z=p.get("rsi_z"),
        dual_macd=p.get("dual_macd"),
        rv20=p.get("rv20"),
        kinematics=p.get("kinematics"),
        composite=p.get("composite"),
    )


# Session-scoped single-flight key, matching routers/volatility.py's convention.
_TECHNICALS_REFRESH_LOCK_SQL = (
    "('x' || substr(md5('technicals_refresh:' || %s), 1, 16))::bit(64)::bigint"
)


@router.post("/stock/{ticker}/technicals/refresh", response_model=TechnicalsResponse)
def refresh_stock_technicals(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsResponse:
    """On-demand EOD technicals compute for a ticker with no history yet.

    Runs the same job the nightly refresh runs, scoped to one ticker, then
    returns the freshly-stored series. Thin history / apex-unreachable leaves
    ``backfill_status='empty'`` (nothing stored, nothing to render). Single-
    flight per ticker via a session advisory lock: a concurrent compute (double
    click, or overlap with the nightly job) returns the current state instead of
    double-running the apex fetch + recompute.
    """
    # ponytail: the one deliberate write on this otherwise read-only router —
    # user-triggered, idempotent, bounded (~2 apex fetches + pandas). Promote to
    # a /jobs kind only if this ever needs to be async or batched.
    from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

    t = ticker.upper()
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT pg_try_advisory_lock({_TECHNICALS_REFRESH_LOCK_SQL})", (t,)
        )
        acquired = bool(cur.fetchone()[0])
    if not acquired:
        return assemble_technicals(t, repo, schema=settings.db_schema)
    try:
        technical_daily_refresh(repo=repo, settings=settings, ticker_filter=[t])
        return assemble_technicals(t, repo, schema=settings.db_schema)
    finally:
        with repo.conn.cursor() as cur:
            cur.execute(
                f"SELECT pg_advisory_unlock({_TECHNICALS_REFRESH_LOCK_SQL})", (t,)
            )


@router.post("/stock/{ticker}/vwap-anchor", response_model=TechnicalsVwapAnchor)
def set_vwap_anchor(
    ticker: str,
    body: VwapAnchorRequest,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsVwapAnchor:
    """Persist a user-clicked VWAP anchor and return the computed series.

    A sanctioned write on this otherwise read-only router (precedent:
    /technicals/refresh). Pure DB read + O(n) math + one upsert — no external
    fetch, so no single-flight lock is needed.
    """
    from uw_scan.cards.technicals import anchored_vwap
    from uw_scan.storage.technical_vwap_anchor_repository import (
        TechnicalVwapAnchorRepository,
    )
    from uw_scan.storage.technicals_repository import TechnicalsRepository

    t = ticker.upper()
    rows = TechnicalsRepository(repo.conn, schema=settings.db_schema).fetch_series(t)
    if not any(r["as_of"] == body.anchor_date for r in rows):
        raise HTTPException(400, f"{body.anchor_date} is not a stored bar for {t}")
    points = anchored_vwap(rows, body.anchor_date)
    if not points:
        raise HTTPException(400, f"no OHLCV at/after {body.anchor_date} for {t}")
    snapshot = [{"as_of": p["as_of"].isoformat(), "vwap": p["vwap"]} for p in points]
    TechnicalVwapAnchorRepository(repo.conn, schema=settings.db_schema).upsert(
        t, body.anchor_date, snapshot
    )
    return TechnicalsVwapAnchor(
        anchor_date=body.anchor_date,
        series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in points],
    )


@router.delete("/stock/{ticker}/vwap-anchor", status_code=204)
def clear_vwap_anchor(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> None:
    """Clear the persisted VWAP anchor (idempotent)."""
    from uw_scan.storage.technical_vwap_anchor_repository import (
        TechnicalVwapAnchorRepository,
    )

    TechnicalVwapAnchorRepository(repo.conn, schema=settings.db_schema).delete(
        ticker.upper()
    )


@router.get(
    "/stock/{ticker}/chanlun/lifecycle", response_model=ChanlunLifecycleResponse
)
def get_stock_chanlun_lifecycle(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ChanlunLifecycleResponse:
    """Current lifecycle state of every recorded chanlun mark, read-only.

    Excludes marks whose current state is invalidated/stale (spec §API amended
    2026-07-14); breach/superseded/split_boundary invalidations are returned.
    """
    from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository

    t = ticker.upper()
    rows = ChanlunSignalRepository(repo.conn, schema=settings.db_schema).current_states(
        t
    )
    # Spec §API: stale-invalidated marks are excluded; every other current
    # state (incl. breach/superseded/split_boundary invalidations) is returned.
    rows = [
        r for r in rows if not (r["state"] == "invalidated" and r["reason"] == "stale")
    ]
    marks = [
        ChanlunLifecycleMark(
            category=r["category"],
            kind=r["kind"],
            extreme_date=r["extreme_date"],
            extreme_price=r["extreme_price"],
            state=r["state"],
            reason=r["reason"],
            first_entered_at=r["first_entered_at"],
            as_of=r["as_of"],
        )
        for r in rows
    ]
    return ChanlunLifecycleResponse(ticker=t, marks=marks)


@router.get("/stock/{ticker}/fundamentals", response_model=FundamentalCardResponse)
def get_stock_fundamentals(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> FundamentalCardResponse:
    """The deterministic blocks of the §7 fundamental card for one name.

    Subscores, coverage and provenance only — the valuation anchor, narrative and
    audit blocks need stages 3-5 and are absent from the contract rather than
    served empty.

    404 and 503 are deliberately distinct: "this name has no score" and "no method
    version is active" are different problems, and collapsing them would hide a
    stack-wide outage behind a per-ticker empty state.
    """
    from uw_scan.fundamentals.card import build_card
    from uw_scan.storage.fundamental_obs import FundamentalObsRepository
    from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

    t = ticker.upper()
    conn, schema = repo.conn, settings.db_schema
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = scores.active_version()
    if engine is None:
        raise HTTPException(
            status_code=503, detail="no active fundamental method version"
        )
    row = scores.latest_for_ticker(t, engine)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no fundamental score for {t}")
    violated = FundamentalObsRepository(conn, schema=schema).violated_fields(
        row.get("source_obs_ids") or []
    )
    return FundamentalCardResponse.model_validate(
        build_card(ticker=t, row=row, violated=violated, engine_version=engine)
    )


_MAGNET_CANDLE_WINDOW = 180
# Sessions of grid history pulled for the ATM IV line. Matches the tile
# sparklines' 90-session window; the surface capture only accrues forward from
# 2025-12-26, so early tickers legitimately return fewer points.
_MAGNET_IV_SESSIONS = 90


@router.get("/stock/{ticker}/magnets", response_model=MagnetsResponse)
def get_magnets(
    ticker: str,
    k_atr: float = Query(3.0, gt=0.0, le=20.0),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> MagnetsResponse:
    """Magnet levels + options-implied cone. Read-only.

    k_atr defaults to 3.0 only because that is the existing last_pivot_index
    default — G1 failed, so no threshold was selected on merit. It stays a query
    param so the sweep's other rungs stay inspectable from the UI without a
    redeploy; nothing writes it. It is BOUNDED because it is user input at a
    trust boundary: k_atr <= 0 makes the reversal threshold zero, every bar
    becomes a pivot, and the response grows to one entry per bar.

    Uses `repo.conn` + `settings.db_schema`, the pattern this codebase already
    uses when a router needs a raw connection (see `routers/health.py:387`);
    the magnet_data loaders take a connection, not a Repository.
    """
    ticker = ticker.upper()
    conn, schema = repo.conn, settings.db_schema

    raw = trim_to_clean_segment(load_adjusted_closes(conn, ticker, schema))
    # Drop incomplete bars ONCE, up front, so every consumer sees one frame.
    #
    # Two reasons this cannot be a candles-only filter. (1) NaN is not JSON —
    # daily_ohlc.open/high/low are nullable DOUBLE PRECISION, load_adjusted_closes
    # coerces NULL to NaN, Pydantic accepts NaN and FastAPI's encoder then raises
    # "Out of range float values are not JSON compliant". (2) `all_pivots` calls
    # `atr14`, which reads high/low/prev-close — a NaN high makes ATR NaN, the
    # detector's `math.isfinite` guard sets the threshold to inf, and the pivot
    # silently never confirms. Filtering only the drawn candles would leave the
    # geometry computed on a different set of rows than the chart displays.
    px = raw[raw[["open", "high", "low", "close"]].notna().all(axis=1)].reset_index(
        drop=True
    )
    if px.empty:
        raise HTTPException(status_code=404, detail=f"no price history for {ticker}")

    as_of = px["date"].iloc[-1]
    spot = float(px["close"].iloc[-1])

    # The cone needs `as_of`; the IV delta needs the fifth session back; the ATM
    # IV tile needs a line. Bounded at _MAGNET_IV_SESSIONS rather than "every
    # session" because `load_all_expiry_iv_curves` interpolates a VALUES list one
    # row per session against the full chain — unbounded, that grows with capture
    # history forever. Measured on the dev DB (NVDA): 7.0 ms at 6 sessions,
    # 14.2 ms at 90, 13.2 ms at 130 — the join is not the cost, the chain scan
    # is, so the extra sessions are close to free.
    #   uv run python -c "...load_all_expiry_iv_curves timing..." (scratch, not committed)
    spots = load_all_session_spots(conn, ticker, schema)
    sessions = sorted(d for d in spots if d <= as_of)
    wanted = {d: spots[d] for d in sessions[-_MAGNET_IV_SESSIONS:]}
    curves = load_all_expiry_iv_curves(conn, ticker, wanted, schema)

    curve = curves.get(as_of, [])
    # Same target_dte mapping the calibration used: h trading days -> h*7/5
    # calendar days. Drift here and the measured-confidence labels stop
    # describing the drawn band.
    ivs = {h: atm_iv_at_horizon(curve, max(1, round(h * 7 / 5))) for h in CONE_HORIZONS}

    iv30 = atm_iv_at_horizon(curve, 30)
    iv30_prior = (
        atm_iv_at_horizon(curves.get(sessions[-6], []), 30)
        if len(sessions) >= 6
        else None
    )

    levels = magnet_levels(px, k=k_atr)
    bands = cone(spot, ivs)
    window = px.tail(_MAGNET_CANDLE_WINDOW).reset_index(drop=True)
    # Pivot indices are positions in `px`; the chart indexes into `candles`.
    # Rebase BY DATE rather than by subtracting `len(px) - len(window)`. The
    # subtraction happens to be correct today because `window` is a plain tail of
    # `px`, but it silently becomes wrong the moment anything else filters rows
    # between the two — which is exactly the bug the up-front NaN filter above
    # was introduced to avoid. A pivot older than the window is omitted, not
    # clamped: a clamped marker points at a bar the pivot did not occur on.
    window_pos = {d: i for i, d in enumerate(window["date"])}
    px_dates = px["date"].tolist()
    pivots = [
        {"index": window_pos[px_dates[p.index]], "kind": p.kind, "price": p.price}
        for p in all_pivots(px, k=k_atr)
        if px_dates[p.index] in window_pos
    ]
    # One IV point per session that HAS a curve — sessions with no captured
    # surface are omitted, not carried forward. A flat segment across a capture
    # gap would draw as "IV held steady", which is a claim the data does not make.
    iv_series = [
        {"date": d, "iv": v}
        for d in sorted(curves)
        if (v := atm_iv_at_horizon(curves[d], 30)) is not None
    ]
    return MagnetsResponse(
        ticker=ticker,
        as_of=as_of,
        levels=levels,
        bands=bands,
        pivots=pivots,
        read=build_read(levels, bands) if levels else [],
        candles=window.to_dict("records"),
        atm_iv_30d=iv30,
        atm_iv_30d_chg_5d=(
            iv30 - iv30_prior if iv30 is not None and iv30_prior is not None else None
        ),
        atm_iv_30d_series=iv_series,
    )
