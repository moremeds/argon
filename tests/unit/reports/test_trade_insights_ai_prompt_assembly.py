"""Provider-neutral prompt assembly contract.

After the prompt-machinery decoupling (Task 2 of the deepseek plan), every
provider — Codex, Claude, DeepSeek — must see the same `CONTRACT_PROMPT`
clause through the user-prompt path. These tests pin that invariant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from uw_scan.reports.trade_insights_ai import (
    CONTRACT_PROMPT,
    MARKET_INTELLIGENCE_PROMPT,  # noqa: F401  # import smoke for re-export
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


def test_contract_prompt_present_in_assembled_prompt() -> None:
    """CONTRACT_PROMPT (lifted from Claude-only `_JSON_ONLY_SYSTEM_PROMPT`)
    must appear in every assembled prompt so DeepSeek/Codex see the same
    contract Claude has been getting through `--append-system-prompt`."""
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    # Three load-bearing fragments from CONTRACT_PROMPT.
    assert 'directional_bias MUST be one of: "LONG_DELTA"' in assembled
    assert "MODE-STRUCTURE CONSISTENCY (HARD" in assembled
    assert "v5.3 LEGS REQUIREMENT (HARD)" in assembled


def test_contract_prompt_does_not_leak_claude_cli_or_structured_output_tool_hints() -> (
    None
):
    """CONTRACT_PROMPT must be provider-neutral. Two leaks to guard against:
    (a) the Claude CLI flag name `--json-schema` was rewritten to "JSON schema"
        so DeepSeek/Codex callers aren't confused by Anthropic CLI grammar;
    (b) the trailing "Use the StructuredOutput tool" Claude-mechanic sentence
        was dropped so non-Claude providers don't see misleading advice."""
    assert "--json-schema" not in CONTRACT_PROMPT
    assert "StructuredOutput tool" not in CONTRACT_PROMPT


def test_contract_prompt_exported_from_package_root() -> None:
    """Both `__init__.py` re-export and the module attribute must resolve to
    the same constant so existing imports stay stable."""
    from uw_scan.reports.trade_insights_ai import prompt_text

    assert CONTRACT_PROMPT is prompt_text.CONTRACT_PROMPT
    assert isinstance(CONTRACT_PROMPT, str)
    assert len(CONTRACT_PROMPT) > 500  # Substantial body, not a stub


def test_prompt_version_bumped_to_v6() -> None:
    """The trade-framework decision-stack contract ships as prompt v6.0."""
    assert PROMPT_VERSION == "trade-insights-ai-v6.0"


def test_framework_kb_and_directive_embedded_in_assembled_prompt() -> None:
    """The assembled SYSTEM prompt must embed the trade-framework knowledge
    base AND the framework decision-stack directive so the model produces the
    full conviction-ledger `framework` object (Task 3.3)."""
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
    assert "trade-insights-ai-v6.0" in assembled


def test_hard_rules_not_triplicated_after_dedupe() -> None:
    """After dedup, each load-bearing HARD-rule clause appears at most twice
    (once in MARKET_INTELLIGENCE_PROMPT, once in CONTRACT_PROMPT). Triplication
    means the integration-notes appendix still restates a rule that's now in
    CONTRACT_PROMPT — token waste, drift surface."""
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    for needle in [
        "MODE-STRUCTURE CONSISTENCY",
        "DELTA-MATCH",
        "DTE-band consistency",
        "Trigger-strike consistency",
        "Conditional-quote validity",
        "Anti-pin quality",
    ]:
        count = assembled.lower().count(needle.lower())
        assert count <= 2, (
            f"{needle!r} appears {count}x in assembled prompt; "
            "should appear at most twice (MARKET_INTELLIGENCE_PROMPT + CONTRACT_PROMPT)"
        )
