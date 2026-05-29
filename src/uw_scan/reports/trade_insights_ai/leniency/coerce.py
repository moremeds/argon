"""Top-level Claude outcome coercion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from uw_scan.reports.trade_insights_ai import (
    DTE_BAND_VALUES,
    ENTRY_STATE_VALUES,
    PROMPT_VERSION,
    TRADE_INTENT_VALUES,
    UNDERLYING_PATH_VALUES,
    _iso_z,
)
from uw_scan.reports.trade_insights_ai.leniency.candidates import (
    _candidate_map_from_payload,
    _coerce_best_expression,
    _coerce_conflict,
    _coerce_metric_card,
    _coerce_preferred_expression,
    _coerce_rejected_idea,
    _coerce_required_check,
    _coerce_scenario_card,
    _coerce_score_breakdown,
    _coerce_section_card,
    _coerce_vrp_assessment,
)
from uw_scan.reports.trade_insights_ai.leniency.framework import _coerce_framework
from uw_scan.reports.trade_insights_ai.leniency.normalization import (
    _PARTIAL_OUTPUT_NOTE,
    _dict_or_empty,
    _int_or,
    _list_or_empty,
    _resolve_conviction,
    _resolve_stance,
    _str_list,
    _str_or,
)
from uw_scan.reports.trade_insights_ai.leniency.triggers import (
    _coerce_anti_pin,
    _coerce_target_feasibility,
    _coerce_trigger_component,
    _coerce_trigger_evidence,
)
from uw_scan.reports.trade_insights_ai.leniency.vocabulary import (
    _DTE_BAND_ALIASES,
    _ENTRY_STATE_ALIASES,
    _THESIS_ARCHETYPE_ALIASES,
    _TRADE_INTENT_ALIASES,
    _UNDERLYING_PATH_ALIASES,
    _derive_thesis_archetype_from_path,
    _resolve_directional_bias,
    _resolve_with_alias,
)


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
        # v5 required directional fields. The smart resolvers translate the
        # common analyst-vocabulary drifts ("long delta"/"longdelta"/"long",
        # "range"/"pinned"/"rangebound", "watchlist"/"pending") into the
        # canonical Pydantic Literal values via alias maps.
        "trade_intent": _resolve_with_alias(
            headline_raw.get("trade_intent"),
            TRADE_INTENT_VALUES,
            _TRADE_INTENT_ALIASES,
            "directional_swing",
        ),
        "directional_bias": directional_bias,
        "entry_state": _resolve_with_alias(
            headline_raw.get("entry_state"),
            ENTRY_STATE_VALUES,
            _ENTRY_STATE_ALIASES,
            # CONDITIONAL is the safe default — it signals "setup may be valid
            # but trigger has not fired", which is the most honest state when
            # the model failed to emit entry_state explicitly. NO_ENTRY would
            # imply we *evaluated* and rejected.
            "CONDITIONAL",
        ),
        "underlying_path": _resolve_with_alias(
            headline_raw.get("underlying_path"),
            UNDERLYING_PATH_VALUES,
            _UNDERLYING_PATH_ALIASES,
            "data_insufficient",
        ),
        "dte_band": _resolve_with_alias(
            headline_raw.get("dte_band"),
            DTE_BAND_VALUES,
            _DTE_BAND_ALIASES,
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
        # v5.2: thesis_archetype with default backfill from underlying_path.
        "thesis_archetype": _resolve_with_alias(
            headline_raw.get("thesis_archetype"),
            (
                "resistance_rejection",
                "support_breakdown",
                "breakout_continuation",
                "pin_no_trade",
                "data_insufficient",
            ),
            _THESIS_ARCHETYPE_ALIASES,
            _derive_thesis_archetype_from_path(
                _resolve_with_alias(
                    headline_raw.get("underlying_path"),
                    UNDERLYING_PATH_VALUES,
                    _UNDERLYING_PATH_ALIASES,
                    "data_insufficient",
                )
            ),
        ),
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
            data.get("preferred_expression"),
            candidates,
            directional_bias=directional_bias,
            entry_state=headline.get("entry_state"),
            deterministic_payload=deterministic_payload,
        ),
        # v5.2: structured trigger_evidence / anti_pin / target_feasibility
        # blocks. Defaults are computed deterministically from the payload
        # so the validator's ACTIVE_TRIGGER_EVIDENCE rule can fire even when
        # the model omits the block entirely. trigger_level for the evidence
        # block is sourced from the preferred_expression's strike_role
        # (after its own backfill) for consistency.
        "trigger_evidence": (
            trigger_evidence := _coerce_trigger_evidence(
                data.get("trigger_evidence"),
                trigger_level_from_strike_role=(
                    _dict_or_empty(data.get("preferred_expression"))
                    .get("strike_role", {})
                    .get("trigger_level")
                    if isinstance(data.get("preferred_expression"), dict)
                    else None
                ),
                deterministic_payload=deterministic_payload,
                watch_trigger=headline.get("watch_trigger", ""),
            )
        ),
        "anti_pin": _coerce_anti_pin(data.get("anti_pin")),
        "target_feasibility": _coerce_target_feasibility(
            data.get("target_feasibility")
        ),
        # v5.3: decomposed trigger state machine. When the model emits its
        # own thesis_trigger / entry_trigger / invalidation, prefer those.
        # Otherwise backfill from the v5.2 trigger_evidence block and
        # strike_role.invalid_level so v5.2-shape outputs still produce a
        # populated v5.3 surface (the M4 validator's mechanical ENTRY_STATE
        # check will then either pass or surface honest CONDITIONAL state
        # rather than a default-null trigger that would otherwise read as
        # NEEDS_CHECK).
        "thesis_trigger": _coerce_trigger_component(
            data.get("thesis_trigger"),
            fallback_level=trigger_evidence.get("trigger_level"),
            fallback_meaning=(
                f"{headline['thesis_archetype']}_confirmed"
                if trigger_evidence.get("trigger_fired")
                else f"{headline['thesis_archetype']}_pending"
            ),
            fallback_fired=bool(trigger_evidence.get("trigger_fired")),
            fallback_evidence_close=trigger_evidence.get("evidence_close"),
            fallback_evidence_date=trigger_evidence.get("evidence_close_date"),
            fallback_source_path=trigger_evidence.get("source_path", ""),
        ),
        "entry_trigger": _coerce_trigger_component(
            data.get("entry_trigger"),
            # v5.2-shape outputs collapse thesis and entry into a single
            # trigger_evidence — mirror it as the entry_trigger fallback
            # so the UI does not show empty cells. The M4 derivation check
            # still requires a real distinct meaning for v5.3 native runs.
            fallback_level=trigger_evidence.get("trigger_level"),
            fallback_meaning="entry_confirmation",
            fallback_fired=bool(trigger_evidence.get("trigger_fired")),
            fallback_evidence_close=trigger_evidence.get("evidence_close"),
            fallback_evidence_date=trigger_evidence.get("evidence_close_date"),
            fallback_source_path=trigger_evidence.get("source_path", ""),
        ),
        "invalidation": _coerce_trigger_component(
            data.get("invalidation"),
            fallback_level=(
                _dict_or_empty(data.get("preferred_expression"))
                .get("strike_role", {})
                .get("invalid_level")
                if isinstance(data.get("preferred_expression"), dict)
                else None
            ),
            fallback_meaning="thesis_invalidated",
            fallback_fired=False,
            fallback_source_path="",
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
    # v6.0: additive framework{} block. Only coerce when the model emitted one
    # — absent => omitted entirely so the field defaults to None and the
    # semantic validator skips it (graceful for providers that drop the block).
    if isinstance(data.get("framework"), dict):
        coerced["framework"] = _coerce_framework(data["framework"], candidates)
    return coerced
