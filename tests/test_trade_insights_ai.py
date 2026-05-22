from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from uw_scan.models import (
    TradeInsightAiAnalysisResponse,
    TradeInsightAiOutcome,
    VolHeaderBlock,
)
from uw_scan.reports.trade_insights_ai import (
    PROMPT_VERSION,
    build_trade_insights_ai_analysis_input,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    hash_trade_insights_ai_analysis_input,
    render_trade_insights_ai_markdown,
    trade_insights_ai_output_schema,
    validate_trade_insights_ai_outcome,
)
from uw_scan.reports.volatility_series import assemble_volatility_series


def _sample_outcome() -> dict:
    produced_at = "2026-03-24T20:18:42Z"
    return {
        "schema_version": PROMPT_VERSION,
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
        prompt_version=PROMPT_VERSION,
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


def _source_payloads() -> dict[str, dict]:
    strike_rows = [
        {
            "expiry": "2026-05-15",
            "strike": str(300 + i),
            "net_gex": str(((-1) ** i) * (i + 1) * 1000),
            "call_gex": str(i * 100),
            "put_gex": str(-i * 50),
        }
        for i in range(50)
    ]
    chain_rows = [
        {
            "expiry": "2026-05-15",
            "strike": str(300 + i),
            "call_volume": i,
            "put_volume": 120 - i,
            "call_open_interest": i * 2,
            "put_open_interest": (120 - i) * 2,
        }
        for i in range(140)
    ]
    return {
        "stock_report": {
            "ticker": "TSLA",
            "generated_at": "2026-05-13T20:00:00Z",
            "market_structure": {
                "spot": "380.88",
                "net_gex": "1000000",
                "max_pain": "375",
            },
            "market_structure_levels": {
                "gex_flip": {"strike": "376.25", "net_gex": "0"},
                "call_wall": {"strike": "382.5", "net_gex": "100400000"},
                "put_wall": {"strike": "370", "net_gex": "-44200000"},
            },
            "strike_gex_curve": strike_rows,
            "max_pain_rows": [
                {"expiry": f"2026-06-{day:02d}", "max_pain": "375"}
                for day in range(1, 15)
            ],
            "flow": {
                "alert_count": 4,
                "net_premium": "524300000",
                "bull_premium": "2290000000",
                "bear_premium": "1770000000",
                "top_alerts": [{"id": str(i)} for i in range(10)],
            },
            "dark_pool_print_count": 8,
            "dark_pool_notional": "2300000",
            "short_data": {
                "short_shares_available": 1200000,
                "fee_rate": "0.35",
                "snapshot_at": "2026-03-23T21:00:00Z",
            },
            "options_timeline": [
                {"date": f"2026-03-{day:02d}", "call_volume": day}
                for day in range(1, 71)
            ],
            "option_chain_per_strike": chain_rows,
            "oi_change_top": [
                {"option_symbol": f"TSLA{i}", "volume": i} for i in range(50)
            ],
            "aggregates": {
                "call_volume_total": 1000,
                "put_volume_total": 900,
                "pcr_volume": "0.9",
                "iv30d": "0.42",
            },
            "next_earnings_date": "2026-04-22",
        },
        "stock_history": {
            "ticker": "TSLA",
            "rows": [
                {
                    "date": f"2026-02-{day:02d}",
                    "spot": str(350 + day),
                    "gex_flip": "376",
                    "net_gex": str(day),
                    "net_dex": str(day * 2),
                    "iv30d": "0.42",
                    "pcr_volume": "0.94",
                    "bias": "mixed",
                }
                for day in range(1, 36)
            ],
        },
        "volatility": {
            "ticker": "TSLA",
            "as_of": "2026-05-13",
            "backfill_status": "ready",
            "header": {
                "iv": "0.42",
                "rv": "0.311",
                "iv_rank": "3.4",
                "skew_25d": "0.014",
                "vrp": "0.076",
                "vrp_signal": "thin",
            },
            "term_structure": [
                {"expiry": f"2026-06-{day:02d}", "dte": day, "atm_iv": "0.40"}
                for day in range(1, 25)
            ],
            "smile": [
                {
                    "expiry": f"2026-06-{day:02d}",
                    "points": [
                        {"strike": str(300 + i), "iv": "0.40"} for i in range(30)
                    ],
                }
                for day in range(1, 8)
            ],
            "hv_iv_history": [
                {"date": f"2026-01-{(i % 28) + 1:02d}", "iv": "0.42", "rv": "0.31"}
                for i in range(95)
            ],
            "iv_percentile_distribution": {
                "current_iv": "0.42",
                "current_percentile": "0.034",
            },
            "iv_of_iv": [{"date": str(i), "value": "0.1"} for i in range(95)],
            "rv_spy_corr": [{"date": str(i), "value": "0.5"} for i in range(95)],
            "regime_quadrant": {"latest": {"label": "low_vol"}},
            "divergence": [{"date": str(i), "value": "0.01"} for i in range(25)],
            "divergence_headline": "No major divergence",
            "vrp_spread": [{"date": str(i), "vrp": "0.01"} for i in range(35)],
            "vrp_spread_headline": "Thin premium",
            "spot": "380.88",
        },
        "trade_insights": {
            "ticker": "TSLA",
            "as_of": "2026-05-13T20:01:00Z",
            "header": {
                "dominant_bias": "BULLISH",
                "primary_setup": "CHEAP_VOL_BREAKOUT",
                "confidence_label": "MEDIUM",
                "data_quality_label": "MIXED",
                "idea_count": 1,
                "preferred_idea_id": None,
            },
            "source_reconciliation": {"status": "UNKNOWN"},
            "signal_stack": [{"lens": "flow", "read": "bullish", "evidence": []}],
            "flow_table": [{"strike": "385", "read": "Call demand concentrated"}],
            "term_structure_table": [
                {"expiry": "2026-05-15", "read": "Front elevated"}
            ],
            "candidate_structures": [
                {
                    "idea_id": "A",
                    "structure": "bull_call_spread",
                    "status": "needs_check",
                    "risk_flags": ["verify_bid_ask"],
                    "max_loss": "6.40",
                    "max_profit": "8.60",
                    "rank": 1,
                },
                {
                    "idea_id": "C",
                    "structure": "long_straddle",
                    "status": "needs_check",
                    "risk_flags": [],
                    "max_loss": "12.00",
                    "max_profit": None,
                    "rank": 3,
                },
            ],
            "synthesis": {
                "dominant_story": "Cheap vol with bullish flow near resistance.",
                "preferred_idea_id": None,
                "required_before_sizing": ["Confirm event calendar"],
            },
        },
    }


def _analysis_input(**overrides):
    payloads = _source_payloads()
    payloads.update(overrides)
    return build_trade_insights_ai_analysis_input(
        ticker="TSLA",
        run_id=123,
        trade_insights_input_hash="sha256-trade-insights",
        trade_insights_payload=payloads["trade_insights"],
        stock_report_payload=payloads["stock_report"],
        stock_history_payload=payloads["stock_history"],
        volatility_series_payload=payloads["volatility"],
    )


def _sample_outcome_for(deterministic_payload: dict) -> dict:
    payload = _sample_outcome()
    payload["snapshot"]["run_id"] = deterministic_payload["run_id"]
    payload["snapshot"]["trade_insights_input_hash"] = deterministic_payload[
        "trade_insights_input_hash"
    ]
    payload["snapshot"]["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        deterministic_payload
    )
    return payload


def test_build_trade_insights_ai_analysis_input_uses_real_tab_payload_fields():
    analysis_input = _analysis_input()

    assert analysis_input["prompt_version"] == PROMPT_VERSION
    assert (
        analysis_input["tabs"]["market_structure"]["market_structure"]["spot"]
        == "380.88"
    )
    assert analysis_input["tabs"]["volatility"]["header"]["iv_rank"] == "3.4"
    assert analysis_input["tabs"]["flow"]["flow"]["net_premium"] == "524300000"
    assert analysis_input["tabs"]["positioning"]["short_data"]["fee_rate"] == "0.35"
    assert analysis_input["tabs"]["positioning"]["aggregates"]["pcr_volume"] == "0.9"
    assert analysis_input["tabs"]["trade_insights"]["synthesis"]["dominant_story"]
    assert analysis_input["candidate_structures"][0]["idea_id"] == "A"
    assert analysis_input["event_data_known"] is True


def test_trade_insights_ai_analysis_hash_is_stable_and_ignores_volatile_times():
    first = _analysis_input()
    payloads = _source_payloads()
    payloads["stock_report"]["generated_at"] = "2026-05-14T20:00:00Z"
    payloads["volatility"]["as_of"] = "2026-05-14"
    payloads["trade_insights"]["as_of"] = "2026-05-14T20:01:00Z"
    second = _analysis_input(
        stock_report=payloads["stock_report"],
        volatility=payloads["volatility"],
        trade_insights=payloads["trade_insights"],
    )

    assert hash_trade_insights_ai_analysis_input(
        first
    ) == hash_trade_insights_ai_analysis_input(second)

    prompt_payload = build_trade_insights_ai_prompt_payload(
        first,
        produced_at=datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc),
    )
    changed_prompt_payload = {
        **prompt_payload,
        "analysis_produced_at": "2026-03-25T20:18:42Z",
    }
    assert hash_trade_insights_ai_analysis_input(
        prompt_payload
    ) == hash_trade_insights_ai_analysis_input(changed_prompt_payload)


