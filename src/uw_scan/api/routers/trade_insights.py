"""Trade Insights endpoint."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.cards.gex import classify_bias, find_flip_strike
from uw_scan.config import Settings
from uw_scan.models import (
    StockHistoryResponse,
    StockHistoryRow,
    StrikeGexBucket,
    TradeInsightAiAnalysisRequest,
    TradeInsightAiAnalysisResponse,
    TradeInsightsResponse,
)
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.reports.trade_insights import (
    ASSEMBLER_VERSION,
    _stable_payload_hash,
    assemble_trade_insights,
)
from uw_scan.reports.trade_insights_ai import (
    PROMPT_VERSION,
    build_trade_insights_ai_analysis_input,
    hash_trade_insights_ai_analysis_input,
)
from uw_scan.reports.volatility_series import assemble_volatility_series
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
            expiry=_date.fromisoformat(str(row["expiry"])),
            net_gex=_dec(row.get("net_gex")),
            call_gex=_dec(row.get("call_gex")),
            put_gex=_dec(row.get("put_gex")),
        )
        for row in raw
    ]


def _build_stock_history_response(
    ticker: str, repo: Repository
) -> StockHistoryResponse:
    rows: list[StockHistoryRow] = []
    for r in repo.fetch_stock_history_rollup(ticker, limit=30):
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
    return StockHistoryResponse(ticker=ticker, rows=rows)


def _build_and_persist_trade_insights(
    ticker: str,
    repo: Repository,
) -> tuple[TradeInsightsResponse, int, str]:
    run_id = repo.latest_run_id(ticker)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {ticker}")

    report = assemble_single_stock_report(ticker, run_id, repo)
    response = assemble_trade_insights(
        ticker=ticker,
        run_id=run_id,
        repo=repo,
        as_of=report.generated_at,
        spot=report.market_structure.spot,
    )
    payload = response.model_dump(mode="json")
    input_hash = _stable_payload_hash(payload)
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker=ticker,
        as_of=response.as_of,
        assembler_version=ASSEMBLER_VERSION,
        input_hash=input_hash,
        payload=payload,
    )
    repo.replace_trade_insight_candidates(
        snapshot_id=snapshot_id,
        run_id=run_id,
        ticker=ticker,
        candidates=payload["candidate_structures"],
    )
    return response, snapshot_id, input_hash


def _row_to_ai_response(
    row: dict[str, Any],
    *,
    reused: bool = False,
) -> TradeInsightAiAnalysisResponse:
    return TradeInsightAiAnalysisResponse(
        analysis_id=UUID(str(row["analysis_id"])),
        ticker=row["ticker"],
        run_id=row["run_id"],
        trade_insights_input_hash=row["trade_insights_input_hash"],
        analysis_input_hash=row["analysis_input_hash"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        status=row["status"],
        produced_at=row.get("produced_at"),
        outcome=row.get("outcome_jsonb"),
        markdown=row.get("markdown"),
        error_message=row.get("error_message"),
        requested_at=row["requested_at"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        reused=reused,
    )


@router.get(
    "/stock/{ticker}/trade-insights",
    response_model=TradeInsightsResponse,
)
def get_trade_insights(
    ticker: str, repo: Repository = Depends(get_repo)
) -> TradeInsightsResponse:
    t = ticker.upper()
    response, _snapshot_id, _input_hash = _build_and_persist_trade_insights(t, repo)
    repo.conn.commit()
    return response


@router.post(
    "/stock/{ticker}/trade-insights/ai-analysis",
    response_model=TradeInsightAiAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_trade_insights_ai_analysis(
    ticker: str,
    request: TradeInsightAiAnalysisRequest | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TradeInsightAiAnalysisResponse:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")
    if not settings.trade_insights_ai_enabled:
        raise HTTPException(
            status_code=503,
            detail="Trade Insights AI analysis is disabled",
        )

    force_rerun = bool(request.force_rerun) if request is not None else False
    trade_response, snapshot_id, trade_input_hash = _build_and_persist_trade_insights(
        t,
        repo,
    )
    stock_report = assemble_single_stock_report(t, run_id, repo)
    stock_history = _build_stock_history_response(t, repo)
    backfill_status = (repo.get_volatility_backfill_status(t) or {}).get(
        "status"
    ) or "ready"
    volatility = assemble_volatility_series(
        ticker=t,
        repo=repo,
        backfill_status=backfill_status,
        persist_derived=False,
    )
    analysis_input = build_trade_insights_ai_analysis_input(
        ticker=t,
        run_id=run_id,
        trade_insights_input_hash=trade_input_hash,
        trade_insights_payload=trade_response.model_dump(mode="json"),
        stock_report_payload=stock_report.model_dump(mode="json"),
        stock_history_payload=stock_history.model_dump(mode="json"),
        volatility_series_payload=volatility.model_dump(mode="json"),
    )
    analysis_hash = hash_trade_insights_ai_analysis_input(analysis_input)
    model_label = settings.trade_insights_ai_model.strip() or "codex-default"

    if not force_rerun:
        reused = repo.find_reusable_trade_insight_ai_analysis(
            ticker=t,
            analysis_input_hash=analysis_hash,
            prompt_version=PROMPT_VERSION,
            model=model_label,
        )
        if reused is not None:
            repo.conn.commit()
            return _row_to_ai_response(reused, reused=True)

    analysis_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker=t,
        run_id=run_id,
        trade_insights_input_hash=trade_input_hash,
        analysis_input_hash=analysis_hash,
        analysis_input=analysis_input,
        prompt_version=PROMPT_VERSION,
        model=model_label,
    )
    repo.conn.commit()
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker=t)
    assert row is not None
    return _row_to_ai_response(row, reused=False)


@router.get(
    "/stock/{ticker}/trade-insights/ai-analysis/latest",
    response_model=TradeInsightAiAnalysisResponse | None,
)
def get_latest_trade_insights_ai_analysis(
    ticker: str,
    repo: Repository = Depends(get_repo),
) -> TradeInsightAiAnalysisResponse | None:
    row = repo.find_latest_succeeded_trade_insight_ai_analysis(ticker=ticker.upper())
    if row is None:
        return None
    return _row_to_ai_response(row)


@router.get(
    "/stock/{ticker}/trade-insights/ai-analysis/{analysis_id}",
    response_model=TradeInsightAiAnalysisResponse,
)
def get_trade_insights_ai_analysis(
    ticker: str,
    analysis_id: UUID,
    repo: Repository = Depends(get_repo),
) -> TradeInsightAiAnalysisResponse:
    row = repo.get_trade_insight_ai_analysis(str(analysis_id), ticker=ticker.upper())
    if row is None:
        raise HTTPException(status_code=404, detail="AI analysis not found")
    return _row_to_ai_response(row)
