"""Strike, trigger, leg, and anti-pin coercion helpers."""

from __future__ import annotations

import logging
import math
from typing import Any

from uw_scan.reports._shared_validation.leniency.normalization import (
    _dict_or_empty,
    _list_or_empty,
    _str_list,
    _str_or,
)
from uw_scan.reports._shared_validation.leniency.vocabulary import (
    _ANTI_PIN_DIRECTION_ALIASES,
    _LONG_LEG_ROLE_ALIASES,
    _SHORT_LEG_ROLE_ALIASES,
    _resolve_with_alias,
)

logger = logging.getLogger(__name__)

def _market_structure_levels(
    deterministic_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pull market_structure_levels for v5.1 strike_role default backfill."""
    if not isinstance(deterministic_payload, dict):
        return {}
    tabs = deterministic_payload.get("tabs") or {}
    if not isinstance(tabs, dict):
        return {}
    ms = tabs.get("market_structure") or {}
    if not isinstance(ms, dict):
        return {}
    levels = ms.get("market_structure_levels") or {}
    return levels if isinstance(levels, dict) else {}


def _latest_completed_close(
    deterministic_payload: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """v5.2: return (close, market_date) for the latest COMPLETED daily
    close in tabs.market_structure.stock_history. Rows with spot=None or
    market_date=None are skipped (today's incomplete bar)."""
    if not isinstance(deterministic_payload, dict):
        return (None, None)
    tabs = deterministic_payload.get("tabs") or {}
    if not isinstance(tabs, dict):
        return (None, None)
    ms = tabs.get("market_structure") or {}
    if not isinstance(ms, dict):
        return (None, None)
    sh = ms.get("stock_history") or {}
    if not isinstance(sh, dict):
        return (None, None)
    rows = sh.get("rows") or []
    if not isinstance(rows, list):
        return (None, None)
    completed = [
        r
        for r in rows
        if isinstance(r, dict)
        and r.get("spot") is not None
        and r.get("market_date") is not None
    ]
    if not completed:
        return (None, None)
    completed.sort(key=lambda r: r.get("market_date") or "")
    latest = completed[-1]
    return (str(latest.get("spot")), str(latest.get("market_date")))


def _coerce_strike_role(
    raw_strike_role: Any,
    *,
    directional_bias: str,
    levels: dict[str, Any],
) -> dict[str, Any]:
    """Coerce strike_role + backfill trigger/target/invalid levels.

    Defaults are derived from market_structure_levels when the model
    omits them: LONG_DELTA uses call_wall as trigger and second_magnet/
    max_magnet as target. SHORT_DELTA uses put_wall as trigger and
    max_accel / next put OI as target. WAIT leaves levels blank.
    """
    raw = _dict_or_empty(raw_strike_role)
    long_role = _resolve_with_alias(
        raw.get("long_leg_role"),
        (
            "trigger_level",
            "support_reclaim",
            "atm_delta_anchor",
            "deep_itm_proxy",
            "n/a",
        ),
        _LONG_LEG_ROLE_ALIASES,
        "n/a",
    )
    short_role = _resolve_with_alias(
        raw.get("short_leg_role"),
        (
            "target_level",
            "next_call_wall",
            "second_magnet",
            "next_put_wall",
            "next_downside_target",
            "n/a",
        ),
        _SHORT_LEG_ROLE_ALIASES,
        "n/a",
    )
    # v5.2: pass values through as-is (str | dict | numeric | None). The
    # Pydantic field_validator extracts .strike from dict objects so the
    # Claude failure mode (whole strike-curve row pasted) is caught at the
    # schema layer. Keep _str_or away from these levels — it stringifies
    # dicts into "{'strike': '215', ...}" which breaks the field_validator.
    trigger = raw.get("trigger_level")
    target = raw.get("target_level")
    invalid = raw.get("invalid_level")

    def _level(key: str) -> Any:
        return levels.get(key) if isinstance(levels, dict) else None

    def _is_blank(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str) and not v.strip():
            return True
        return False

    # Default-fill when model omitted these — pulled from market structure.
    if directional_bias == "LONG_DELTA":
        if _is_blank(trigger):
            trigger = _level("call_wall")
        if _is_blank(target):
            target = _level("second_magnet") or _level("max_magnet")
        if _is_blank(invalid):
            invalid = _level("gex_flip") or _level("put_wall")
    elif directional_bias == "SHORT_DELTA":
        if _is_blank(trigger):
            trigger = _level("put_wall") or _level("gex_flip")
        if _is_blank(target):
            target = _level("max_accel") or _level("max_magnet")
        if _is_blank(invalid):
            invalid = _level("call_wall")
    # WAIT leaves blank levels intact.

    return {
        "long_leg_role": long_role,
        "short_leg_role": short_role,
        # Pydantic's _coerce_strike_level will normalize these:
        # numeric / numeric-string → Decimal; dict-with-strike-key → Decimal;
        # blank/None → None; everything else → ValueError.
        "trigger_level": trigger,
        "target_level": target,
        "invalid_level": invalid,
        "trigger_source_path": _str_or(raw.get("trigger_source_path"), ""),
        "target_source_path": _str_or(raw.get("target_source_path"), ""),
        "invalid_source_path": _str_or(raw.get("invalid_source_path"), ""),
    }


def _coerce_trigger_evidence(
    raw_te: Any,
    *,
    trigger_level_from_strike_role: Any,
    deterministic_payload: dict[str, Any] | None,
    watch_trigger: str,
) -> dict[str, Any]:
    """v5.2: build the trigger_evidence block.

    Strategy:
      1. If the model emitted trigger_evidence with trigger_fired/close/
         date populated, preserve it.
      2. Otherwise read the latest completed daily close from
         tabs.market_structure.stock_history and compute trigger_fired
         deterministically against trigger_level.
      3. Infer trigger_type from watch_trigger prose ("daily close above/
         below X" → daily_close; "2-session hold" → two_session_hold).
    """
    raw = _dict_or_empty(raw_te)
    # Latest completed close from payload.
    latest_close, latest_date = _latest_completed_close(deterministic_payload)

    # Pull or default fields.
    trigger_level = raw.get("trigger_level")
    if trigger_level is None:
        trigger_level = trigger_level_from_strike_role

    evidence_close = raw.get("evidence_close")
    if evidence_close is None:
        evidence_close = latest_close

    evidence_close_date = raw.get("evidence_close_date") or latest_date

    # Trigger type inference from watch_trigger prose.
    wt = (watch_trigger or "").lower()
    if "2-session" in wt or "two-session" in wt or "two session" in wt:
        trigger_type = "two_session_hold"
    elif "daily close" in wt or "close above" in wt or "close below" in wt:
        trigger_type = "daily_close"
    else:
        trigger_type = str(raw.get("trigger_type") or "unknown")

    # Compute trigger_fired only when both close and trigger_level are
    # numeric — the validator will read this field, not the prose.
    trigger_fired = bool(raw.get("trigger_fired", False))
    try:
        from decimal import Decimal

        if evidence_close is not None and trigger_level is not None:
            ec = Decimal(str(evidence_close).strip().lstrip("$"))
            tl = (
                trigger_level
                if isinstance(trigger_level, Decimal)
                else Decimal(str(trigger_level).strip().lstrip("$"))
            )
            # Direction inference from watch_trigger prose.
            if "above" in wt:
                trigger_fired = ec > tl
            elif "below" in wt:
                trigger_fired = ec < tl
            # else: leave whatever the model emitted (could be 2-session hold).
    except Exception as exc:
        _ = repr(exc)  # CI Guardrail 2

    source_path = _str_or(
        raw.get("source_path"),
        "tabs.market_structure.stock_history.rows" if latest_close else "",
    )

    return {
        "trigger_fired": trigger_fired,
        "trigger_type": trigger_type,
        "trigger_level": trigger_level,
        "evidence_close": evidence_close,
        "evidence_close_date": evidence_close_date,
        "source_path": source_path,
    }


def _coerce_decimal_str(value: Any) -> str | None:
    """v5.3: best-effort numeric-string coercion for Decimal fields.

    Handles ints, floats, Decimals, "$215", "215.00", and the dict-form
    Claude failure mode (`{'strike': '215', 'net_gex': ...}`). Returns
    None for empty / unparseable input — Pydantic will treat None as
    "model declined to populate," which is legal for optional Decimal
    fields on TriggerComponent.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("strike", "price", "level", "value"):
            if key in value:
                return _coerce_decimal_str(value[key])
        return None
    if isinstance(value, str):
        cleaned = value.strip().lstrip("$")
        if not cleaned:
            return None
        try:
            from decimal import Decimal, InvalidOperation

            Decimal(cleaned)
        except (InvalidOperation, ValueError) as exc:
            logger.debug("decimal coerce failed for %r: %s", cleaned, repr(exc))
            return None
        return cleaned
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return str(value)
    return None


def _coerce_trigger_component(
    raw: Any,
    *,
    fallback_level: Any = None,
    fallback_meaning: str = "",
    fallback_fired: bool = False,
    fallback_evidence_close: Any = None,
    fallback_evidence_date: Any = None,
    fallback_source_path: str = "",
) -> dict[str, Any]:
    """v5.3: coerce one TradeInsightAiTriggerComponent block.

    Used for thesis_trigger, entry_trigger, and invalidation. Each
    component carries its own {level, meaning, fired, evidence_close,
    evidence_date, source_path}. When the model omits the field, the
    caller supplies fallbacks typically derived from the v5.2
    trigger_evidence block or strike_role.invalid_level — this lets
    a v5.2-shape outcome still produce a usable v5.3 trigger surface
    so the UI does not render blank cells for backwards-compatible
    historical inputs.
    """
    raw_dict = _dict_or_empty(raw)

    raw_level = raw_dict.get("level")
    if raw_level is None:
        raw_level = fallback_level
    level = _coerce_decimal_str(raw_level)

    raw_ec = raw_dict.get("evidence_close")
    if raw_ec is None:
        raw_ec = fallback_evidence_close
    evidence_close = _coerce_decimal_str(raw_ec)

    evidence_date = raw_dict.get("evidence_date") or fallback_evidence_date
    if evidence_date is not None and not isinstance(evidence_date, str):
        evidence_date = str(evidence_date)

    fired_raw = raw_dict.get("fired")
    fired_bool = fired_raw if isinstance(fired_raw, bool) else bool(fallback_fired)

    meaning = _str_or(raw_dict.get("meaning"), fallback_meaning)
    source_path = _str_or(raw_dict.get("source_path"), fallback_source_path)

    return {
        "level": level,
        "meaning": meaning,
        "fired": fired_bool,
        "evidence_close": evidence_close,
        "evidence_date": evidence_date,
        "source_path": source_path,
    }


_OPTION_TYPE_ALIASES = {
    "call": "call",
    "c": "call",
    "calls": "call",
    "put": "put",
    "p": "put",
    "puts": "put",
}
_OPTION_SIDE_ALIASES = {
    "long": "long",
    "l": "long",
    "buy": "long",
    "bought": "long",
    "short": "short",
    "s": "short",
    "sell": "short",
    "sold": "short",
}


def _normalize_option_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _OPTION_TYPE_ALIASES.get(value.strip().lower())


def _normalize_option_side(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _OPTION_SIDE_ALIASES.get(value.strip().lower())


def _normalize_expiry(value: Any) -> str | None:
    """v5.3: coerce expiry into an ISO date string.

    Accepts YYYY-MM-DD, YYYY/MM/DD (slashes → dashes), and date/datetime
    objects. Pydantic enforces the final ISO date format downstream.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().replace("/", "-")
        return s or None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso().split("T")[0]
    return None


def _coerce_option_leg(raw: Any) -> dict[str, Any] | None:
    """v5.3: coerce one option leg. Returns None for unparseable entries.

    The legs-strategy-match validator (M4) checks structure-specific
    geometry against the surviving entries; here we only normalize
    shape and drop entries that lack a parseable strike or option type.
    """
    if not isinstance(raw, dict):
        return None
    option_type = _normalize_option_type(raw.get("option_type") or raw.get("type"))
    side = _normalize_option_side(raw.get("side"))
    strike = _coerce_decimal_str(raw.get("strike"))
    expiry = _normalize_expiry(
        raw.get("expiry") or raw.get("expiration") or raw.get("expiry_date")
    )
    if not option_type or not side or strike is None or not expiry:
        return None
    return {
        "option_type": option_type,
        "side": side,
        "strike": strike,
        "expiry": expiry,
    }


def _coerce_option_legs(raw: Any) -> list[dict[str, Any]]:
    """v5.3: coerce legs[] array. Silent drop of unparseable entries —
    the M4 legs-strategy-match validator enforces structure semantics
    against what survives."""
    return [
        leg
        for leg in (_coerce_option_leg(r) for r in _list_or_empty(raw))
        if leg is not None
    ]


def _coerce_anti_pin(raw_ap: Any) -> dict[str, Any]:
    """v5.2: coerce anti_pin block.

    Default invoked=false so the M4 conviction-cap rule does NOT apply
    when the model omits anti_pin — structural-break / trend-continuation
    theses can legitimately have a low anti-pin score without being
    penalized for it. The model must explicitly set invoked=true when
    anti-pin is the trade thesis."""
    raw = _dict_or_empty(raw_ap)
    direction = _resolve_with_alias(
        raw.get("direction"),
        ("upside", "downside", "none"),
        _ANTI_PIN_DIRECTION_ALIASES,
        "none",
    )
    score_raw = raw.get("score")
    try:
        score = int(score_raw) if score_raw is not None else 0
    except (ValueError, TypeError) as exc:
        _ = repr(exc)
        score = 0
    score = max(0, min(score, 4))  # clamp to [0, 4]
    return {
        "invoked": bool(raw.get("invoked", False)),
        "direction": direction,
        "score": score,
        "max_score": 4,
        "conditions_met": _str_list(raw.get("conditions_met")),
        "conviction_cap_applied": bool(raw.get("conviction_cap_applied", False)),
        "cap_reason": _str_or(raw.get("cap_reason"), ""),
    }


def _coerce_target_feasibility(raw_tf: Any) -> dict[str, Any]:
    """v5.2: coerce target_feasibility block.

    Default feasibility='missing' so the absence of expected_move data
    in the payload does not block the trade — it's just unsurfaced."""
    raw = _dict_or_empty(raw_tf)
    feasibility = raw.get("feasibility")
    if feasibility not in (
        "inside_expected_move",
        "outside_expected_move",
        "missing",
    ):
        feasibility = "missing"
    return {
        "distance_to_target_pct": raw.get("distance_to_target_pct"),
        "expected_move_available": bool(raw.get("expected_move_available", False)),
        "expected_move_source_path": _str_or(raw.get("expected_move_source_path"), ""),
        "feasibility": feasibility,
    }

