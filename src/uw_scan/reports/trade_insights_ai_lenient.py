"""Claude leniency layer for Trade Insights AI outcome validation.

Claude does not reliably adhere to the strict TradeInsightAiOutcome schema
even with --json-schema and a JSON-only system prompt (see issue #67).
`_coerce_claude_outcome_dict` pre-processes Claude's raw JSON into a
structurally-valid outcome:

* Identity fields (schema_version, ticker, snapshot.*, analysis_produced_at)
  are overwritten with deterministic worker-known values so downstream
  equality checks pass deterministically.
* Missing required scalars get safe placeholders.
* Unknown keys at every nesting level are dropped (every Pydantic model
  uses extra="forbid").
* Invalid Literal values are coerced to allowed values via a vocabulary
  bridge (e.g. "range" -> "neutral", "no_trade" -> "wait", with whitespace
  and separator normalization).
* For best_expressions / preferred_expression / rejected_ideas whose
  idea_id is a known candidate, status_observed and risk_flags_observed
  are overwritten from the deterministic candidate so Claude cannot
  whitewash `needs_check` rows.
* Unknown conflict.affected_idea_ids are filtered out and recorded in
  missing_data.

The resulting dict MUST round-trip through TradeInsightAiOutcome.model_validate.
Codex stays on the strict path; this module is used only when
provider == "claude".
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any

from uw_scan.reports.trade_insights_ai import (
    DIRECTIONAL_BIAS_VALUES,
    DTE_BAND_VALUES,
    ENTRY_STATE_VALUES,
    FINAL_RATING_VALUES,
    PROMPT_VERSION,
    STRATEGY_FAMILY_IDS,
    TRADE_INTENT_VALUES,
    UNDERLYING_PATH_VALUES,
    _iso_z,
)

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


# v5 directional vocabulary — full coercion lives in M4. For M1 we only need
# safe defaults so partial Claude output still round-trips through the (now
# v5-shaped) Pydantic model. The smart coercion (case-insensitive alias map,
# spaced "long delta" -> LONG_DELTA, etc.) is added in M4.
def _derive_bias_from_stance(stance: str) -> str:
    """Conservative directional_bias inference from a resolved stance.

    Bullish/bearish stances map cleanly; everything else (neutral, mixed,
    wait — all of which mean 'no clean direction at this horizon') maps to
    WAIT so the panel does not surface a false directional call when the
    model failed to emit one explicitly. M4 will replace this with a real
    coercer that reads the explicit `directional_bias` field first."""
    if stance == "bullish":
        return "LONG_DELTA"
    if stance == "bearish":
        return "SHORT_DELTA"
    return "WAIT"


def _resolve_directional_bias(raw: Any, stance: str) -> str:
    """Pick directional_bias when supplied; otherwise derive from stance."""
    if isinstance(raw, str):
        candidate = raw.strip().upper().replace(" ", "_").replace("-", "_")
        if candidate in DIRECTIONAL_BIAS_VALUES:
            return candidate
    return _derive_bias_from_stance(stance)


def _resolve_enum(raw: Any, allowed: tuple[str, ...], default: str) -> str:
    """Generic enum resolver — case-insensitive match against allowed."""
    if isinstance(raw, str):
        candidate = raw.strip()
        for value in allowed:
            if candidate.lower() == value.lower():
                return value
    return default


def _candidate_map_from_payload(
    deterministic_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("idea_id")): candidate
        for candidate in deterministic_payload.get("candidate_structures") or []
        if candidate.get("idea_id") is not None
    }


def _coerce_label_value_item(item: Any) -> dict[str, Any] | None:
    """Shared shape for metric_cards and section.highlights — both have
    {label, value, source_path, note}. Returns None when both label and
    value are empty so we drop empty items."""
    raw = _dict_or_empty(item)
    label = _str_or(raw.get("label"), "")
    value = _str_or(raw.get("value"), "")
    if not label and not value:
        return None
    return {
        "label": label or "(unlabeled)",
        "value": value or "(no value)",
        "source_path": raw["source_path"]
        if isinstance(raw.get("source_path"), str)
        else None,
        "note": _str_or(raw.get("note"), ""),
    }


def _coerce_metric_card(item: Any) -> dict[str, Any] | None:
    coerced = _coerce_label_value_item(item)
    if coerced is None:
        return None
    raw = _dict_or_empty(item)
    return {**coerced, "tone": _str_or(raw.get("tone"), "neutral")}


def _coerce_highlight(item: Any) -> dict[str, Any] | None:
    return _coerce_label_value_item(item)


def _coerce_scenario_card(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    case_value = raw.get("case")
    if not isinstance(case_value, str) or not case_value:
        return None
    return {
        "case": case_value,
        "tone": _str_or(raw.get("tone"), "neutral"),
        "title": _str_or(raw.get("title"), case_value),
        "description": _str_or(raw.get("description"), ""),
    }


def _coerce_score_breakdown(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    section = _str_or(raw.get("section"), "")
    if not section:
        return None
    return {
        "section": section,
        "score": _int_or(raw.get("score"), 0),
        "max_score": _int_or(raw.get("max_score"), 0),
        "summary": _str_or(raw.get("summary"), ""),
    }


def _coerce_level(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    price = _str_or(raw.get("price"), "")
    kind = _str_or(raw.get("kind"), "")
    if not price and not kind:
        return None
    return {
        "price": price or "(no price)",
        "kind": kind or "level",
        "value": _str_or(raw.get("value"), ""),
        "importance": _str_or(raw.get("importance"), "normal"),
        "source_path": raw["source_path"]
        if isinstance(raw.get("source_path"), str)
        else None,
        "note": _str_or(raw.get("note"), ""),
    }


def _coerce_section_card(raw: Any, default_title: str) -> dict[str, Any]:
    data = _dict_or_empty(raw)
    return {
        "title": _str_or(data.get("title"), default_title),
        "score": _opt_int(data.get("score")),
        "max_score": _opt_int(data.get("max_score")),
        "summary": _str_or(data.get("summary"), "(no summary produced)"),
        "highlights": [
            item
            for item in (
                _coerce_highlight(h) for h in _list_or_empty(data.get("highlights"))
            )
            if item is not None
        ],
        "levels": [
            item
            for item in (
                _coerce_level(level) for level in _list_or_empty(data.get("levels"))
            )
            if item is not None
        ],
        "data_quality": _str_or(data.get("data_quality"), "unknown"),
    }


def _coerce_strategy_item(
    item: Any,
    candidates: dict[str, dict[str, Any]],
    *,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Shared coercion for best_expressions / preferred_expression items.

    For known candidate idea_ids, overwrites status_observed and
    risk_flags_observed from the deterministic candidate so Claude cannot
    whitewash a `needs_check` row to `strategy_review`. For unknown
    idea_ids, keeps Claude's values (lenient mode allows unknown ids).
    For strategy-family ids (STRATEGY_FAMILY_IDS), forces the canonical
    "strategy_review" status and empty risk_flags expected by the strict
    validator's safety check.
    """
    raw = _dict_or_empty(item)
    idea_id = _str_or(raw.get("idea_id"), "")
    if not idea_id:
        return None

    if idea_id in candidates:
        candidate = candidates[idea_id]
        status_observed = str(candidate.get("status") or "")
        risk_flags_observed = list(candidate.get("risk_flags") or [])
    elif idea_id in STRATEGY_FAMILY_IDS:
        status_observed = "strategy_review"
        risk_flags_observed = []
    else:
        status_observed = _str_or(raw.get("status_observed"), "strategy_review")
        risk_flags_observed = _str_list(raw.get("risk_flags_observed"))

    base = {
        "idea_id": idea_id,
        "structure": _str_or(raw.get("structure"), idea_id),
        "why": _str_or(raw.get("why"), ""),
        "status_observed": status_observed,
        "risk_flags_observed": risk_flags_observed,
    }
    if extra_fields is not None:
        base.update(extra_fields)
    return base


