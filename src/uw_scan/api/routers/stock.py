"""/api/stock/{ticker} — latest report + run history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import SingleStockReport
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/stock/{ticker}", response_model=SingleStockReport)
def get_stock(ticker: str, repo: Repository = Depends(get_repo)) -> SingleStockReport:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")
    return assemble_single_stock_report(t, run_id, repo)


@router.get("/stock/{ticker}/runs")
def list_runs(ticker: str, repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_runs_for_ticker(ticker.upper(), limit=50)


@router.get("/stock/{ticker}/runs/{run_id}", response_model=SingleStockReport)
def get_specific_run(
    ticker: str, run_id: int, repo: Repository = Depends(get_repo)
) -> SingleStockReport:
    return assemble_single_stock_report(ticker.upper(), run_id, repo)