def test_trade_insights_ai_analysis_hash_changes_for_each_deterministic_lens():
    base_hash = hash_trade_insights_ai_analysis_input(_analysis_input())

    for key, mutate in [
        (
            "stock_report",
            lambda p: p["market_structure"].update({"net_gex": "changed"}),
        ),
        ("volatility", lambda p: p["header"].update({"iv_rank": "55"})),
        ("stock_report", lambda p: p["flow"].update({"net_premium": "1"})),
        ("stock_report", lambda p: p["short_data"].update({"fee_rate": "9.99"})),
        (
            "trade_insights",
            lambda p: p["synthesis"].update({"dominant_story": "changed"}),
        ),
    ]:
        payloads = _source_payloads()
        mutate(payloads[key])
        changed = _analysis_input(
            stock_report=payloads["stock_report"],
            volatility=payloads["volatility"],
            trade_insights=payloads["trade_insights"],
        )
        assert hash_trade_insights_ai_analysis_input(changed) != base_hash


def test_trade_insights_ai_prompt_prunes_long_arrays_and_allows_empty_history():
    analysis_input = _analysis_input()

    assert (
        len(analysis_input["tabs"]["market_structure"]["stock_history"]["rows"]) == 30
    )
    assert len(analysis_input["tabs"]["market_structure"]["strike_gex_curve"]) <= 43
    assert len(analysis_input["tabs"]["market_structure"]["max_pain_rows"]) == 12
    assert len(analysis_input["tabs"]["volatility"]["term_structure"]) == 20
    assert len(analysis_input["tabs"]["volatility"]["smile"]) == 6
    assert all(
        len(curve["points"]) <= 25
        for curve in analysis_input["tabs"]["volatility"]["smile"]
    )
    assert len(analysis_input["tabs"]["volatility"]["hv_iv_history"]) == 90
    assert len(analysis_input["tabs"]["flow"]["options_timeline"]) == 60
    assert len(analysis_input["tabs"]["flow"]["option_chain_per_strike"]) == 120

    payloads = _source_payloads()
    payloads["stock_history"]["rows"] = []
    payloads["volatility"]["hv_iv_history"] = []
    payloads["volatility"]["vrp_spread"] = []
    degraded = _analysis_input(
        stock_report={**payloads["stock_report"], "next_earnings_date": None},
        stock_history=payloads["stock_history"],
        volatility=payloads["volatility"],
    )
    assert degraded["tabs"]["market_structure"]["stock_history"]["rows"] == []
    assert degraded["tabs"]["volatility"]["hv_iv_history"] == []
    assert any("stock_history.rows" in note for note in degraded["missing_data"])
    assert any("volatility.hv_iv_history" in note for note in degraded["missing_data"])
    assert any("next_earnings_date" in note for note in degraded["missing_data"])
    assert degraded["event_data_known"] is False


