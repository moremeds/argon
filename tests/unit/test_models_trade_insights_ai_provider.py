"""Unit tests for new provider-aware Trade Insights AI Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from uw_scan.models import (
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiAnalysisResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiBase,
    TradeInsightAiLatestPair,
    TradeInsightAiOutcome,
    TradeInsightAiProvider,
)


def test_provider_literal_accepts_codex_and_claude() -> None:
    stub = TradeInsightAiAnalysisStub(
        provider="codex",
        analysis_id=uuid4(),
        status="queued",
        reused=False,
        model="codex-default",
    )
    assert stub.provider == "codex"
    stub2 = stub.model_copy(update={"provider": "claude"})
    assert stub2.provider == "claude"


def test_provider_literal_accepts_deepseek() -> None:
    """After widening for the DeepSeek runner, the Literal accepts "deepseek"."""
    stub = TradeInsightAiAnalysisStub(
        provider="deepseek",
        analysis_id=uuid4(),
        status="queued",
        reused=False,
        model="deepseek-v4-pro",
    )
    assert stub.provider == "deepseek"


def test_provider_literal_rejects_other_values() -> None:
    with pytest.raises(ValueError):
        TradeInsightAiAnalysisStub(
            provider="openai",  # type: ignore[arg-type]
            analysis_id=uuid4(),
            status="queued",
            reused=False,
            model="x",
        )


def test_enqueue_response_holds_list_of_stubs() -> None:
    resp = TradeInsightAiAnalysisEnqueueResponse(
        analyses=[
            TradeInsightAiAnalysisStub(
                provider="codex",
                analysis_id=uuid4(),
                status="queued",
                reused=False,
                model="codex-default",
            ),
            TradeInsightAiAnalysisStub(
                provider="claude",
                analysis_id=uuid4(),
                status="succeeded",
                reused=True,
                model="claude-opus-4-7",
            ),
        ]
    )
    assert len(resp.analyses) == 2
    assert {a.provider for a in resp.analyses} == {"codex", "claude"}


def test_latest_pair_allows_null_per_provider() -> None:
    pair = TradeInsightAiLatestPair(
        codex=None,
        claude=None,
        current_prompt_version="trade-insights-ai-v5.3",
    )
    assert pair.codex is None
    assert pair.claude is None
    assert pair.current_prompt_version == "trade-insights-ai-v5.3"


def test_analysis_response_has_provider_and_model_fields() -> None:
    now = datetime.now(timezone.utc)
    resp = TradeInsightAiAnalysisResponse(
        analysis_id=uuid4(),
        ticker="TSLA",
        run_id=1,
        trade_insights_input_hash="x",
        analysis_input_hash="y",
        model="codex-default",
        provider="codex",
        prompt_version="trade-insights-ai-v4",
        status="queued",
        requested_at=now,
        reused=False,
    )
    assert resp.provider == "codex"
    assert resp.model == "codex-default"


def test_provider_alias_is_a_str_literal_at_runtime() -> None:
    # Literal["codex", "claude"] resolves to str at runtime; this just sanity
    # checks the alias exists and is importable.
    assert TradeInsightAiProvider is not None


def test_public_trade_insights_ai_modules_remain_stable() -> None:
    assert TradeInsightAiBase.__module__ == "uw_scan.models"
    assert TradeInsightAiOutcome.__module__ == "uw_scan.models"
    assert TradeInsightAiAnalysisResponse.__module__ == "uw_scan.models"
