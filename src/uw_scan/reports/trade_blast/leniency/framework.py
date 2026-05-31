"""Lenient coercion for the additive framework{} block (v6.0).

Claude emits free-form JSON; the strict Pydantic contract for the framework
requires exactly 8 conviction factors and a defined-risk flag on every
candidate. This module collapses cosmetic drift BEFORE
TradeInsightAiOutcome.model_validate runs (which is where min_length=8 fires),
so a structurally-sound-but-cosmetically-loose Claude framework still parses
and then faces the same semantic validator (_check_framework_rules) as Codex.

What it does NOT do: invent data. Missing canonical factors are padded as
`na` (never `yes`), and an absent `defined_risk` defaults to **False** so the
validator REJECTS a naked candidate rather than silently passing it (fail-safe).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from uw_scan.reports._shared_validation.leniency.normalization import (
    _dict_or_empty,
    _int_or,
    _list_or_empty,
    _str_or,
)

logger = logging.getLogger(__name__)

# The 8 canonical bull-conviction factors, verbatim from the embedded KB
# (references/strategies.md / pitfall 24). Order is contract-significant: the
# prompt asks the model to emit them in this order, the UI renders N/8 against
# this fixed denominator, and factors 1 & 5 are structurally `na` under
# UW+massive scope (channel checks / whisper data are out of scope).
CANONICAL_CONVICTION_FACTORS: tuple[str, ...] = (
    "3+ independent channel checks aligned bullish",
    "Sector / thematic narrative actively re-rating",
    "Stock down >20% from recent high (de-risked setup)",
    "Past 4 quarters: >=3 positive earnings reactions",
    "NEW information likely to be disclosed (new customer tier/product/guide raise/M&A)",
    "Net options flow back-month bullish (call-premium dominance, 5-day rolling)",
    "Short interest >10% (squeeze potential)",
    "Implied move materially below recent realized average",
)

_VALID_FACTOR_STATUS = {"yes", "no", "na"}

# --- Alias maps for framework enum coercion ---
# Claude (and occasionally DeepSeek) emits free-form strings where the contract
# expects a narrow Literal.  These maps collapse cosmetic drift BEFORE
# model_validate so the Pydantic Literal check passes.

_POSITION_TYPE_ALIASES: dict[str, str] = {
    "directional_swing": "swing",
    "swing_trade": "swing",
    "swing trade": "swing",
    "leaps_position": "leaps",
    "stand-aside": "stand_aside",
    "no_trade": "stand_aside",
}

_DIRECTION_VERDICT_ALIASES: dict[str, str] = {
    "bullish": "bull",
    "bearish": "bear",
    "long": "bull",
    "short": "bear",
    "flat": "neutral",
}

_VEGA_REGIME_ALIASES: dict[str, str] = {
    "event": "event_iv",
    "demand": "demand_iv",
    "low": "low_iv",
    "high_iv": "event_iv",
    "elevated": "event_iv",
    "depressed": "low_iv",
}

_GAMMA_REGIME_ALIASES: dict[str, str] = {
    "short_gamma": "short",
    "long_gamma": "long",
    "negative": "short",
    "positive": "long",
}

_STRUCTURE_FAMILY_ALIASES: dict[str, str] = {
    "directional": "directional_defined_risk",
    "defined_risk": "directional_defined_risk",
    "pin": "pin_vega",
    "vega": "pin_vega",
}

_CATALYST_HANDLING_ALIASES: dict[str, str] = {
    "exit_before": "exit_before_print",
    "exit": "exit_before_print",
    "stand-aside": "stand_aside",
    "hold_through": "hold_through_leaps",
    "hold": "hold_through_leaps",
    "no_er": "no_conflict",
    "no_conflict": "no_conflict",
    "none": "no_conflict",
    "n/a": "no_conflict",
}


def _resolve_enum(
    value: Any,
    valid: tuple[str, ...] | frozenset[str],
    aliases: dict[str, str],
    default: str,
) -> str:
    """Resolve a raw model value to a valid enum member via alias map."""
    if not isinstance(value, str):
        return default
    v = value.strip().lower().replace(" ", "_").replace("-", "_")
    if v in valid:
        return v
    if v in aliases:
        return aliases[v]
    return default


_FALSE_STRINGS = frozenset({"false", "no", "0", "off", "none", ""})


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce a value to bool, handling string "false"/"true" correctly.

    Python's bool("false") is True — this handles that case.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_STRINGS
    if value is None:
        return default
    return bool(value)


def _pick(raw: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Return only the keys in `allowed`, stripping extras for extra='forbid'."""
    return {k: v for k, v in raw.items() if k in allowed}