def test_trade_insights_ai_prompt_payload_and_prompt_are_recommendation_oriented_guarded():
    analysis_input = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    prompt_payload = build_trade_insights_ai_prompt_payload(
        analysis_input,
        produced_at=produced_at,
    )
    prompt = build_trade_insights_ai_prompt(prompt_payload)

    assert prompt_payload["analysis_produced_at"] == "2026-03-24T20:18:42Z"
    assert prompt_payload[
        "analysis_input_hash"
    ] == hash_trade_insights_ai_analysis_input(analysis_input)
    assert (
        "You are an institutional options strategist analyzing one stock for a 1-2 week SWING HOLD entry."
        in prompt
    )
    # Swing-hold horizon is hard-coded, not optional context.
    assert "Time horizon (FIXED, not negotiable)" in prompt
    assert "The trade is HELD 5-10 trading sessions" in prompt
    assert "Entry-expiry DTE MUST be 28-45 (preferred) or 21-60 (allowed)" in prompt
    assert "horizon_mismatch" in prompt
    # New PR #60 / #61 evidence is wired into the payload key map.
    assert "tabs.market_structure.dealer_regime" in prompt
    assert "tabs.market_structure.exposures_summary" in prompt
    assert "tabs.market_structure.strike_exposures" in prompt
    # 4-section report structure replaces the prior 9-section template.
    assert "## Call" in prompt
    assert "## Why" in prompt
    assert "## Expiry Selection (mandatory)" in prompt
    assert "## Scenarios (3 rows, probabilities sum to 100%)" in prompt
    # No section_cards 1-9 grid, no needs_check deferral.
    assert "## 5. Cross-Pillar Conflict Resolution" not in prompt
    assert (
        "Do not defer solely because a deterministic candidate status is needs_check"
        in prompt
    )
    # Source-path discipline + schema_version are now appendix-level rules.
    assert "Source-path rule (HARD)" in prompt
    assert f"schema_version MUST be exactly the string {PROMPT_VERSION!r}" in prompt
    # idea_id rule and SWING-restricted preferred_expression.
    assert "idea_id rules (HARD)" in prompt
    for swing_family in ("long_call", "call_debit_spread", "iron_condor", "no_trade"):
        assert swing_family in prompt
    # Output framing: still research-only, still bounded JSON.
    assert "Emit only JSON" in prompt
    assert '"tabs"' in prompt


