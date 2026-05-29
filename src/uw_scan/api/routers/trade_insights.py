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
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiAnalysisRequest,
    TradeInsightAiAnalysisResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiLatestPair,
    TradeInsightAiPriorRow,
    TradeInsightAiPriorsResponse,
    TradeInsightAiProviderConsensus,
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
    # Legacy read-back guard: outcome_jsonb persisted under any prior
    # PROMPT_VERSION (v4, v5) will not satisfy the current schema's
    # required fields, so model construction would raise ValidationError
    # and 500 the endpoint. Drop the outcome and surface an explanatory
    # error_message instead; the UI paints the "legacy, re-run" badge on
    # top of this signal. The row itself (status, prompt_version, ids)
    # still renders so the UI can offer a re-run button. Equality against
    # PROMPT_VERSION is the single source of truth — works for every
    # future version bump without code changes here.
    row_prompt_version = row.get("prompt_version")
    outcome_jsonb = row.get("outcome_jsonb")
    if outcome_jsonb is not None and row_prompt_version != PROMPT_VERSION:
        outcome_jsonb = None
        legacy_note = (
            f"Outcome stored under prompt_version={row_prompt_version!r}; "
            f"current version is {PROMPT_VERSION!r}. Re-run to render."
        )
        error_message = row.get("error_message") or legacy_note
    else:
        error_message = row.get("error_message")
    return TradeInsightAiAnalysisResponse(
        analysis_id=UUID(str(row["analysis_id"])),
        ticker=row["ticker"],
        run_id=row["run_id"],
        trade_insights_input_hash=row["trade_insights_input_hash"],
        analysis_input_hash=row["analysis_input_hash"],
        model=row["model"],
        provider=row.get("provider", "codex"),
        prompt_version=row_prompt_version,
        status=row["status"],
        produced_at=row.get("produced_at"),
        outcome=outcome_jsonb,
        markdown=row.get("markdown"),
        error_message=error_message,
        requested_at=row["requested_at"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        reused=reused,
    )


def _enqueue_one_provider(
    *,
    t: str,
    run_id: int,
    snapshot_id: int,
    trade_input_hash: str,
    analysis_hash: str,
    analysis_input: dict[str, Any],
    provider: str,
    model_label: str,
    force_rerun: bool,
    repo: Repository,
) -> TradeInsightAiAnalysisStub:
    """Return a stub describing what happened for ONE provider — either a cache
    hit (reused=True) or a freshly enqueued row (reused=False)."""
    if not force_rerun:
        reused = repo.find_reusable_trade_insight_ai_analysis(
            ticker=t,
            analysis_input_hash=analysis_hash,
            prompt_version=PROMPT_VERSION,
            model=model_label,
            provider=provider,
        )
        if reused is not None:
            return TradeInsightAiAnalysisStub(
                provider=provider,
                analysis_id=UUID(str(reused["analysis_id"])),
                status=reused["status"],
                reused=True,
                model=reused["model"],
            )
    analysis_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker=t,
        run_id=run_id,
        trade_insights_input_hash=trade_input_hash,
        analysis_input_hash=analysis_hash,
        analysis_input=analysis_input,
        prompt_version=PROMPT_VERSION,
        model=model_label,
        provider=provider,
    )
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker=t)
    assert row is not None
    return TradeInsightAiAnalysisStub(
        provider=provider,
        analysis_id=UUID(str(row["analysis_id"])),
        status=row["status"],
        reused=False,
        model=row["model"],
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
    response_model=TradeInsightAiAnalysisEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_trade_insights_ai_analysis(
    ticker: str,
    request: TradeInsightAiAnalysisRequest | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TradeInsightAiAnalysisEnqueueResponse:
    """Enqueue one Trade Insights AI analysis per enabled provider.

    Response contains one stub per provider with status + reused + model.
    Disabled providers are omitted from the response (not included with a
    'disabled' status — the UI tab handles this via /latest = null).
    """
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")
    if not (
        settings.trade_insights_ai_enabled
        or settings.trade_insights_ai_claude_enabled
        or settings.trade_insights_ai_deepseek_enabled
    ):
        raise HTTPException(
            status_code=503,
            detail="Trade Insights AI analysis is disabled (all providers)",
        )

    force_rerun = bool(request.force_rerun) if request is not None else False
    provider_filter: set[str] | None = (
        set(request.providers) if request is not None and request.providers else None
    )
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
    # Framework view (M6): request-time reads from the warm store (per the
    # R2-vs-warm-store rule, API reads hit Postgres). All na-tolerant — the
    # builder degrades each section to {"available": False} when absent.
    positioning_payload = repo.get_uw_positioning(t)
    fundamentals_payload = repo.get_massive_fundamentals(t)
    ohlcv_rows = repo.list_daily_ohlc(t, limit=210)

    analysis_input = build_trade_insights_ai_analysis_input(
        ticker=t,
        run_id=run_id,
        trade_insights_input_hash=trade_input_hash,
        trade_insights_payload=trade_response.model_dump(mode="json"),
        stock_report_payload=stock_report.model_dump(mode="json"),
        stock_history_payload=stock_history.model_dump(mode="json"),
        volatility_series_payload=volatility.model_dump(mode="json"),
        positioning_payload=positioning_payload,
        fundamentals_payload=fundamentals_payload,
        ohlcv_rows=ohlcv_rows,
    )
    analysis_hash = hash_trade_insights_ai_analysis_input(analysis_input)

    stubs: list[TradeInsightAiAnalysisStub] = []
    if settings.trade_insights_ai_enabled and (
        provider_filter is None or "codex" in provider_filter
    ):
        model_label = settings.trade_insights_ai_model.strip() or "codex-default"
        stubs.append(
            _enqueue_one_provider(
                t=t,
                run_id=run_id,
                snapshot_id=snapshot_id,
                trade_input_hash=trade_input_hash,
                analysis_hash=analysis_hash,
                analysis_input=analysis_input,
                provider="codex",
                model_label=model_label,
                force_rerun=force_rerun,
                repo=repo,
            )
        )
    if settings.trade_insights_ai_claude_enabled and (
        provider_filter is None or "claude" in provider_filter
    ):
        model_label = (
            settings.trade_insights_ai_claude_model.strip() or "claude-default"
        )
        stubs.append(
            _enqueue_one_provider(
                t=t,
                run_id=run_id,
                snapshot_id=snapshot_id,
                trade_input_hash=trade_input_hash,
                analysis_hash=analysis_hash,
                analysis_input=analysis_input,
                provider="claude",
                model_label=model_label,
                force_rerun=force_rerun,
                repo=repo,
            )
        )
    if settings.trade_insights_ai_deepseek_enabled and (
        provider_filter is None or "deepseek" in provider_filter
    ):
        model_label = (
            settings.trade_insights_ai_deepseek_model.strip() or "deepseek-default"
        )
        stubs.append(
            _enqueue_one_provider(
                t=t,
                run_id=run_id,
                snapshot_id=snapshot_id,
                trade_input_hash=trade_input_hash,
                analysis_hash=analysis_hash,
                analysis_input=analysis_input,
                provider="deepseek",
                model_label=model_label,
                force_rerun=force_rerun,
                repo=repo,
            )
        )
    repo.conn.commit()
    return TradeInsightAiAnalysisEnqueueResponse(analyses=stubs)


def _compute_provider_consensus(
    codex: TradeInsightAiAnalysisResponse | None,
    claude: TradeInsightAiAnalysisResponse | None,
) -> TradeInsightAiProviderConsensus:
    """v5.2: compute cross-provider agreement at GET /latest time.

    Compares the two providers' headline fields whenever both have a
    succeeded outcome. The UI surfaces consensus_grade +
    actionable_disagreement above the [Codex] [Claude] tabs.

    DELIBERATELY 2-PROVIDER (v1 DeepSeek scope decision, 2026-05-28):
    consensus stays a codex-vs-claude comparison even after deepseek was
    added as a third provider. Extending to 3-way consensus (majority
    vote? pairwise agreement? per-pair grades?) is a separate scoping
    question. DeepSeek queues, persists, and surfaces in /latest, but
    does NOT vote here."""
    if not (codex and codex.outcome and claude and claude.outcome):
        return TradeInsightAiProviderConsensus(consensus_grade="missing")

    cx_h = codex.outcome.headline
    cl_h = claude.outcome.headline
    cx_pref = codex.outcome.preferred_expression
    cl_pref = claude.outcome.preferred_expression

    bias_ok = cx_h.directional_bias == cl_h.directional_bias
    struct_ok = bool(cx_pref and cl_pref and cx_pref.structure == cl_pref.structure)
    state_ok = cx_h.entry_state == cl_h.entry_state
    path_ok = cx_h.underlying_path == cl_h.underlying_path
    dte_ok = cx_h.dte_band == cl_h.dte_band

    agreements = [bias_ok, struct_ok, state_ok, path_ok, dte_ok]
    n_agree = sum(1 for a in agreements if a)

    if n_agree == 5:
        grade = "full"
    elif n_agree >= 3:
        grade = "partial"
    else:
        grade = "divergent"

    # Single-sentence actionable disagreement string — only when there's
    # something to act on. Prioritize bias > structure > entry_state >
    # path > dte_band since those are the most consequential.
    disagreement = ""
    if not bias_ok:
        disagreement = (
            f"Directional bias differs: Codex={cx_h.directional_bias}, "
            f"Claude={cl_h.directional_bias}. Re-evaluate before sizing."
        )
    elif not struct_ok:
        cx_s = cx_pref.structure if cx_pref else "none"
        cl_s = cl_pref.structure if cl_pref else "none"
        disagreement = (
            f"Same directional bias but different structures: Codex={cx_s}, "
            f"Claude={cl_s}."
        )
    elif not state_ok:
        disagreement = (
            f"Entry state differs: Codex={cx_h.entry_state}, "
            f"Claude={cl_h.entry_state} — depends on whether the latest "
            "completed daily close satisfies the trigger."
        )
    elif not path_ok:
        disagreement = (
            f"Underlying path differs: Codex={cx_h.underlying_path}, "
            f"Claude={cl_h.underlying_path}. Same direction but different "
            "spatial archetype (rejection vs break)."
        )
    elif not dte_ok:
        disagreement = (
            f"DTE band differs: Codex={cx_h.dte_band}, Claude={cl_h.dte_band}."
        )

    return TradeInsightAiProviderConsensus(
        bias_agreement=bias_ok,
        structure_agreement=struct_ok,
        entry_state_agreement=state_ok,
        path_agreement=path_ok,
        dte_band_agreement=dte_ok,
        consensus_grade=grade,
        actionable_disagreement=disagreement,
    )


def _current_prompt_label() -> str:
    return PROMPT_VERSION.removeprefix("trade-insights-ai-")


@router.get(
    "/stock/{ticker}/trade-insights/ai-analysis/latest",
    response_model=TradeInsightAiLatestPair,
)
def get_latest_trade_insights_ai_analysis(
    ticker: str,
    repo: Repository = Depends(get_repo),
) -> TradeInsightAiLatestPair:
    """Latest terminal-state row per provider as a keyed dict.

    Returns {codex: row|null, claude: row|null}. Succeeded rows take priority
    over failed rows at the same finished_at; failed rows are returned (with
    error_message populated) when no succeeded row exists, so the UI can
    distinguish "never ran" from "ran and failed." 200 even when both are
    null so the UI renders the empty Run state instead of a 404.

    v5.2: also computes provider_consensus by comparing the two providers'
    headlines when both have a succeeded outcome (failed rows are treated as
    missing for consensus purposes — see _compute_provider_consensus).
    """
    pair = repo.find_latest_trade_insight_ai_analyses_per_provider(
        ticker=ticker.upper(),
        prompt_version=PROMPT_VERSION,
    )
    codex = _row_to_ai_response(pair["codex"]) if pair["codex"] else None
    claude = _row_to_ai_response(pair["claude"]) if pair["claude"] else None
    deepseek = _row_to_ai_response(pair["deepseek"]) if pair["deepseek"] else None
    return TradeInsightAiLatestPair(
        current_prompt_version=PROMPT_VERSION,
        current_prompt_label=_current_prompt_label(),
        codex=codex,
        claude=claude,
        deepseek=deepseek,
        provider_consensus=_compute_provider_consensus(codex, claude),
    )


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


@router.get(
    "/trade-insights/priors",
    response_model=TradeInsightAiPriorsResponse,
)
def get_trade_insight_priors(
    provider: str | None = None,
    prompt_version: str | None = None,
    archetype: str | None = None,
    bias: str | None = None,
    entry_state: str | None = None,
    repo: Repository = Depends(get_repo),
) -> TradeInsightAiPriorsResponse:
    """Per-provider per-archetype hit-rate priors from the outcome ledger.

    Reads `trade_insight_provider_archetype_priors` (migration 055).
    All filter parameters are optional; with none, returns every cohort
    across every provider/version/archetype/bias/entry_state combination
    that has at least one outcome row.

    `hit_rate_pct` is null when the cohort has zero resolved outcomes
    (everything is still pending). `sample_count` includes pending +
    resolved + expired; `target_hit_count` / `invalidation_hit_count` /
    `pending_count` / `expired_no_resolution_count` are the breakdown.

    Returns a 200 with an empty `priors` list when no rows match —
    callers should not treat empty as an error.
    """
    sql = """
        SELECT provider, prompt_version, thesis_archetype, directional_bias,
               entry_state, sample_count, target_hit_count,
               invalidation_hit_count, pending_count,
               expired_no_resolution_count, hit_rate_pct,
               median_days_to_resolution
          FROM uw_scan.trade_insight_provider_archetype_priors
         WHERE (%s::text IS NULL OR provider = %s)
           AND (%s::text IS NULL OR prompt_version = %s)
           AND (%s::text IS NULL OR thesis_archetype = %s)
           AND (%s::text IS NULL OR directional_bias = %s)
           AND (%s::text IS NULL OR entry_state = %s)
         ORDER BY sample_count DESC, provider, prompt_version
    """
    params = (
        provider,
        provider,
        prompt_version,
        prompt_version,
        archetype,
        archetype,
        bias,
        bias,
        entry_state,
        entry_state,
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    priors = [
        TradeInsightAiPriorRow(
            provider=row[0],
            prompt_version=row[1],
            thesis_archetype=row[2],
            directional_bias=row[3],
            entry_state=row[4],
            sample_count=row[5],
            target_hit_count=row[6],
            invalidation_hit_count=row[7],
            pending_count=row[8],
            expired_no_resolution_count=row[9],
            hit_rate_pct=row[10],
            median_days_to_resolution=row[11],
        )
        for row in rows
    ]
    return TradeInsightAiPriorsResponse(priors=priors)
