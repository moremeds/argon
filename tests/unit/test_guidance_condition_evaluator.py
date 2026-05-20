"""Unit tests for the AST-whitelist condition evaluator.

The evaluator is a security boundary. Tests cover:
1. Valid conditions evaluate correctly.
2. Every common eval-sandbox-escape pattern raises ValueError/SyntaxError.
"""

from __future__ import annotations

import pytest

from uw_scan.api.routers.regime_validation import _evaluate_condition

CTX = {
    "level": "LOW",
    "vix_vix3m_ratio": 0.92,
    "vrp": 5.2,
    "vix_zscore_30d": 1.1,
}


def test_simple_compare_true() -> None:
    assert _evaluate_condition("level == 'LOW'", CTX) is True


def test_chained_compare() -> None:
    assert _evaluate_condition("0.9 <= vix_vix3m_ratio < 1.0", CTX) is True


def test_and_or_not() -> None:
    assert (
        _evaluate_condition("level == 'LOW' and (vrp > 0 or vix_zscore_30d > 3)", CTX)
        is True
    )
    assert _evaluate_condition("not (level == 'HIGH')", CTX) is True


def test_is_none_for_missing_field() -> None:
    """is None / is not None must work for the missing-VIX3M guard rules."""
    ctx_missing = {**CTX, "vix_vix3m_ratio": None}
    assert _evaluate_condition("vix_vix3m_ratio is None", ctx_missing) is True
    assert _evaluate_condition("vix_vix3m_ratio is not None", CTX) is True


def test_subscript_attribute_call_all_rejected() -> None:
    # Each of these is a known eval-sandbox-escape vector.
    for expr in (
        "().__class__.__bases__[0].__subclasses__()",
        "level.upper()",
        "[1, 2, 3][0]",
        "lambda: 1",
        "__import__('os')",
    ):
        with pytest.raises((ValueError, SyntaxError)):
            _evaluate_condition(expr, CTX)


def test_unknown_name_rejected() -> None:
    with pytest.raises(ValueError, match="unknown name"):
        _evaluate_condition("foo == 1", CTX)


def test_arithmetic_op_rejected() -> None:
    # We intentionally don't allow + - * / — comparisons only.
    with pytest.raises(ValueError):
        _evaluate_condition("vrp + 1 > 0", CTX)


def test_type_mismatched_compare_raises_typeerror() -> None:
    # A well-formed AST (`level < 1`) but the op blows up at runtime
    # because "LOW" < 1 isn't defined. The endpoint catches it and logs.
    with pytest.raises(TypeError):
        _evaluate_condition("level < 1", CTX)