def test_trade_insights_ai_output_schema_requires_structured_sections():
    schema = trade_insights_ai_output_schema()

    assert schema["title"] == "TradeInsightAiOutcome"
    assert schema["properties"]["schema_version"]["const"] == PROMPT_VERSION
    assert schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"][
        "enum"
    ] == [
        "A",
        "B",
        "C",
        "D",
        "F",
    ]
    required = set(schema["required"])
    assert {
        "metric_cards",
        "scenario_cards",
        "score_breakdown",
        "section_cards",
        "dominant_read",
        "guardrails",
    } <= required
    assert schema["additionalProperties"] is False


def test_validate_trade_insights_ai_outcome_rejects_candidate_guardrail_drift():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    bad_idea = _sample_outcome_for(deterministic)
    bad_idea["best_expressions"][0]["idea_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="unknown idea_id"):
        validate_trade_insights_ai_outcome(
            bad_idea, deterministic, produced_at=produced_at
        )

    bad_status = _sample_outcome_for(deterministic)
    bad_status["preferred_expression"]["status_observed"] = "ready"
    with pytest.raises(ValueError, match="status_observed"):
        validate_trade_insights_ai_outcome(
            bad_status, deterministic, produced_at=produced_at
        )

    bad_flags = _sample_outcome_for(deterministic)
    bad_flags["preferred_expression"]["risk_flags_observed"] = []
    with pytest.raises(ValueError, match="risk_flags_observed"):
        validate_trade_insights_ai_outcome(
            bad_flags, deterministic, produced_at=produced_at
        )

    bad_guardrails = _sample_outcome_for(deterministic)
    bad_guardrails["guardrails"]["statuses_preserved"] = False
    with pytest.raises(ValueError, match="guardrails"):
        validate_trade_insights_ai_outcome(
            bad_guardrails, deterministic, produced_at=produced_at
        )

    bad_rating = _sample_outcome_for(deterministic)
    bad_rating["headline"]["conviction"] = "Medium-low actionable conviction"
    with pytest.raises(ValueError, match="final rating"):
        validate_trade_insights_ai_outcome(
            bad_rating, deterministic, produced_at=produced_at
        )

    bad_conflict_ref = _sample_outcome_for(deterministic)
    bad_conflict_ref["conflicts"][0]["affected_idea_ids"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="unknown idea_id"):
        validate_trade_insights_ai_outcome(
            bad_conflict_ref,
            deterministic,
            produced_at=produced_at,
        )


def test_validate_trade_insights_ai_outcome_allows_strategy_family_ids():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    strategy_read = _sample_outcome_for(deterministic)
    strategy_read["preferred_expression"]["idea_id"] = "long_stock"
    strategy_read["preferred_expression"]["structure"] = "long_stock"
    strategy_read["preferred_expression"]["status_observed"] = "strategy_review"
    strategy_read["preferred_expression"]["risk_flags_observed"] = []
    strategy_read["best_expressions"][0]["idea_id"] = "long_stock"
    strategy_read["best_expressions"][0]["structure"] = "long_stock"
    strategy_read["best_expressions"][0]["status_observed"] = "strategy_review"
    strategy_read["best_expressions"][0]["risk_flags_observed"] = []
    strategy_read["rejected_ideas"][0]["idea_id"] = "short_strangle"
    strategy_read["rejected_ideas"][0]["structure"] = "short_strangle"

    parsed = validate_trade_insights_ai_outcome(
        strategy_read,
        deterministic,
        produced_at=produced_at,
    )

    assert parsed.preferred_expression is not None
    assert parsed.preferred_expression.idea_id == "long_stock"
    assert parsed.best_expressions[0].status_observed == "strategy_review"


def test_validate_trade_insights_ai_outcome_rejects_undefined_risk_preferred_strategy():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    preferred_short_strangle = _sample_outcome_for(deterministic)
    preferred_short_strangle["preferred_expression"]["idea_id"] = "short_strangle"
    preferred_short_strangle["preferred_expression"]["structure"] = "short_strangle"
    preferred_short_strangle["preferred_expression"]["status_observed"] = (
        "strategy_review"
    )
    preferred_short_strangle["preferred_expression"]["risk_flags_observed"] = []
    with pytest.raises(ValueError, match="undefined-risk"):
        validate_trade_insights_ai_outcome(
            preferred_short_strangle,
            deterministic,
            produced_at=produced_at,
        )

    best_short_strangle = _sample_outcome_for(deterministic)
    best_short_strangle["best_expressions"][0]["idea_id"] = "short_strangle"
    best_short_strangle["best_expressions"][0]["structure"] = "short_strangle"
    best_short_strangle["best_expressions"][0]["status_observed"] = "strategy_review"
    best_short_strangle["best_expressions"][0]["risk_flags_observed"] = []
    with pytest.raises(ValueError, match="undefined-risk"):
        validate_trade_insights_ai_outcome(
            best_short_strangle,
            deterministic,
            produced_at=produced_at,
        )


def test_validate_trade_insights_ai_outcome_rejects_time_and_section_mismatches():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    bad_time = _sample_outcome_for(deterministic)
    bad_time["analysis_produced_at"] = "2026-03-24T20:19:42Z"
    with pytest.raises(ValueError, match="analysis_produced_at"):
        validate_trade_insights_ai_outcome(
            bad_time, deterministic, produced_at=produced_at
        )

    missing_section = _sample_outcome_for(deterministic)
    del missing_section["section_cards"]["flow_positioning"]
    with pytest.raises(ValidationError):
        validate_trade_insights_ai_outcome(
            missing_section,
            deterministic,
            produced_at=produced_at,
        )


def test_validate_trade_insights_ai_outcome_rejects_source_path_problems():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    # `charm` / `vanna` paths are no longer unavailable since PR #60 forwarded
    # exposures_summary + strike_exposures into the payload. A non-existent
    # charm path now falls through to the generic prefix-existence check.
    nonexistent_charm = _sample_outcome_for(deterministic)
    nonexistent_charm["metric_cards"][0]["source_path"] = (
        "tabs.market_structure.charm_summary"
    )
    with pytest.raises(ValueError, match="source_path"):
        validate_trade_insights_ai_outcome(
            nonexistent_charm, deterministic, produced_at=produced_at
        )

    missing_source_path = _sample_outcome_for(deterministic)
    missing_source_path["metric_cards"][0]["source_path"] = None
    with pytest.raises(ValueError, match="source_path"):
        validate_trade_insights_ai_outcome(
            missing_source_path,
            deterministic,
            produced_at=produced_at,
        )

    bad_prefix = _sample_outcome_for(deterministic)
    bad_prefix["metric_cards"][0]["source_path"] = "tabs.flow.not_a_real_family"
    with pytest.raises(ValueError, match="source_path"):
        validate_trade_insights_ai_outcome(
            bad_prefix, deterministic, produced_at=produced_at
        )

    bad_leaf = _sample_outcome_for(deterministic)
    bad_leaf["metric_cards"][0]["source_path"] = "tabs.volatility.header.not_real"
    with pytest.raises(ValueError, match="source_path"):
        validate_trade_insights_ai_outcome(
            bad_leaf, deterministic, produced_at=produced_at
        )


def test_validate_trade_insights_ai_outcome_accepts_array_family_source_paths():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    wildcard_path = _sample_outcome_for(deterministic)
    wildcard_path["metric_cards"][0]["source_path"] = (
        "tabs.market_structure.stock_history.rows[].net_dex"
    )

    parsed = validate_trade_insights_ai_outcome(
        wildcard_path,
        deterministic,
        produced_at=produced_at,
    )

    assert parsed.metric_cards[0].source_path.endswith("rows[].net_dex")


def test_validate_trade_insights_ai_outcome_canonicalizes_nested_stock_history_path():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    nested_path = _sample_outcome_for(deterministic)
    nested_path["metric_cards"][0]["source_path"] = (
        "tabs.market_structure.market_structure.stock_history.rows[0].net_dex"
    )

    parsed = validate_trade_insights_ai_outcome(
        nested_path,
        deterministic,
        produced_at=produced_at,
    )

    assert (
        parsed.metric_cards[0].source_path
        == "tabs.market_structure.stock_history.rows[0].net_dex"
    )


def test_validate_trade_insights_ai_outcome_accepts_negative_array_source_paths():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    latest_path = _sample_outcome_for(deterministic)
    latest_path["metric_cards"][0]["source_path"] = (
        "tabs.volatility.hv_iv_history[-1].rv"
    )

    parsed = validate_trade_insights_ai_outcome(
        latest_path,
        deterministic,
        produced_at=produced_at,
    )

    assert parsed.metric_cards[0].source_path.endswith("hv_iv_history[-1].rv")


def test_validate_trade_insights_ai_outcome_accepts_sparse_array_source_paths():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    sparse_path = _sample_outcome_for(deterministic)
    sparse_path["metric_cards"][0]["source_path"] = (
        "tabs.flow.option_chain_per_strike[].call_open_interest"
    )
    deterministic["tabs"]["flow"]["option_chain_per_strike"][0].pop(
        "call_open_interest",
        None,
    )
    sparse_path["snapshot"]["analysis_input_hash"] = (
        hash_trade_insights_ai_analysis_input(deterministic)
    )

    parsed = validate_trade_insights_ai_outcome(
        sparse_path,
        deterministic,
        produced_at=produced_at,
    )

    assert parsed.metric_cards[0].source_path.endswith("call_open_interest")


def test_validate_trade_insights_ai_outcome_rejects_field_aware_imperatives():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    allowed = _sample_outcome_for(deterministic)
    allowed["headline"]["stance_label"] = "BUY setup"
    assert validate_trade_insights_ai_outcome(
        allowed, deterministic, produced_at=produced_at
    )

    rejected = _sample_outcome_for(deterministic)
    rejected["preferred_expression"]["title"] = "Buy now"
    with pytest.raises(ValueError, match="imperative"):
        validate_trade_insights_ai_outcome(
            rejected, deterministic, produced_at=produced_at
        )

    advice_order = _sample_outcome_for(deterministic)
    advice_order["preferred_expression"]["why"] = (
        "You should buy this spread because flow is bullish."
    )
    with pytest.raises(ValueError, match="imperative"):
        validate_trade_insights_ai_outcome(
            advice_order,
            deterministic,
            produced_at=produced_at,
        )


def test_render_trade_insights_ai_markdown_uses_structured_sections():
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    outcome = validate_trade_insights_ai_outcome(
        _sample_outcome_for(deterministic),
        deterministic,
        produced_at=produced_at,
    )

    markdown = render_trade_insights_ai_markdown(outcome)

    assert "TSLA near gamma resistance" in markdown
    assert "IV Rank" in markdown
    assert "Break $382.50 wall" in markdown
    assert "Market Structure" in markdown
    assert "Volatility" in markdown
    assert "Flow & Positioning" in markdown
    assert "VRP Assessment" in markdown
    assert "Bull Call Spread" in markdown
    assert "Confirm event calendar" in markdown
    assert "No event calendar data" in markdown


class _FakeVolRepo:
    def __init__(self, rv_rows: list[dict] | None = None):
        self.rv_rows = (
            rv_rows
            if rv_rows is not None
            else [
                {
                    "market_date": "2026-03-20",
                    "price": "100",
                    "implied_volatility": "0.40",
                    "realized_volatility": "0.30",
                },
                {
                    "market_date": "2026-03-21",
                    "price": "101",
                    "implied_volatility": "0.41",
                    "realized_volatility": "0.31",
                },
            ]
        )
        self.conn = self
        self.commits = 0

    def commit(self):
        self.commits += 1

    def fetch_realized_vol_history(self, ticker, days=365):
        return list(self.rv_rows)

    def fetch_index_ohlc_series(self, ticker):
        return []

    def fetch_realized_vol_latest(self, ticker):
        return {"price": "101"} if self.rv_rows else {}


def test_assemble_volatility_series_read_only_mode_skips_derived_persistence(
    monkeypatch,
):
    repo = _FakeVolRepo()
    calls = {"vrp": 0, "analytics": 0}

    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_header",
        lambda repo, ticker: VolHeaderBlock(iv="0.41", rv="0.31"),
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_term_structure",
        lambda repo, ticker: [],
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_smile",
        lambda repo, ticker: [],
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.persist_vrp_daily",
        lambda *args: calls.__setitem__("vrp", calls["vrp"] + 1),
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.persist_stock_analytics",
        lambda *args: calls.__setitem__("analytics", calls["analytics"] + 1),
    )

    default_response = assemble_volatility_series(ticker="TSLA", repo=repo)
    read_only_response = assemble_volatility_series(
        ticker="TSLA",
        repo=repo,
        persist_derived=False,
    )

    assert default_response.model_dump(mode="json") == read_only_response.model_dump(
        mode="json"
    )
    assert calls == {"vrp": 1, "analytics": 1}
    assert repo.commits == 1


