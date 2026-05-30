"""Candidate, expression, and card coercion helpers."""

from __future__ import annotations

from typing import Any

from uw_scan.reports._shared_validation import STRATEGY_FAMILY_IDS
from uw_scan.reports._shared_validation.leniency.normalization import (
    _VRP_SIGNAL_FALLBACK,
    _VRP_VALID_SIGNALS,
    _dict_or_empty,
    _int_or,
    _list_or_empty,
    _opt_int,
    _str_list,
    _str_or,
)
from uw_scan.reports._shared_validation.leniency.triggers import (
    _coerce_option_legs,
    _coerce_strike_role,
    _market_structure_levels,
)


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
    item: Any,
    candidates: dict[str, dict[str, Any]],
    *,
    directional_bias: str = "WAIT",
    entry_state: str | None = None,
    deterministic_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    base = _coerce_strategy_item(item, candidates)
    if base is None:
        return None
    # v5.3 CONDITIONAL → strategy_review preservation: _coerce_strategy_item
    # always overwrites status_observed to candidate.status for known
    # candidate idea_ids. When the model correctly translates the
    # candidate-row pre-trigger status to "strategy_review" under
    # CONDITIONAL (the prompt requires this), preserve the model's emission
    # — otherwise the strict validator's conditional_quote_validity rule
    # rejects the clobbered "candidate" value downstream.
    raw_status = _str_or(raw.get("status_observed"), "")
    idea_id = base["idea_id"]
    if (
        entry_state == "CONDITIONAL"
        and raw_status == "strategy_review"
        and idea_id in candidates
        and str(candidates[idea_id].get("status") or "") == "candidate"
    ):
        base["status_observed"] = "strategy_review"
    levels = _market_structure_levels(deterministic_payload)
    strike_role = _coerce_strike_role(
        raw.get("strike_role"),
        directional_bias=directional_bias,
        levels=levels,
    )
    legs = _coerce_option_legs(raw.get("legs"))
    return {
        **base,
        "title": _str_or(raw.get("title"), base["idea_id"]),
        "subtitle": _str_or(raw.get("subtitle"), ""),
        "estimated_entry": _str_or(raw.get("estimated_entry"), ""),
        "max_profit_observed": _str_or(raw.get("max_profit_observed"), ""),
        "max_loss_observed": _str_or(raw.get("max_loss_observed"), ""),
        "reward_risk": _str_or(raw.get("reward_risk"), ""),
        "management_notes": _str_list(raw.get("management_notes")),
        "strike_role": strike_role,
        # v5.3: explicit option legs. Empty list is legal for
        # strategy_review / no_trade — M4 validator enforces geometry
        # only when legs[] is non-empty for a structured family.
        "legs": legs,
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
