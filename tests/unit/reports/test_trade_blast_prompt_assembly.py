"""Trade-skills KB + framework directive embedding in the BLAST prompt.

The trade_blast lane (prompt ``trade-blast-v1``) bakes the trade-skills
knowledge base and the framework decision-stack directive into the assembled
prompt. The production v5.3 card (``uw_scan.reports.trade_insights_ai``)
deliberately does NOT carry this material — that lane is tested in
``test_trade_insights_ai_prompt_assembly.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from uw_scan.reports.trade_blast import (
    PROMPT_VERSION,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
)


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


def test_prompt_version_is_blast_v1() -> None:
    """The trade-framework decision-stack contract ships as prompt trade-blast-v1."""
    assert PROMPT_VERSION == "trade-blast-v1"


def test_framework_kb_and_directive_embedded_in_assembled_prompt() -> None:
    """The assembled blast prompt must embed the trade-framework knowledge
    base AND the framework decision-stack directive so the model produces the
    full conviction-ledger ``framework`` object."""
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    # Embedded KB header.
    assert "TRADE FRAMEWORK KNOWLEDGE" in assembled
    # Framework decision-stack directive load-bearing fragments.
    assert "best_setup" in assembled
    assert "framework" in assembled
    # Version stamp flows into the assembled prompt.
    assert "trade-blast-v1" in assembled
