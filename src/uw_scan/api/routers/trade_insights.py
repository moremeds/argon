"""Trade Insights endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import TradeInsightsResponse
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.reports.trade_insights import (
    ASSEMBLER_VERSION,
    _stable_payload_hash,
    assemble_trade_insights,
)
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get(
    "/stock/{ticker}/trade-insights",
    response_model=TradeInsightsResponse,
)
def get_trade_insights(
    ticker: str, repo: Repository = Depends(get_repo)
) -> TradeInsightsResponse:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")

    report = assemble_single_stock_report(t, run_id, repo)
    response = assemble_trade_insights(
        ticker=t,
        run_id=run_id,
        repo=repo,
        as_of=report.generated_at,
        spot=report.market_structure.spot,
    )
    payload = response.model_dump(mode="json")
    input_hash = _stable_payload_hash(payload)
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker=t,
        as_of=response.as_of,
        assembler_version=ASSEMBLER_VERSION,
        input_hash=input_hash,
        payload=payload,
    )
    repo.replace_trade_insight_candidates(
        snapshot_id=snapshot_id,
        run_id=run_id,
        ticker=t,
        candidates=payload["candidate_structures"],
    )
    repo.conn.commit()
    return response
