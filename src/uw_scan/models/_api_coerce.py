"""Shared coercion helpers for the API contract models."""

from __future__ import annotations


def _to_float(v):
    """Pydantic v2 before-validator: coerce string-valued numerics from UW."""
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: coercion failures fold to None silently
        return None