def test_assemble_volatility_series_read_only_mode_accepts_empty_history(
    monkeypatch,
):
    repo = _FakeVolRepo(rv_rows=[])
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_header",
        lambda repo, ticker: VolHeaderBlock(),
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_term_structure",
        lambda repo, ticker: [],
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series._build_smile",
        lambda repo, ticker: [],
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.persist_vrp_daily",
        lambda *args: pytest.fail("read-only mode should not persist VRP"),
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.persist_stock_analytics",
        lambda *args: pytest.fail("read-only mode should not persist analytics"),
    )

    response = assemble_volatility_series(
        ticker="TSLA",
        repo=repo,
        backfill_status="missing",
        persist_derived=False,
    )

    assert response.ticker == "TSLA"
    assert response.backfill_status == "missing"
    assert response.hv_iv_history == []
    assert response.vrp_spread == []
    assert repo.commits == 0


def test_to_decimal_returns_none_for_invalid_input():
    """R1: _to_decimal previously returned Decimal('0') on any conversion
    failure (including the very common case of a missing dict key returning
    None from .get()). It must return None instead so call sites can decide
    explicitly between 'treat as 0' and 'sort to end'."""
    from decimal import Decimal

    from uw_scan.reports.trade_insights_ai import _to_decimal

    assert _to_decimal(None) is None
    assert _to_decimal("not a number") is None
    assert _to_decimal("") is None

    # Valid inputs still coerce.
    assert _to_decimal("3.14") == Decimal("3.14")
    assert _to_decimal(42) == Decimal(42)
    assert _to_decimal(Decimal("1.5")) == Decimal("1.5")


