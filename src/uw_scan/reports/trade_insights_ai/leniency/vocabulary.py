"""Vocabulary bridges for Claude Trade Insights AI leniency."""

from __future__ import annotations

from typing import Any

from uw_scan.reports.trade_insights_ai import DIRECTIONAL_BIAS_VALUES
from uw_scan.reports.trade_insights_ai.leniency.normalization import (
    _STANCE_SEPARATOR_RE,
)

# v5 directional vocabulary — smart coercion with alias maps.
def _derive_bias_from_stance(stance: str) -> str:
    """Conservative directional_bias inference from a resolved stance.

    Bullish/bearish stances map cleanly; everything else (neutral, mixed,
    wait — all of which mean 'no clean direction at this horizon') maps to
    WAIT so the panel does not surface a false directional call when the
    model failed to emit one explicitly."""
    if stance == "bullish":
        return "LONG_DELTA"
    if stance == "bearish":
        return "SHORT_DELTA"
    return "WAIT"


# Alias map for directional_bias. Keys are the *normalized* form (lower-case
# + separators collapsed to "_"); values are the canonical enum constant.
# This catches the common Claude vocabulary drifts: "long delta", "long-delta",
# "longdelta", "long" (bare), "bullish_continuation" (path label leaked), etc.
_DIRECTIONAL_BIAS_ALIASES = {
    # Long-delta synonyms
    "long_delta": "LONG_DELTA",
    "longdelta": "LONG_DELTA",
    "long": "LONG_DELTA",
    "bullish": "LONG_DELTA",
    "bull": "LONG_DELTA",
    "bullish_continuation": "LONG_DELTA",
    # Short-delta synonyms
    "short_delta": "SHORT_DELTA",
    "shortdelta": "SHORT_DELTA",
    "short": "SHORT_DELTA",
    "bearish": "SHORT_DELTA",
    "bear": "SHORT_DELTA",
    "bearish_rejection": "SHORT_DELTA",
    "downside_break": "SHORT_DELTA",
    # Wait synonyms
    "wait": "WAIT",
    "no_trade": "WAIT",
    "notrade": "WAIT",
    "no_entry": "WAIT",
    "stand_aside": "WAIT",
    "standaside": "WAIT",
    "pinned_no_directional_entry": "WAIT",
    "data_insufficient": "WAIT",
    "neutral": "WAIT",
    "mixed": "WAIT",
}


def _resolve_directional_bias(raw: Any, stance: str) -> str:
    """Pick directional_bias from the explicit field when present, applying
    a generous alias map; fall back to stance-derivation otherwise.

    Order of precedence:
      1. Explicit directional_bias field matches the canonical enum directly.
      2. Explicit field normalizes (case/separator insensitive) to a known alias.
      3. Stance-derivation as last resort.
    """
    if isinstance(raw, str):
        compact = _STANCE_SEPARATOR_RE.sub("_", raw.strip().lower()).strip("_")
        if not compact:
            return _derive_bias_from_stance(stance)
        # Try the canonical form first (UPPER + _ separators).
        candidate = compact.upper()
        if candidate in DIRECTIONAL_BIAS_VALUES:
            return candidate
        # Alias lookup uses the lower-cased normalized form.
        aliased = _DIRECTIONAL_BIAS_ALIASES.get(compact)
        if aliased is not None:
            return aliased
    return _derive_bias_from_stance(stance)


# Underlying-path aliases. Real-world Claude/Codex drift includes "bullish"
# (compressed from bullish_continuation) and "range" (compressed from
# pinned_no_directional_entry).
_UNDERLYING_PATH_ALIASES = {
    "bullish": "bullish_continuation",
    "bullish_trend": "bullish_continuation",
    "bullish_breakout": "bullish_continuation",
    "bearish": "bearish_rejection",
    "bearish_fade": "bearish_rejection",
    "bearish_reject": "bearish_rejection",
    "breakdown": "downside_break",
    "downside": "downside_break",
    "range": "pinned_no_directional_entry",
    "range_bound": "pinned_no_directional_entry",  # post-separator-collapse form
    "rangebound": "pinned_no_directional_entry",  # compact form
    "pinned": "pinned_no_directional_entry",
    "pin": "pinned_no_directional_entry",
    "neutral": "pinned_no_directional_entry",
    "insufficient_data": "data_insufficient",
    "no_data": "data_insufficient",
    "data_missing": "data_insufficient",
}


# Entry-state aliases.
_ENTRY_STATE_ALIASES = {
    "active": "ACTIVE",
    "in_trade": "ACTIVE",
    "live": "ACTIVE",
    "conditional": "CONDITIONAL",
    "pending": "CONDITIONAL",
    "watchlist": "CONDITIONAL",
    "watch": "CONDITIONAL",
    "wait": "CONDITIONAL",
    "no_entry": "NO_ENTRY",
    "noentry": "NO_ENTRY",
    "stand_aside": "NO_ENTRY",
    "skip": "NO_ENTRY",
    "reject": "NO_ENTRY",
}


# Trade-intent aliases.
_TRADE_INTENT_ALIASES = {
    "directional_swing": "directional_swing",
    "directional": "directional_swing",
    "swing": "directional_swing",
    "range_income": "range_income",
    "range": "range_income",
    "income": "range_income",
    "vol_seller": "range_income",
    "premium_seller": "range_income",
}