def _str_list_or_empty(raw: Any) -> list[str]:
    """Coerce a legs-like field to list[str].

    Claude emits leg dicts ({type, strike, ...}) where the contract expects
    plain strings. Stringify non-str elements so Pydantic's list[str] passes.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(" ".join(str(v) for v in item.values() if v))
        else:
            out.append(str(item))
    return out


def _norm(name: str) -> str:
    """Case/space/hyphen-fold a strategy or factor name (no alias fuzzing)."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _decimal_or_none(value: Any) -> Decimal | None:
    """Coerce a candidate's net_delta / net_vega toward Decimal | None.

    DeepSeek (and occasionally Claude) put a *direction word* — "long",
    "short", "positive" — where the contract expects a signed Decimal greek.
    A non-numeric value is not a fabricable number, so it degrades to None
    ("na") rather than crashing model_validate with decimal_parsing. Numeric
    values (int/float/Decimal or a numeric string like "0.42" / "-1.3") pass
    through as Decimal. This is the normalize-in-validator pattern: tolerate
    cosmetic model drift at the boundary, never invent data.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            logger.debug("non-numeric decimal value %r: %r", text, repr(exc))
            return None
    return None


def _coerce_factor_status(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in _VALID_FACTOR_STATUS:
            return candidate
    return "na"


def _pad_conviction_factors(raw_factors: Any) -> list[dict[str, Any]]:
    """Return exactly the 8 canonical factors, in canonical order.

    Provided factors are matched onto the canonical names by `_norm`; any
    canonical factor the model omitted is appended as `na`. Extra/unknown
    factors the model invented are dropped (the denominator is fixed at 8).
    """
    by_norm: dict[str, dict[str, Any]] = {}
    for item in _list_or_empty(raw_factors):
        fd = _dict_or_empty(item)
        name = _str_or(fd.get("name"), "")
        if not name:
            continue
        by_norm[_norm(name)] = {
            "name": name,
            "status": _coerce_factor_status(fd.get("status")),
            "note": _str_or(fd.get("note"), ""),
        }

    out: list[dict[str, Any]] = []
    for canonical in CANONICAL_CONVICTION_FACTORS:
        match = by_norm.get(_norm(canonical))
        if match is not None:
            # keep the model's status/note but pin the canonical name
            out.append(
                {"name": canonical, "status": match["status"], "note": match["note"]}
            )
        else:
            out.append({"name": canonical, "status": "na", "note": ""})
    return out


_DEFINED_RISK_TOKENS = frozenset(
    {
        "spread",
        "butterfly",
        "condor",
        "collar",
        "diagonal",
        "calendar",
        "vertical",
        "debit",
        "iron",
        "long",
        "protective",
        "covered",
    }
)


def _is_defined_risk_name(normed_name: str) -> bool:
    """Infer defined_risk from the structure name when the model omits the flag.

    Spreads, butterflies, condors, and other capped-loss structures are
    defined-risk by construction. Only naked shorts (short_call, short_put,
    short_strangle, short_straddle without protection) are undefined-risk.
    When uncertain, default False so the validator catches it.
    """
    parts = set(normed_name.split("_"))
    return bool(parts & _DEFINED_RISK_TOKENS)


def _coerce_candidate(raw: Any) -> dict[str, Any]:
    cd = _dict_or_empty(raw)
    _CANDIDATE_FIELDS = {
        "name",
        "legs",
        "debit_credit",
        "net_delta",
        "net_vega",
        "pnl_bull",
        "pnl_base",
        "pnl_bear",
        "defined_risk",
    }
    out = _pick(cd, _CANDIDATE_FIELDS)
    name = _str_or(cd.get("name"), "")
    out["name"] = _norm(name) if name else name
    out["legs"] = _str_list_or_empty(cd.get("legs"))
    if "net_delta" in cd:
        out["net_delta"] = _decimal_or_none(cd.get("net_delta"))
    if "net_vega" in cd:
        out["net_vega"] = _decimal_or_none(cd.get("net_vega"))
    raw_dr = cd.get("defined_risk")
    if isinstance(raw_dr, bool):
        out["defined_risk"] = raw_dr
    else:
        out["defined_risk"] = _is_defined_risk_name(out["name"])
    return out


def _coerce_header(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce framework header — normalize enums, fill required, strip extras."""
    _HEADER_FIELDS = {"thesis_one_liner", "position_type", "spot", "conviction_n"}
    out = _pick(raw, _HEADER_FIELDS)
    out["thesis_one_liner"] = _str_or(
        raw.get("thesis_one_liner") or raw.get("headline"), "partial output"
    )
    out["position_type"] = _resolve_enum(
        raw.get("position_type"),
        ("swing", "leaps", "stand_aside"),
        _POSITION_TYPE_ALIASES,
        "swing",
    )
    if "spot" in raw:
        out["spot"] = _decimal_or_none(raw.get("spot"))
    out["conviction_n"] = _int_or(raw.get("conviction_n"), 0)
    return out