def test_validate_lenient_captures_partial_claude_output():
    """Issue #67: Claude often drops top-level required fields (snapshot,
    analysis_produced_at, headline.stance/stance_label) while inventing peer
    keys like primary_setup, time_horizon. Lenient mode synthesizes the
    missing identity fields from the deterministic payload and accepts
    Claude's actual content for everything else."""
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    # Resembles a real Claude off-schema response: missing snapshot/produced_at,
    # invented headline keys, missing required headline fields, missing the
    # required nested models (dominant_read, section_cards, etc.).
    partial = {
        "schema_version": "WRONG_VERSION",  # should get overwritten
        "ticker": "WRONG",  # should get overwritten with deterministic value
        "headline": {
            "primary_setup": "TRADE_BULLISH",  # unknown key — should be stripped
            "time_horizon": "1-2 weeks",  # unknown key — should be stripped
            "title": "TSLA — bullish swing setup",
            "top_reason": "Cheap IV + bullish flow above gex_flip",
            # stance/stance_label/score/conviction/etc. all missing
        },
        "missing_data": ["headline.stance not produced by provider"],
    }

    parsed = validate_trade_insights_ai_outcome(
        partial,
        deterministic,
        produced_at=produced_at,
        lenient=True,
    )

    # Identity fields force-overwritten from deterministic payload
    assert parsed.schema_version == PROMPT_VERSION
    assert parsed.ticker == "TSLA"
    assert parsed.snapshot.run_id == 123
    assert parsed.snapshot.trade_insights_input_hash == "sha256-trade-insights"
    # analysis_produced_at round-trips to the worker-provided timestamp
    assert parsed.analysis_produced_at == produced_at

    # Claude's actual content preserved where present
    assert parsed.headline.title == "TSLA — bullish swing setup"
    assert parsed.headline.top_reason == "Cheap IV + bullish flow above gex_flip"

    # Missing required scalars get safe placeholders
    assert parsed.headline.stance == "mixed"  # invalid-Literal fallback
    assert parsed.headline.conviction == "F"  # F = data insufficient
    assert parsed.headline.score == 0

    # Provider-noted missing data is preserved (with our placeholder prepended)
    assert any("partial output" in note.lower() for note in parsed.missing_data)
    assert "headline.stance not produced by provider" in parsed.missing_data


