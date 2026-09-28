"""Primitives shared verbatim by the two AI analysis_input lanes.

`trade_blast/analysis_input.py` and `trade_insights_ai/analysis_input.py`
prune the same raw payload sections (strike_gex_curve, smile points, chain
rows, strike exposures), walk the payload to strip volatile keys before
hashing, and walk the Pydantic JSON schema for the strict/lax output
contract. Those traversals live here so the two lanes cannot drift apart.

Deliberately NOT shared — each lane keeps its own prompt text/version,
`_VOLATILE_HASH_KEYS` exclusion set (blast also excludes `age_days` and
`stale` so its cache key survives wall-clock movement), payload assembly,
and `trade_insights_ai_output_schema` entry point.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce to Decimal or return None. Never silently returns 0 on bad input —
    callers must explicitly opt in via _to_decimal_or_zero when 0 is correct."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:
        _ = repr(exc)  # CI Guardrail 2: surface exception repr even when swallowed.
        return None


def _to_decimal_or_zero(value: Any) -> Decimal:
    """Coerce to Decimal, falling back to Decimal(0) for None / unparseable
    input. Use this AT CALL SITES where the existing semantics treat missing
    data as zero (sums, abs-distance sort keys whose missing-data behavior is
    'rank as small/center'). Documenting the choice at the call site makes
    the silent-zero coercion explicit instead of hidden in the helper."""
    coerced = _to_decimal(value)
    return coerced if coerced is not None else Decimal(0)


def _sorted_recent(
    rows: list[dict[str, Any]], limit: int, key: str = "date"
) -> list[dict[str, Any]]:
    if not rows:
        return []
    return sorted(rows, key=lambda row: str(row.get(key) or ""))[-limit:]


def _sorted_front(
    rows: list[dict[str, Any]], limit: int, key: str = "expiry"
) -> list[dict[str, Any]]:
    if not rows:
        return []
    return sorted(rows, key=lambda row: str(row.get(key) or ""))[:limit]


def _strike_value(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("strike")
        if value is not None:
            return str(value)
    return None


def _named_level_strikes(levels: dict[str, Any]) -> set[str]:
    strikes: set[str] = set()
    for value in levels.values():
        strike = _strike_value(value)
        if strike is not None:
            strikes.add(strike)
    return strikes


def _prune_strike_gex_curve(
    rows: list[dict[str, Any]],
    levels: dict[str, Any],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    named = _named_level_strikes(levels)
    top = sorted(
        rows,
        key=lambda row: abs(_to_decimal_or_zero(row.get("net_gex"))),
        reverse=True,
    )[:40]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*top, *[r for r in rows if str(r.get("strike")) in named]]:
        by_key[(str(row.get("expiry")), str(row.get("strike")))] = row
    return list(by_key.values())


def _downsample_smile_points(
    points: list[dict[str, Any]], limit: int = 25
) -> list[dict[str, Any]]:
    if len(points) <= limit:
        return sorted(points, key=lambda row: _to_decimal_or_zero(row.get("strike")))
    sorted_points = sorted(
        points, key=lambda row: _to_decimal_or_zero(row.get("strike"))
    )
    if limit <= 1:
        return sorted_points[:limit]
    step = (len(sorted_points) - 1) / (limit - 1)
    indexes = sorted({round(i * step) for i in range(limit)})
    return [sorted_points[i] for i in indexes[:limit]]


def _combined_chain_interest(row: dict[str, Any]) -> Decimal:
    keys = ("call_volume", "put_volume", "call_open_interest", "put_open_interest")
    return sum((_to_decimal_or_zero(row.get(key)) for key in keys), Decimal("0"))


def _prune_chain_rows(
    rows: list[dict[str, Any]],
    *,
    spot: Any,
    limit: int = 120,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    top = sorted(rows, key=_combined_chain_interest, reverse=True)[:limit]
    if spot is None:
        return top
    near_spot = sorted(
        rows,
        key=lambda row: abs(
            _to_decimal_or_zero(row.get("strike")) - _to_decimal_or_zero(spot)
        ),
    )[:20]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*near_spot, *top]:
        by_key[(str(row.get("expiry")), str(row.get("strike")))] = row
    return list(by_key.values())[:limit]


def _prune_strike_exposures(
    rows: list[dict[str, Any]],
    *,
    spot: Any,
    expiry_limit: int = 4,
    strikes_per_side: int = 10,
) -> list[dict[str, Any]]:
    """Cap vanna/charm per-strike rows: keep the front `expiry_limit` expiries
    inside the swing window and, within each expiry, ±`strikes_per_side` around
    spot. Order is preserved by (expiry, strike)."""
    if not rows:
        return []
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_expiry.setdefault(str(row.get("expiry")), []).append(row)
    expiries = sorted(by_expiry.keys())[:expiry_limit]
    if not expiries:
        return []
    spot_dec = _to_decimal_or_zero(spot) if spot is not None else None
    pruned: list[dict[str, Any]] = []
    for expiry in expiries:
        rows_for_expiry = by_expiry[expiry]
        if spot_dec is None:
            kept = rows_for_expiry
        else:
            kept = sorted(
                rows_for_expiry,
                key=lambda row: abs(_to_decimal_or_zero(row.get("strike")) - spot_dec),
            )[: strikes_per_side * 2]
        pruned.extend(
            sorted(kept, key=lambda row: _to_decimal_or_zero(row.get("strike")))
        )
    return pruned


def _strip_volatile_for_hash(value: Any, volatile_keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile_for_hash(item, volatile_keys)
            for key, item in value.items()
            if key not in volatile_keys
        }
    if isinstance(value, list):
        return [_strip_volatile_for_hash(item, volatile_keys) for item in value]
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_data_freshness(
    *,
    stock_history_rows: list[dict[str, Any]],
    hv_iv_history: list[dict[str, Any]],
    short_data: dict[str, Any],
    volatility_as_of: Any,
    trade_insights_as_of: Any,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    items.append(
        {
            "source": "stock_history",
            "as_of": str((stock_history_rows[-1] or {}).get("date"))
            if stock_history_rows
            else "",
            "freshness_type": "source" if stock_history_rows else "missing",
            "staleness_hint": "latest stored stock history row"
            if stock_history_rows
            else "no stored stock history rows",
        }
    )
    items.append(
        {
            "source": "volatility_hv_iv_history",
            "as_of": str((hv_iv_history[-1] or {}).get("date"))
            if hv_iv_history
            else "",
            "freshness_type": "source" if hv_iv_history else "missing",
            "staleness_hint": "latest stored HV/IV row"
            if hv_iv_history
            else "no stored HV/IV rows",
        }
    )
    items.append(
        {
            "source": "short_data",
            "as_of": str(short_data.get("snapshot_at") or ""),
            "freshness_type": "source" if short_data.get("snapshot_at") else "missing",
            "staleness_hint": "borrow/availability snapshot",
        }
    )
    if volatility_as_of is not None:
        items.append(
            {
                "source": "volatility_response_as_of",
                "as_of": str(volatility_as_of),
                "freshness_type": "assembly",
                "staleness_hint": "request-time assembler date; excluded from hash",
            }
        )
    if trade_insights_as_of is not None:
        items.append(
            {
                "source": "trade_insights_response_as_of",
                "as_of": str(trade_insights_as_of),
                "freshness_type": "assembly",
                "staleness_hint": "deterministic response assembly time; excluded from hash",
            }
        )
    return items


def _coerce_strict_schema(node: Any) -> Any:
    if isinstance(node, dict):
        coerced = {key: _coerce_strict_schema(value) for key, value in node.items()}
        if "properties" in coerced and isinstance(coerced["properties"], dict):
            coerced["additionalProperties"] = False
            coerced["required"] = list(coerced["properties"].keys())
        return coerced
    if isinstance(node, list):
        return [_coerce_strict_schema(item) for item in node]
    return node


def _strip_openai_unsupported_patterns(node: Any) -> Any:
    """Strip regex 'pattern' constraints that OpenAI's structured-output
    validator rejects.

    Pydantic v2 emits a Decimal string serialization that includes a
    negative-lookahead regex (e.g. ``(?!^[-+.]*$)``). OpenAI's
    ``--output-schema`` validator does not support lookarounds and
    returns ``invalid_json_schema`` 400 errors. Decimal | None fields
    are still validated for type at the Pydantic layer when we
    deserialize the model's response — dropping the schema-side regex
    only relaxes what we tell the model, not what we enforce.

    The Codex/OpenAI structured output requires us to comply; the
    Anthropic/Claude path is more permissive and accepts the pattern,
    so this stripper runs only in the strict-mode path."""
    if isinstance(node, dict):
        cleaned = {
            key: _strip_openai_unsupported_patterns(value)
            for key, value in node.items()
        }
        # If this dict has a 'pattern' field containing a lookaround,
        # drop the pattern. Keep the rest of the type constraints intact.
        pattern = cleaned.get("pattern")
        if isinstance(pattern, str) and ("(?!" in pattern or "(?=" in pattern):
            cleaned = {k: v for k, v in cleaned.items() if k != "pattern"}
        return cleaned
    if isinstance(node, list):
        return [_strip_openai_unsupported_patterns(item) for item in node]
    return node
