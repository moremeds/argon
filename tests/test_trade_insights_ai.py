from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from uw_scan.models import (
    TradeInsightAiAnalysisResponse,
    TradeInsightAiOutcome,
)


def _sample_outcome() -> dict:
    produced_at = "2026-03-24T20:18:42Z"
    return {
        "schema_version": "trade-insights-ai-v1",
        "analysis_produced_at": produced_at,
        "ticker": "TSLA",
        "underlying_price": "$380.88",
        "snapshot": {
            "run_id": 123,
            "trade_insights_input_hash": "sha256-trade-insights",
            "analysis_input_hash": "sha256-combined",
            "data_as_of": "2026-03-24",
            "freshness_label": "mixed",
            "source_notes": ["Flow: same-day snapshot"],
        },
        "headline": {
            "title": "TSLA near gamma resistance with cheap vol and bullish flow",
            "stance": "bullish",
            "stance_label": "BUY setup",
            "score": 31,
            "score_scale": 100,
            "conviction": "B",
            "conviction_label": "Moderate",
            "top_reason": "Cheap IV plus bullish flow",
            "primary_risk": "$382.50 GEX wall may cap immediate upside",
            "watch_trigger": "Break above $382.50 with volume",
        },
        "metric_cards": [
            {
                "label": "IV Rank",
                "value": "3.4/100",
                "tone": "bullish",
                "source_path": "tabs.volatility.header.iv_rank",
                "note": "Options screen historically cheap.",
            }
        ],
        "scenario_cards": [
            {
                "case": "upside",
                "tone": "bullish",
                "title": "Break $382.50 wall",
                "description": "$392-$400 target zone from supplied GEX levels.",
            }
        ],
        "score_breakdown": [
            {
                "section": "market_structure",
                "score": 8,
                "max_score": 28,
                "summary": "Positive gamma with nearby resistance.",
            }
        ],
        "section_cards": {
            "market_structure": {
                "title": "Market Structure",
                "score": 8,
                "max_score": 28,
                "summary": "Positive gamma above the flip.",
                "highlights": [
                    {
                        "label": "GEX Flip",
                        "value": "$376.25",
                        "source_path": "tabs.market_structure.market_structure_levels.gex_flip",
                    }
                ],
                "levels": [
                    {
                        "price": "$382.50",
                        "kind": "resistance",
                        "value": "+$100.4M",
                        "importance": "major",
                        "source_path": "tabs.market_structure.strike_gex_curve",
                    }
                ],
                "data_quality": "high",
            },
            "volatility": {
                "title": "Volatility",
                "score": 8,
                "max_score": 28,
                "summary": "IV is cheap versus its own range.",
                "highlights": [],
                "levels": [],
                "data_quality": "medium",
            },
            "flow_positioning": {
                "title": "Flow & Positioning",
                "score": 15,
                "max_score": 44,
                "summary": "Bullish net premium supports breakout monitoring.",
                "highlights": [],
                "levels": [],
                "data_quality": "medium",
            },
        },
        "vrp_assessment": {
            "signal": "do_not_sell",
            "title": "VRP Assessment - Do Not Sell",
            "summary": "IV rank is near the 52-week floor.",
            "metrics": [{"label": "VRP", "value": "7.6%"}],
            "reason": "Failed VRP entry threshold in supplied deterministic data.",
        },
        "preferred_expression": {
            "idea_id": "A",
            "structure": "bull_call_spread",
            "title": "Bull Call Spread - TSLA",
            "subtitle": "Buy $385 Call / Sell $400 Call - Apr 17, 2026",
            "estimated_entry": "~$6.40 debit",
            "max_profit_observed": "~$8.60",
            "max_loss_observed": "~$6.40",
            "reward_risk": "1.34:1",
            "why": "The supplied candidate is the cleanest defined-risk expression.",
            "management_notes": ["Verify before sizing."],
            "status_observed": "needs_check",
            "risk_flags_observed": ["verify_bid_ask"],
        },
        "dominant_read": {
            "headline": "Cheap vol with bullish flow near resistance.",
            "summary": "Plain-English synthesis of deterministic evidence.",
            "confidence_commentary": "Moderate confidence.",
            "data_quality_commentary": "Mixed freshness.",
        },
        "best_expressions": [
            {
                "idea_id": "A",
                "structure": "bull_call_spread",
                "role": "best_defined_risk_long_delta_expression",
                "why": "Grounded in supplied deterministic fields.",
                "caveats": ["Needs bid/ask verification."],
                "status_observed": "needs_check",
                "risk_flags_observed": ["verify_bid_ask"],
            }
        ],
        "conflicts": [
            {
                "lens": "flow_vs_structure",
                "severity": "medium",
                "description": "Bullish flow conflicts with nearby resistance.",
                "affected_idea_ids": ["A"],
            }
        ],
        "required_checks": [
            {
                "check": "Confirm event calendar",
                "reason": "The deterministic payload marks event_data_known=false.",
                "blocks_sizing": True,
                "source": "synthesis.required_before_sizing",
            }
        ],
        "rejected_ideas": [
            {
                "idea_id": "C",
                "structure": "long_straddle",
                "reason": "No clear long-vol edge in supplied deterministic setup.",
            }
        ],
        "missing_data": ["No event calendar data in deterministic payload."],
        "rendering": {
            "disclaimer": "Generated by local Codex from deterministic Trade Insights data. Not financial advice.",
            "card_order": [
                "headline",
                "metrics",
                "scenarios",
                "market_structure",
                "volatility",
                "flow_positioning",
            ],
        },
        "guardrails": {
            "statuses_preserved": True,
            "risk_flags_preserved": True,
            "no_executable_recommendations": True,
        },
    }


def test_trade_insight_ai_outcome_serializes_required_sections():
    outcome = TradeInsightAiOutcome.model_validate(_sample_outcome())

    body = outcome.model_dump(mode="json")

    assert body["ticker"] == "TSLA"
    assert body["headline"]["stance"] == "bullish"
    assert body["metric_cards"][0]["source_path"] == "tabs.volatility.header.iv_rank"
    assert body["section_cards"]["market_structure"]["title"] == "Market Structure"
    assert body["section_cards"]["volatility"]["title"] == "Volatility"
    assert body["section_cards"]["flow_positioning"]["title"] == "Flow & Positioning"
    assert body["guardrails"]["statuses_preserved"] is True


def test_trade_insight_ai_outcome_rejects_unknown_extra_fields():
    payload = _sample_outcome()
    payload["hallucinated_field"] = "nope"

    with pytest.raises(ValidationError):
        TradeInsightAiOutcome.model_validate(payload)


def test_trade_insight_ai_analysis_response_includes_queue_and_hash_fields():
    response = TradeInsightAiAnalysisResponse(
        analysis_id=UUID("00000000-0000-0000-0000-000000000123"),
        ticker="TSLA",
        run_id=123,
        trade_insights_input_hash="sha256-trade-insights",
        analysis_input_hash="sha256-combined",
        model="codex-default",
        prompt_version="trade-insights-ai-v1",
        status="queued",
        requested_at=datetime(2026, 3, 24, 20, 0, tzinfo=timezone.utc),
    )

    body = response.model_dump(mode="json")

    assert body["analysis_id"] == "00000000-0000-0000-0000-000000000123"
    assert body["trade_insights_input_hash"] == "sha256-trade-insights"
    assert body["analysis_input_hash"] == "sha256-combined"
    assert body["produced_at"] is None
    assert body["outcome"] is None
    assert body["markdown"] is None