def test_validate_lenient_skips_idea_id_and_source_path_checks():
    """Lenient mode skips the Codex-style provider-consistency checks: unknown
    idea_ids, source_path family validation, and guardrails-truthy. Those would
    otherwise prevent partial Claude output from landing at all."""
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    # Take the strict happy-path outcome but introduce things strict would reject.
    payload = _sample_outcome_for(deterministic)
    payload["best_expressions"][0]["idea_id"] = "UNKNOWN_IDEA"
    payload["metric_cards"][0]["source_path"] = "tabs.flow.not_a_real_family"
    payload["guardrails"]["statuses_preserved"] = False

    # Strict: rejects on the first failure
    with pytest.raises(ValueError):
        validate_trade_insights_ai_outcome(
            payload, deterministic, produced_at=produced_at
        )

    # Lenient: accepts and captures
    parsed = validate_trade_insights_ai_outcome(
        payload,
        deterministic,
        produced_at=produced_at,
        lenient=True,
    )
    assert parsed.best_expressions[0].idea_id == "UNKNOWN_IDEA"
    assert parsed.metric_cards[0].source_path == "tabs.flow.not_a_real_family"
    assert parsed.guardrails.statuses_preserved is False


def test_validate_lenient_still_rejects_imperative_text():
    """Safety guardrail: imperative trade instructions ("execute this trade",
    "go long now") must be rejected even in lenient mode. The whole point of
    that check is to block research-only output that crosses into order-placement
    language; provider quirks don't get to bypass it."""
    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    payload = {
        "headline": {
            "title": "TSLA setup",
            "stance_label": "buy now: bullish swing",
        }
    }
    with pytest.raises(ValueError, match="imperative"):
        validate_trade_insights_ai_outcome(
            payload, deterministic, produced_at=produced_at, lenient=True
        )