def _coerce_best_expression(
    item: Any, candidates: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    base = _coerce_strategy_item(item, candidates)
    if base is None:
        return None
    return {
        **base,
        "role": _str_or(raw.get("role"), ""),
        "caveats": _str_list(raw.get("caveats")),
    }


def _coerce_preferred_expression(
    item: Any, candidates: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    base = _coerce_strategy_item(item, candidates)
    if base is None:
        return None
    return {
        **base,
        "title": _str_or(raw.get("title"), base["idea_id"]),
        "subtitle": _str_or(raw.get("subtitle"), ""),
        "estimated_entry": _str_or(raw.get("estimated_entry"), ""),
        "max_profit_observed": _str_or(raw.get("max_profit_observed"), ""),
        "max_loss_observed": _str_or(raw.get("max_loss_observed"), ""),
        "reward_risk": _str_or(raw.get("reward_risk"), ""),
        "management_notes": _str_list(raw.get("management_notes")),
    }


def _coerce_conflict(
    item: Any,
    candidates: dict[str, dict[str, Any]],
    missing_data: list[str],
) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    description = _str_or(raw.get("description"), "")
    if not description:
        return None
    affected = _str_list(raw.get("affected_idea_ids"))
    valid, dropped = [], []
    for idea_id in affected:
        if idea_id in candidates or idea_id in STRATEGY_FAMILY_IDS:
            valid.append(idea_id)
        else:
            dropped.append(idea_id)
    for idea_id in dropped:
        note = f"conflict.affected_idea_ids: unknown idea_id dropped: {idea_id}"
        if note not in missing_data:
            missing_data.append(note)
    return {
        "lens": _str_or(raw.get("lens"), "unspecified"),
        "severity": _str_or(raw.get("severity"), "medium"),
        "description": description,
        "affected_idea_ids": valid,
    }


def _coerce_required_check(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    check = _str_or(raw.get("check"), "")
    if not check:
        return None
    blocks_raw = raw.get("blocks_sizing", True)
    return {
        "check": check,
        "reason": _str_or(raw.get("reason"), ""),
        "blocks_sizing": blocks_raw is True if isinstance(blocks_raw, bool) else True,
        "source": _str_or(raw.get("source"), ""),
    }


def _coerce_rejected_idea(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    idea_id = _str_or(raw.get("idea_id"), "")
    if not idea_id:
        return None
    return {
        "idea_id": idea_id,
        "structure": _str_or(raw.get("structure"), idea_id),
        "reason": _str_or(raw.get("reason"), ""),
    }


def _coerce_vrp_assessment(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    title = _str_or(raw.get("title"), "")
    summary = _str_or(raw.get("summary"), "")
    if not title and not summary:
        return None
    signal_raw = raw.get("signal")
    signal = (
        signal_raw
        if isinstance(signal_raw, str) and signal_raw in _VRP_VALID_SIGNALS
        else _VRP_SIGNAL_FALLBACK
    )
    return {
        "signal": signal,
        "title": title or "VRP",
        "summary": summary,
        "metrics": [
            item
            for item in (
                _coerce_metric_card(m) for m in _list_or_empty(raw.get("metrics"))
            )
            if item is not None
        ],
        "reason": _str_or(raw.get("reason"), ""),
    }


def _coerce_claude_outcome_dict(
    raw: Any,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    expected_analysis_input_hash: str,
) -> dict[str, Any]:
    """Coerce Claude's free-form JSON into a TradeInsightAiOutcome-shaped dict.

    See module docstring for full behavior. The result MUST round-trip
    through TradeInsightAiOutcome.model_validate.
    """
    data = raw if isinstance(raw, dict) else {}
    candidates = _candidate_map_from_payload(deterministic_payload)

    headline_raw = _dict_or_empty(data.get("headline"))
    stance_raw = headline_raw.get("stance")
    stance = _resolve_stance(stance_raw)
    conviction = _resolve_conviction(headline_raw.get("conviction"))

    ticker = _str_or(deterministic_payload.get("ticker"), "TICKER")
    # Preserve the raw analyst vocabulary in stance_label when the model
    # didn't provide an explicit label — keeps "range" / "no_trade"
    # visible in the UI while the Literal `stance` lands on a valid value.
    default_stance_label = (
        stance_raw
        if isinstance(stance_raw, str) and stance_raw.strip()
        else "Partial output"
    )
    directional_bias = _resolve_directional_bias(
        headline_raw.get("directional_bias"), stance
    )
    headline = {
        # v5 required directional fields — backfilled with safe defaults when
        # the provider omits them so the lenient path still produces a
        # round-trippable outcome. Smart coercion (alias maps, mode-structure
        # consistency enforcement) lands in M4.
        "trade_intent": _resolve_enum(
            headline_raw.get("trade_intent"),
            TRADE_INTENT_VALUES,
            "directional_swing",
        ),
        "directional_bias": directional_bias,
        "entry_state": _resolve_enum(
            headline_raw.get("entry_state"),
            ENTRY_STATE_VALUES,
            # CONDITIONAL is the safe default — it signals "setup may be valid
            # but trigger has not fired", which is the most honest state when
            # the model failed to emit entry_state explicitly. NO_ENTRY would
            # imply we *evaluated* and rejected.
            "CONDITIONAL",
        ),
        "underlying_path": _resolve_enum(
            headline_raw.get("underlying_path"),
            UNDERLYING_PATH_VALUES,
            "data_insufficient",
        ),
        "dte_band": _resolve_enum(
            headline_raw.get("dte_band"),
            DTE_BAND_VALUES,
            # trend (45-75 DTE) is the lower-gamma safer default; momentum
            # band (14-30 DTE) needs an explicit breakout thesis the lenient
            # path cannot infer from missing data.
            "trend",
        ),
        "title": _str_or(headline_raw.get("title"), f"{ticker} — partial output"),
        "stance": stance,
        "stance_label": _str_or(headline_raw.get("stance_label"), default_stance_label),
        "score": _int_or(headline_raw.get("score"), 0),
        "score_scale": _int_or(headline_raw.get("score_scale"), 100),
        "conviction": conviction,
        "conviction_label": _str_or(
            headline_raw.get("conviction_label"), "data insufficient"
        ),
        "top_reason": _str_or(headline_raw.get("top_reason"), _PARTIAL_OUTPUT_NOTE),
        "primary_risk": _str_or(
            headline_raw.get("primary_risk"), "provider schema adherence"
        ),
        "watch_trigger": _str_or(headline_raw.get("watch_trigger"), "re-run analysis"),
    }

    snapshot_raw = _dict_or_empty(data.get("snapshot"))
    data_as_of_raw = snapshot_raw.get("data_as_of") or data.get("data_as_of")
    snapshot = {
        "run_id": deterministic_payload.get("run_id"),
        "trade_insights_input_hash": deterministic_payload.get(
            "trade_insights_input_hash"
        ),
        "analysis_input_hash": expected_analysis_input_hash,
        "data_as_of": data_as_of_raw
        if isinstance(data_as_of_raw, str) and data_as_of_raw
        else None,
        "freshness_label": _str_or(snapshot_raw.get("freshness_label"), "unknown"),
        "source_notes": _str_list(snapshot_raw.get("source_notes")),
    }

    section_cards_raw = _dict_or_empty(data.get("section_cards"))
    section_cards = {
        "market_structure": _coerce_section_card(
            section_cards_raw.get("market_structure"), "Market Structure"
        ),
        "volatility": _coerce_section_card(
            section_cards_raw.get("volatility"), "Volatility"
        ),
        "flow_positioning": _coerce_section_card(
            section_cards_raw.get("flow_positioning"), "Flow & Positioning"
        ),
    }

    dominant_read_raw = _dict_or_empty(data.get("dominant_read"))
    dominant_read = {
        "headline": _str_or(dominant_read_raw.get("headline"), headline["title"]),
        "summary": _str_or(dominant_read_raw.get("summary"), headline["top_reason"]),
        "confidence_commentary": _str_or(
            dominant_read_raw.get("confidence_commentary"),
            "Partial output — confidence not reported by provider.",
        ),
        "data_quality_commentary": _str_or(
            dominant_read_raw.get("data_quality_commentary"),
            _PARTIAL_OUTPUT_NOTE,
        ),
    }

    rendering_raw = _dict_or_empty(data.get("rendering"))
    rendering = {
        "disclaimer": _str_or(
            rendering_raw.get("disclaimer"),
            "Research-only — partial output captured; not order-placement instructions.",
        ),
        "card_order": _str_list(rendering_raw.get("card_order")),
    }

    # Guardrails: default to True when Claude omits them (Claude doesn't know
    # what these mean and we want to allow lenient capture). The validator
    # ALSO enforces all-true downstream — see validate_trade_insights_ai_outcome.
    # An explicit False from Claude flows through and is rejected post-coerce.
    guardrails_raw = _dict_or_empty(data.get("guardrails"))

    def _guardrail_bool(key: str) -> bool:
        v = guardrails_raw.get(key, True)
        return v if isinstance(v, bool) else True

    guardrails = {
        "statuses_preserved": _guardrail_bool("statuses_preserved"),
        "risk_flags_preserved": _guardrail_bool("risk_flags_preserved"),
        "no_executable_recommendations": _guardrail_bool(
            "no_executable_recommendations"
        ),
    }

    missing_data = _str_list(data.get("missing_data"))
    if any(
        value in (None, "", [])
        for value in (
            headline_raw.get("stance"),
            headline_raw.get("title"),
            data.get("snapshot"),
            data.get("section_cards"),
            data.get("dominant_read"),
        )
    ):
        missing_data = [_PARTIAL_OUTPUT_NOTE, *missing_data]

    coerced: dict[str, Any] = {
        "schema_version": PROMPT_VERSION,
        "analysis_produced_at": _iso_z(produced_at),
        "ticker": ticker,
        "underlying_price": data.get("underlying_price")
        if isinstance(data.get("underlying_price"), str)
        else None,
        "snapshot": snapshot,
        "headline": headline,
        "metric_cards": [
            item
            for item in (
                _coerce_metric_card(m) for m in _list_or_empty(data.get("metric_cards"))
            )
            if item is not None
        ],
        "scenario_cards": [
            item
            for item in (
                _coerce_scenario_card(s)
                for s in _list_or_empty(data.get("scenario_cards"))
            )
            if item is not None
        ],
        "score_breakdown": [
            item
            for item in (
                _coerce_score_breakdown(s)
                for s in _list_or_empty(data.get("score_breakdown"))
            )
            if item is not None
        ],
        "section_cards": section_cards,
        "vrp_assessment": _coerce_vrp_assessment(data.get("vrp_assessment")),
        "preferred_expression": _coerce_preferred_expression(
            data.get("preferred_expression"), candidates
        ),
        "dominant_read": dominant_read,
        "best_expressions": [
            item
            for item in (
                _coerce_best_expression(b, candidates)
                for b in _list_or_empty(data.get("best_expressions"))
            )
            if item is not None
        ],
        "conflicts": [
            item
            for item in (
                _coerce_conflict(c, candidates, missing_data)
                for c in _list_or_empty(data.get("conflicts"))
            )
            if item is not None
        ],
        "required_checks": [
            item
            for item in (
                _coerce_required_check(r)
                for r in _list_or_empty(data.get("required_checks"))
            )
            if item is not None
        ],
        "rejected_ideas": [
            item
            for item in (
                _coerce_rejected_idea(r)
                for r in _list_or_empty(data.get("rejected_ideas"))
            )
            if item is not None
        ],
        "missing_data": missing_data,
        "rendering": rendering,
        "guardrails": guardrails,
    }
    return coerced
