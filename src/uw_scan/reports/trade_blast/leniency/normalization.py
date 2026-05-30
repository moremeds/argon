"""Basic normalization helpers for Claude Trade Insights AI leniency."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from uw_scan.reports.trade_blast import FINAL_RATING_VALUES

logger = logging.getLogger(__name__)

_HEADLINE_VALID_STANCES = ("bullish", "bearish", "neutral", "mixed", "wait")
_HEADLINE_STANCE_FALLBACK = "mixed"
# Vocabulary bridge: the user prompt's markdown template asks for "range"
# or "no_trade", but the model Literal is the 5-value set above. Codex
# translates these automatically; Claude does not. Keys are normalized
# (lower-case, separators collapsed to "_") before lookup so "range bound"
# and "range-bound" both hit "rangebound" -> "neutral".
_HEADLINE_STANCE_ALIASES = {
    "range": "neutral",
    "rangebound": "neutral",
    "no_trade": "wait",
    "notrade": "wait",
    "none": "wait",
}
_CONVICTION_FALLBACK = "F"
_VRP_VALID_SIGNALS = ("long_vol", "short_vol", "neutral")
_VRP_SIGNAL_FALLBACK = "neutral"
_PARTIAL_OUTPUT_NOTE = (
    "Provider produced partial output that did not adhere to the strict schema; "
    "missing required fields were synthesized."
)
_STANCE_SEPARATOR_RE = re.compile(r"[\s\-_]+")


def _str_or(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _int_or(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return default
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            logger.debug("_int_or fell back to default for %r: %s", value, repr(exc))
            return default
    return default


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            logger.debug("_opt_int returned None for %r: %s", value, repr(exc))
            return None
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_list(value: Any) -> list[str]:
    return [v for v in (_str_or(item, "") for item in _list_or_empty(value)) if v]


def _normalize_stance(value: Any) -> str | None:
    """Lower-case + collapse separators so "no trade", "no-trade", "no_trade"
    all hit "no_trade"; "range bound", "range-bound", "rangebound" all hit
    "rangebound". Returns None for non-strings."""
    if not isinstance(value, str):
        return None
    return _STANCE_SEPARATOR_RE.sub("_", value.strip().lower()).strip("_")


def _resolve_stance(raw: Any) -> str:
    """Apply alias map + Literal fallback. Returns a value in
    _HEADLINE_VALID_STANCES; falls back to _HEADLINE_STANCE_FALLBACK."""
    normalized = _normalize_stance(raw)
    if normalized is None:
        return _HEADLINE_STANCE_FALLBACK
    # Stripped separators: alias keys also normalized via removing "_"/"-"
    compact = normalized.replace("_", "")
    candidate = _HEADLINE_STANCE_ALIASES.get(compact, compact)
    if candidate in _HEADLINE_VALID_STANCES:
        return candidate
    # Last-chance: maybe normalized matches a valid stance directly
    if normalized in _HEADLINE_VALID_STANCES:
        return normalized
    return _HEADLINE_STANCE_FALLBACK


def _resolve_conviction(raw: Any) -> str:
    """Normalize case/whitespace and validate against FINAL_RATING_VALUES."""
    if not isinstance(raw, str):
        return _CONVICTION_FALLBACK
    candidate = raw.strip().upper()
    return candidate if candidate in FINAL_RATING_VALUES else _CONVICTION_FALLBACK