def test_coerce_claude_outcome_strips_unknown_keys():
    """Pydantic models in this contract use extra='forbid'. The lenient coercer
    must strip unknown keys at every nesting level so the resulting dict
    round-trips through model_validate without ValidationError."""
    from uw_scan.reports.trade_insights_ai import _coerce_claude_outcome_dict

    deterministic = _analysis_input()
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    expected_hash = hash_trade_insights_ai_analysis_input(deterministic)

    raw = {
        "headline": {
            "title": "Test",
            "stance": "bullish",
            "stance_label": "Bullish",
            "conviction": "B",
            "conviction_label": "Moderate",
            "top_reason": "r",
            "primary_risk": "k",
            "watch_trigger": "t",
            "score": 50,
            "INVENTED_FIELD": "should be dropped",
        },
        "INVENTED_TOP_LEVEL": {"nested": "junk"},
        "section_cards": {
            "market_structure": {
                "title": "MS",
                "summary": "s",
                "INVENTED_SECTION_FIELD": "drop me",
            },
        },
    }

    coerced = _coerce_claude_outcome_dict(
        raw,
        deterministic,
        produced_at=produced_at,
        expected_analysis_input_hash=expected_hash,
    )

    # Unknown top-level key dropped
    assert "INVENTED_TOP_LEVEL" not in coerced
    # Unknown nested key dropped
    assert "INVENTED_FIELD" not in coerced["headline"]
    assert "INVENTED_SECTION_FIELD" not in coerced["section_cards"]["market_structure"]
    # And it round-trips through Pydantic
    TradeInsightAiOutcome.model_validate(coerced)
