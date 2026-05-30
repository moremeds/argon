"""Regression guard on the assembled Trade Insights AI prompt size.

The v6.0 prompt embeds the ~192 KB trade-framework knowledge base on top of
the existing ~350 KB-class system prompt the runners already send. This test
documents the headroom: the assembled prompt for a minimal payload must stay
comfortably under a generous 600 KB ceiling. If a future KB or directive edit
blows past it, this guard fails loudly so the size is a conscious decision.

Run with ``-s`` to see the measured byte size printed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from uw_scan.reports.trade_insights_ai import (
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
)

# Generous ceiling: the assembled minimal prompt is ~210 KB today (KB ~192 KB +
# contract/market-intelligence/directive). 600 KB leaves room for a fully
# populated per-ticker payload without papering over a runaway KB.
PROMPT_BYTE_CEILING = 600_000


def _minimal_analysis_input() -> dict:
    return {
        "ticker": "TEST",
        "run_id": "run-xyz",
        "trade_insights_input_hash": "hash-abc",
        "tabs": {
            "market_structure": {"market_structure": {"spot": "100.0"}},
            "volatility": {},
            "flow": {},
            "positioning": {},
        },
        "underlying_price": "100.0",
        "candidate_structures": [],
    }


def test_assembled_prompt_under_byte_budget() -> None:
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    measured = len(assembled.encode("utf-8"))
    # Visible under `pytest -s` — documents the headroom on every run.
    print(f"\nassembled prompt size = {measured} bytes (ceiling {PROMPT_BYTE_CEILING})")
    assert measured < PROMPT_BYTE_CEILING, (
        f"assembled prompt is {measured} bytes, over the "
        f"{PROMPT_BYTE_CEILING}-byte budget — re-check KB/directive growth"
    )