# DTE-band aliases. v5.1: 3-band (momentum | standard | trend). Models
# that emitted "standard" under v5 (which forced binary) get a correct
# round-trip now. Truly ambiguous values (middle/medium) collapse to
# standard so the validator can then sanity-check against the actual
# entry DTE (M4).
_DTE_BAND_ALIASES = {
    "momentum": "momentum",
    "short": "momentum",
    "short_dte": "momentum",
    "front": "momentum",
    "near": "momentum",
    "standard": "standard",
    "middle": "standard",
    "mid": "standard",
    "medium": "standard",
    "trend": "trend",
    "long": "trend",
    "long_dte": "trend",
    "back": "trend",
    "far": "trend",
}

# v5.2: thesis_archetype aliases. Maps common drift back to canonical Literal.
_THESIS_ARCHETYPE_ALIASES = {
    "resistance_rejection": "resistance_rejection",
    "rejection": "resistance_rejection",
    "wall_rejection": "resistance_rejection",
    "fade_from_above": "resistance_rejection",
    "support_breakdown": "support_breakdown",
    "breakdown": "support_breakdown",
    "support_break": "support_breakdown",
    "downside_break": "support_breakdown",
    "breakout_continuation": "breakout_continuation",
    "breakout": "breakout_continuation",
    "continuation": "breakout_continuation",
    "bullish_continuation": "breakout_continuation",
    "pin_no_trade": "pin_no_trade",
    "pin": "pin_no_trade",
    "no_trade": "pin_no_trade",
    "data_insufficient": "data_insufficient",
    "insufficient": "data_insufficient",
    "insufficient_data": "data_insufficient",
}

# v5.2: anti_pin direction aliases.
_ANTI_PIN_DIRECTION_ALIASES = {
    "upside": "upside",
    "up": "upside",
    "bullish": "upside",
    "long": "upside",
    "downside": "downside",
    "down": "downside",
    "bearish": "downside",
    "short": "downside",
    "none": "none",
    "n/a": "none",
    "n_a": "none",
}

# v5.1: long_leg_role / short_leg_role coercion. Models drift on synonyms
# ("breakout" vs "trigger_level", "next_wall" vs "next_call_wall"). Map
# common variants back to the canonical Literal values.
_LONG_LEG_ROLE_ALIASES = {
    "trigger_level": "trigger_level",
    "trigger": "trigger_level",
    "breakout_level": "trigger_level",
    "wall": "trigger_level",
    "support_reclaim": "support_reclaim",
    "support": "support_reclaim",
    "reclaim": "support_reclaim",
    "atm_delta_anchor": "atm_delta_anchor",
    "atm": "atm_delta_anchor",
    "delta_anchor": "atm_delta_anchor",
    "deep_itm_proxy": "deep_itm_proxy",
    "deep_itm": "deep_itm_proxy",
    "itm_proxy": "deep_itm_proxy",
    "n_a": "n/a",
    "na": "n/a",
    "none": "n/a",
}
_SHORT_LEG_ROLE_ALIASES = {
    "target_level": "target_level",
    "target": "target_level",
    "next_call_wall": "next_call_wall",
    "call_wall": "next_call_wall",
    "next_wall": "next_call_wall",
    "second_magnet": "second_magnet",
    "magnet": "second_magnet",
    "next_put_wall": "next_put_wall",
    "put_wall": "next_put_wall",
    "next_downside_target": "next_downside_target",
    "downside_target": "next_downside_target",
    "n_a": "n/a",
    "na": "n/a",
    "none": "n/a",
}


def _resolve_with_alias(
    raw: Any,
    canonical: tuple[str, ...],
    alias_map: dict[str, str],
    default: str,
) -> str:
    """Resolve an enum value with a separator-normalized alias map.

    1. Direct match against the canonical enum (case-preserving).
    2. Alias lookup using lower-case + separator-collapsed form.
    3. Fall back to the supplied default.
    """
    if not isinstance(raw, str):
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    # Case-insensitive direct match (preserves canonical case).
    for value in canonical:
        if stripped.lower() == value.lower():
            return value
    compact = _STANCE_SEPARATOR_RE.sub("_", stripped.lower()).strip("_")
    aliased = alias_map.get(compact)
    if aliased is not None:
        return aliased
    return default


def _resolve_enum(raw: Any, allowed: tuple[str, ...], default: str) -> str:
    """Generic enum resolver — case-insensitive match against allowed.

    Retained for callsites that don't need alias coercion; for v5 directional
    vocab use `_resolve_with_alias` against the appropriate alias map."""
    if isinstance(raw, str):
        candidate = raw.strip()
        for value in allowed:
            if candidate.lower() == value.lower():
                return value
    return default

def _derive_thesis_archetype_from_path(underlying_path: str) -> str:
    """v5.2: map underlying_path → thesis_archetype for default backfill."""
    mapping = {
        "bullish_continuation": "breakout_continuation",
        "bearish_rejection": "resistance_rejection",
        "downside_break": "support_breakdown",
        "pinned_no_directional_entry": "pin_no_trade",
        "data_insufficient": "data_insufficient",
    }
    return mapping.get(underlying_path, "data_insufficient")
