"""/api/stock/{ticker} — latest report + run history."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.cards.gex import classify_bias, find_flip_strike
from uw_scan.models import (
    SingleStockReport,
    StockHistoryResponse,
    StockHistoryRow,
    StrikeGexBucket,
)
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.storage.repository import Repository

router = APIRouter()


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
    return _with_latest_spot(assemble_single_stock_report(t, run_id, repo), repo)


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
    report = assemble_single_stock_report(ticker.upper(), run_id, repo)
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
        best_source = "massive.com_intraday"

    report.market_structure.spot = best_spot
    report.spot_quoted_at = best_at
    report.spot_source = best_source
    return report
