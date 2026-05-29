"""Schema auto-inclusion guard for the additive framework{} block (v6.0)."""

from __future__ import annotations


def test_output_schema_includes_framework():
    from uw_scan.reports.trade_insights_ai import trade_insights_ai_output_schema

    schema = trade_insights_ai_output_schema(strict=True, strip_lookaround_regex=True)
    assert "framework" in schema["properties"]
    assert "TradeFramework" in schema["$defs"]
    # strict mode forces every top-level property required; framework allows null via anyOf
    assert "framework" in schema["required"]