def _coerce_direction(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    return {
        "verdict": _resolve_enum(
            d.get("verdict") or d.get("read"),
            ("bull", "bear", "neutral"),
            _DIRECTION_VERDICT_ALIASES,
            "neutral",
        ),
        "prose": _str_or(d.get("prose") or d.get("evidence"), "data insufficient"),
    }


def _coerce_vega(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    out: dict[str, Any] = {
        "regime": _resolve_enum(
            d.get("regime") or d.get("read"),
            ("event_iv", "demand_iv", "low_iv"),
            _VEGA_REGIME_ALIASES,
            "low_iv",
        ),
        "prose": _str_or(d.get("prose") or d.get("evidence"), "data insufficient"),
    }
    if "ivr" in d:
        out["ivr"] = _decimal_or_none(d.get("ivr"))
    if "term_slope" in d:
        out["term_slope"] = _str_or(d.get("term_slope"), None)
    return out


def _coerce_asymmetry(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    return {
        "rule_on": _coerce_bool(d.get("rule_on"), True),
        "structure_family": _resolve_enum(
            d.get("structure_family") or d.get("read"),
            ("directional_defined_risk", "pin_vega"),
            _STRUCTURE_FAMILY_ALIASES,
            "directional_defined_risk",
        ),
        "prose": _str_or(d.get("prose") or d.get("evidence"), "data insufficient"),
    }


def _coerce_three_axis(raw: Any) -> dict[str, Any]:
    ta = _dict_or_empty(raw)
    return {
        "direction": _coerce_direction(ta.get("direction")),
        "vega": _coerce_vega(ta.get("vega")),
        "asymmetry": _coerce_asymmetry(ta.get("asymmetry")),
    }


def _coerce_gamma(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    out: dict[str, Any] = {
        "regime": _resolve_enum(
            d.get("regime"),
            ("short", "long"),
            _GAMMA_REGIME_ALIASES,
            "short",
        ),
        "prose": _str_or(d.get("prose"), "data insufficient"),
    }
    if "flip_strike" in d:
        out["flip_strike"] = _decimal_or_none(d.get("flip_strike"))
    if "call_wall" in d:
        out["call_wall"] = _decimal_or_none(d.get("call_wall"))
    if "put_wall" in d:
        out["put_wall"] = _decimal_or_none(d.get("put_wall"))
    return out


def _coerce_catalyst(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    out: dict[str, Any] = {
        "handling": _resolve_enum(
            d.get("handling"),
            (
                "no_conflict",
                "exit_before_print",
                "stand_aside",
                "hold_through_leaps",
            ),
            _CATALYST_HANDLING_ALIASES,
            "stand_aside",
        ),
        "prose": _str_or(d.get("prose"), "data insufficient"),
    }
    if "next_er_date" in d:
        out["next_er_date"] = _str_or(d.get("next_er_date"), None)
    if "dte_to_er" in d:
        out["dte_to_er"] = _int_or(d.get("dte_to_er"), None)
    if "implied_move" in d:
        out["implied_move"] = _decimal_or_none(d.get("implied_move"))
    return out


def _coerce_confluence(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    signals = []
    for s in _list_or_empty(d.get("signals")):
        sd = _dict_or_empty(s)
        signals.append(
            {
                "name": _str_or(sd.get("name"), ""),
                "direction": _str_or(sd.get("direction"), ""),
            }
        )
    return {
        "aligned": _coerce_bool(d.get("aligned"), False),
        "signals": signals,
        "prose": _str_or(d.get("prose"), ""),
    }


def _coerce_pitfall(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    return {
        "id": _str_or(d.get("id"), ""),
        "title": _str_or(d.get("title"), ""),
        "triggered": _coerce_bool(d.get("triggered"), False),
        "note": _str_or(d.get("note"), ""),
    }


def _coerce_what_changes(raw: Any) -> dict[str, Any]:
    d = _dict_or_empty(raw)
    return {
        "signal": _str_or(d.get("signal"), ""),
        "effect": _str_or(d.get("effect"), ""),
    }


def _coerce_best_setup(raw: dict[str, Any]) -> dict[str, Any]:
    _BEST_SETUP_FIELDS = {
        "structure",
        "legs",
        "cost",
        "max_risk",
        "rationale",
        "why_not_alternatives",
        "invalidation",
    }
    out = _pick(raw, _BEST_SETUP_FIELDS)
    structure = _str_or(raw.get("structure"), "")
    if structure:
        out["structure"] = _norm(structure)
    out["legs"] = _str_list_or_empty(raw.get("legs"))
    out["rationale"] = _str_or(raw.get("rationale"), "data insufficient")
    out["invalidation"] = _str_or(raw.get("invalidation"), "data insufficient")
    out.setdefault("why_not_alternatives", "")
    return out


def _coerce_framework(
    raw: Any, candidates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Coerce a Claude-shaped framework dict toward the strict contract.

    Handles enum normalization, extra-field stripping (models use
    ``extra="forbid"``), missing required field defaults, and conviction
    factor padding — everything needed for a model's free-form framework
    output to round-trip through ``TradeFramework.model_validate``.
    """
    fw = _dict_or_empty(raw)

    # 1. header — normalize position_type, strip extras, fill thesis_one_liner.
    out: dict[str, Any] = {}
    out["header"] = _coerce_header(_dict_or_empty(fw.get("header")))

    # 2. three_axis — normalize verdict/regime enums, fill required prose.
    out["three_axis"] = _coerce_three_axis(fw.get("three_axis"))

    # 3. gamma — normalize regime enum.
    out["gamma"] = _coerce_gamma(fw.get("gamma"))

    # 4. catalyst — normalize handling enum.
    out["catalyst"] = _coerce_catalyst(fw.get("catalyst"))

    # 5. conviction — normalize score str->int, pad factors to canonical 8.
    conviction = _dict_or_empty(fw.get("conviction"))
    conviction_out: dict[str, Any] = {}
    conviction_out["score"] = _int_or(conviction.get("score"), 0)
    conviction_out["factors"] = _pad_conviction_factors(conviction.get("factors"))
    conviction_out["prose"] = _str_or(conviction.get("prose"), "")
    out["conviction"] = conviction_out

    # 6. confluence — normalize signals list.
    out["confluence"] = _coerce_confluence(fw.get("confluence"))

    # 7. pitfalls — coerce each item.
    out["pitfalls"] = [_coerce_pitfall(p) for p in _list_or_empty(fw.get("pitfalls"))]

    # 8. candidates — default defined_risk False, _norm names.
    out["candidates"] = [
        _coerce_candidate(c) for c in _list_or_empty(fw.get("candidates"))
    ]

    # 9. best_setup — _norm structure, fill required fields.
    best_setup = _dict_or_empty(fw.get("best_setup"))
    out["best_setup"] = (
        _coerce_best_setup(best_setup)
        if best_setup
        else {
            "structure": "stand_aside",
            "legs": [],
            "rationale": "data insufficient",
            "invalidation": "data insufficient",
        }
    )

    # 10. what_changes + bottom_line.
    out["what_changes"] = [
        _coerce_what_changes(w) for w in _list_or_empty(fw.get("what_changes"))
    ]
    out["bottom_line"] = _str_or(fw.get("bottom_line"), "data insufficient")

    return out
