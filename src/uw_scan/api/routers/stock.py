"""/api/stock/{ticker} — latest report + run history."""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from datetime import date as _date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.cards.gex import classify_bias, find_flip_strike
from uw_scan.config import Settings
from uw_scan.models import (
    SingleStockReport,
    StockHistoryResponse,
    StockHistoryRow,
    StrikeGexBucket,
    TechnicalsLiveResponse,
    TechnicalsResponse,
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
        z=p.get("z"),
        z_band=p.get("z_band"),
        rsi14=p.get("rsi14"),
        rsi_z=p.get("rsi_z"),
        dual_macd=p.get("dual_macd"),
        rv20=p.get("rv20"),
        kinematics=p.get("kinematics"),
        composite=p.get("composite"),
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
    ``backfill_status='empty'`` (nothing stored, nothing to render).
    """
    # ponytail: the one deliberate write on this otherwise read-only router —
    # user-triggered, idempotent, bounded (~2 apex fetches + pandas). Promote to
    # a /jobs kind only if this ever needs to be async or batched.
    from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

    t = ticker.upper()
    technical_daily_refresh(repo=repo, settings=settings, ticker_filter=[t])
    return assemble_technicals(t, repo, schema=settings.db_schema)
