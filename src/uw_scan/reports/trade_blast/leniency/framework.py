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


def _coerce_candidate(raw: Any) -> dict[str, Any]:
    cd = _dict_or_empty(raw)
    name = _str_or(cd.get("name"), "")
    out = dict(cd)
    out["name"] = _norm(name) if name else name
    # net_delta / net_vega are Decimal | None greeks. Models frequently emit a
    # direction word ("long"/"short") here; coerce non-numeric to None so the
    # candidate still validates (the safety property is defined_risk, not the
    # exact greek). Only touch keys the model actually supplied.
    if "net_delta" in cd:
        out["net_delta"] = _decimal_or_none(cd.get("net_delta"))
    if "net_vega" in cd:
        out["net_vega"] = _decimal_or_none(cd.get("net_vega"))
    # Fail-safe: absent defined_risk => False so the validator rejects a naked
    # candidate rather than silently accepting it.
    out["defined_risk"] = bool(cd.get("defined_risk", False))
    return out


def _coerce_framework(
    raw: Any, candidates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Coerce a Claude-shaped framework dict toward the strict contract.

    `candidates` is the deterministic candidate map (id -> candidate dict); it
    is accepted for signature symmetry with the other leniency coercers and
    future cross-checks, but the framework's own candidates[] are self-contained
    so it is currently unused for lookups.
    """
    fw = _dict_or_empty(raw)
    out: dict[str, Any] = dict(fw)

    # 1. conviction: normalize score str->int, pad factors to canonical 8.
    conviction = _dict_or_empty(fw.get("conviction"))
    conviction_out = dict(conviction)
    conviction_out["score"] = _int_or(conviction.get("score"), 0)
    conviction_out["factors"] = _pad_conviction_factors(conviction.get("factors"))
    out["conviction"] = conviction_out

    # 2. header.conviction_n: normalize str->int (validator enforces == score).
    header = _dict_or_empty(fw.get("header"))
    if header:
        header_out = dict(header)
        if "conviction_n" in header:
            header_out["conviction_n"] = _int_or(header.get("conviction_n"), 0)
        out["header"] = header_out

    # 3. candidates: default defined_risk False, _norm names.
    if "candidates" in fw:
        out["candidates"] = [
            _coerce_candidate(c) for c in _list_or_empty(fw.get("candidates"))
        ]

    # 4. best_setup.structure: _norm so the validator's verbatim match is
    #    drift-tolerant (matches the _norm applied to candidates[].name).
    best_setup = _dict_or_empty(fw.get("best_setup"))
    if best_setup:
        best_out = dict(best_setup)
        structure = _str_or(best_setup.get("structure"), "")
        if structure:
            best_out["structure"] = _norm(structure)
        out["best_setup"] = best_out

    return out
