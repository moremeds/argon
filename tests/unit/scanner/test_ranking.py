"""build_candidate and rank_candidates — DP-only suppression + ordering."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.scanner.models import ContextFlag, SignalHit
from uw_scan.scanner.ranking import (
    build_candidate,
    derive_bias,
    derive_setup,
    rank_candidates,
)


def _hit(
    signal_type: str,
    tier: int,
    score: str,
    *,
    direction: str | None = None,
) -> SignalHit:
    evidence: dict[str, object] = {}
    if direction is not None:
        evidence["direction"] = direction
    return SignalHit(
        ticker="AAPL",
        signal_type=signal_type,
        tier=tier,
        score=Decimal(score),
        evidence=evidence,
        freshness="live",
    )


def test_dp_only_ticker_produces_no_candidate():
    cand = build_candidate(
        ticker="AAPL",
        hits=[_hit("dark_pool_accumulation", 2, "0.50")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is None


def test_dcf_only_ticker_produces_candidate_not_type_f():
    cand = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.70")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is not None
    assert cand.is_type_f is False
    # raw = 0.70 * 3.0 = 2.10; confluence = 3.0; final = 5.10
    assert cand.raw_score == Decimal("2.10")
    assert cand.confluence_score == Decimal("3.0")
    assert cand.final_score == Decimal("5.10")


def test_dcf_plus_eic_is_type_f_with_correct_score():
    cand = build_candidate(
        ticker="AAPL",
        hits=[
            _hit("deep_conviction_flow", 1, "0.85"),
            _hit("dark_pool_accumulation", 2, "0.40"),
            _hit("earnings_iv_crush", 1, "0.72"),
        ],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is not None
    assert cand.is_type_f is True
    # raw = 0.85*3 + 0.72*3 = 4.71; conf = 3 + 1.5 + 3 = 7.5; final = 12.21
    assert cand.raw_score == Decimal("4.71")
    assert cand.confluence_score == Decimal("7.5")
    assert cand.final_score == Decimal("12.21")


def test_rank_candidates_orders_type_f_first_then_score_then_ticker():
    type_f = build_candidate(
        ticker="AAPL",
        hits=[
            _hit("deep_conviction_flow", 1, "0.85"),
            _hit("earnings_iv_crush", 1, "0.72"),
        ],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    big_single = build_candidate(
        ticker="MSFT",
        hits=[_hit("deep_conviction_flow", 1, "1.0")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    small_single = build_candidate(
        ticker="ZZZZ",
        hits=[_hit("deep_conviction_flow", 1, "0.50")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert type_f is not None and big_single is not None and small_single is not None
    ranked = rank_candidates([small_single, big_single, type_f])
    assert [c.ticker for c in ranked] == ["AAPL", "MSFT", "ZZZZ"]


def test_derive_bias_bullish_strong_from_high_score_call_dcf():
    bias, strength = derive_bias(
        [_hit("deep_conviction_flow", 1, "0.95", direction="long")]
    )
    assert bias == "bullish"
    assert strength == "strong"


def test_derive_bias_bearish_moderate_from_mid_score_put_dcf():
    bias, strength = derive_bias(
        [_hit("deep_conviction_flow", 1, "0.75", direction="short")]
    )
    assert bias == "bearish"
    assert strength == "moderate"


def test_derive_bias_weak_when_dcf_score_below_moderate_threshold():
    bias, strength = derive_bias(
        [_hit("deep_conviction_flow", 1, "0.60", direction="long")]
    )
    assert bias == "bullish"
    assert strength == "weak"


def test_derive_bias_neutral_when_no_dcf():
    bias, strength = derive_bias(
        [
            _hit("dark_pool_accumulation", 2, "0.90"),
            _hit("gex_pinning", 1, "0.80"),
        ]
    )
    assert bias == "neutral"
    assert strength is None


def test_derive_bias_neutral_when_dcf_direction_missing_or_unknown():
    bias, strength = derive_bias(
        [_hit("deep_conviction_flow", 1, "0.90", direction="unknown")]
    )
    assert bias == "neutral"
    assert strength is None


def test_derive_setup_ready_when_all_gates_pass():
    setup, reason = derive_setup(
        {"earnings": "pass", "liquidity": "pass", "regime": "pass"}
    )
    assert setup == "ready"
    assert reason is None


def test_derive_setup_caution_when_earnings_blocks():
    setup, reason = derive_setup(
        {"earnings": "block", "liquidity": "pass", "regime": "pass"}
    )
    assert setup == "caution"
    assert reason == "earnings"


def test_derive_setup_caution_when_liquidity_blocks():
    setup, reason = derive_setup(
        {"earnings": "pass", "liquidity": "block", "regime": "pass"}
    )
    assert setup == "caution"
    assert reason == "liquidity"


def test_derive_setup_ready_when_only_legacy_regime_blocks():
    setup, reason = derive_setup(
        {"earnings": "pass", "liquidity": "pass", "regime": "block"}
    )
    assert setup == "ready"
    assert reason is None


def test_build_candidate_attaches_bias_and_setup():
    cand = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.95", direction="short")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is not None
    assert cand.bias == "bearish"
    assert cand.bias_strength == "strong"
    assert cand.setup == "ready"
    assert cand.setup_reason is None


def test_context_flags_passthrough_does_not_affect_score():
    flag = ContextFlag(
        ticker="AAPL",
        layer="pcr_sentiment",
        label="Extreme Fear",
        value=Decimal("1.7"),
    )
    cand_with = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.85")],
        context_flags=[flag],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    cand_without = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.85")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand_with is not None and cand_without is not None
    assert cand_with.final_score == cand_without.final_score
    assert cand_with.context_flags == [flag]
