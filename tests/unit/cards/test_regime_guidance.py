"""cards.regime_guidance — the guidance.md parser and the condition evaluator
at their own (non-router) home. The router-path coverage stays in
tests/unit/test_guidance_condition_evaluator.py."""

from __future__ import annotations

import pytest

from uw_scan.cards.regime_guidance import evaluate_condition, parse_guidance_md


def test_evaluate_condition_accepts_compare_and_boolean_rejects_call_and_attribute() -> (
    None
):
    ctx = {"level": "LOW", "vix_vix3m_ratio": 0.9, "vrp": None}
    assert evaluate_condition("level == 'LOW' and vix_vix3m_ratio < 0.95", ctx) is True
    assert evaluate_condition("not (level == 'HIGH') or vrp is None", ctx) is True
    assert (
        evaluate_condition("level == 'HIGH' or vix_vix3m_ratio >= 0.95", ctx) is False
    )
    for expr in ("__import__('os')", "level.upper() == 'LOW'"):
        with pytest.raises(ValueError, match="forbidden node"):
            evaluate_condition(expr, ctx)


def test_parse_guidance_md_reads_frontmatter_and_body(tmp_path) -> None:
    md = tmp_path / "guidance.md"
    md.write_text(
        "---\n"
        "state: low_contango\n"
        "condition: \"level == 'LOW' and vix_vix3m_ratio < 0.95\"\n"
        "posture: premium_selling\n"
        "---\n"
        "Sell premium.\n"
        "---\n"
        "state: no_posture\n"
        "condition: \"level == 'HIGH'\"\n"
        "---\n"
        "Skipped: posture is missing.\n"
        "---\n"
        "state: low_neutral\n"
        "condition: \"level == 'LOW'\"\n"
        "posture: neutral\n"
        "---\n"
        "Stay neutral.\n"
    )
    assert parse_guidance_md(md) == [
        {
            "state": "low_contango",
            "condition": "level == 'LOW' and vix_vix3m_ratio < 0.95",
            "posture": "premium_selling",
            "body_md": "Sell premium.",
        },
        {
            "state": "low_neutral",
            "condition": "level == 'LOW'",
            "posture": "neutral",
            "body_md": "Stay neutral.",
        },
    ]
    assert parse_guidance_md(tmp_path / "missing.md") == []
