"""Deterministic HARD validators for Trade Insights AI outcomes.

Every `_check_*` function raises `ValueError` (caught upstream and surfaced
as a structured rejection) when the model output violates the contract the
prompt promises. `validate_trade_insights_ai_outcome` is the entry point.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from uw_scan.models import TradeInsightAiOutcome

from .analysis_input import (
    _iso_z,
    hash_trade_insights_ai_analysis_input,
)
from .prompt_text import (
    DIRECTIONAL_SWING_STRUCTURES,
    DTE_BAND_RANGES,
    FINAL_RATING_VALUES,
    PREFERRED_STRATEGY_FAMILY_IDS,
    PROMPT_VERSION,
    RANGE_INCOME_STRUCTURES,
    STRATEGY_FAMILY_IDS,
)

_IMPERATIVE_PHRASES = (
    "buy now",
    "sell now",
    "enter now",
    "execute this trade",
    "place this order",
    "size this position",
)
_IMPERATIVE_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\byou\s+should\s+(?:buy|sell|enter|open|execute)\b",
        r"\bmust\s+(?:buy|sell|enter|open|execute)\b",
        r"\b(?:take|open)\s+this\s+trade\b",
        r"\b(?:place|send)\s+(?:this|the|an?)\s+order\b",
        r"\bgo\s+(?:long|short)\s+now\b",
    )
)


def _candidate_map(deterministic_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("idea_id")): candidate
        for candidate in deterministic_payload.get("candidate_structures") or []
        if candidate.get("idea_id") is not None
    }


def _known_idea_id(idea_id: str, candidates: dict[str, dict[str, Any]]) -> bool:
    return idea_id in candidates or idea_id in STRATEGY_FAMILY_IDS


_PATH_PART_INDEX_RE = re.compile(r"\[-?\d*\]")
_SOURCE_PATH_ALIASES = (
    (
        "tabs.market_structure.market_structure.stock_history.",
        "tabs.market_structure.stock_history.",
    ),
)


def _canonical_source_path(path: str, deterministic_payload: dict[str, Any]) -> str:
    for invalid_prefix, canonical_prefix in _SOURCE_PATH_ALIASES:
        if not path.startswith(invalid_prefix):
            continue
        candidate = f"{canonical_prefix}{path.removeprefix(invalid_prefix)}"
        if _path_family_exists(candidate, deterministic_payload):
            return candidate
    return path


def _path_family_exists(path: str, deterministic_payload: dict[str, Any]) -> bool:
    parts = [_PATH_PART_INDEX_RE.sub("", p) for p in path.split(".") if p]
    if not parts:
        return False
    return _path_parts_exist(deterministic_payload, parts)


def _path_parts_exist(node: Any, parts: list[str]) -> bool:
    if not parts:
        return True
    if isinstance(node, list):
        if not node:
            return False
        return any(_path_parts_exist(item, parts) for item in node)
    part = parts[0]
    if not isinstance(node, dict) or part not in node:
        return False
    return _path_parts_exist(node[part], parts[1:])


def _mentions_missing_data(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    text = " ".join(str(item.get(key) or "") for key in ("label", "value", "note"))
    return "missing" in text.lower() or "unavailable" in text.lower()


def _missing_data_mentions(outcome: TradeInsightAiOutcome, token: str) -> bool:
    needle = token.lower()
    return any(needle in item.lower() for item in outcome.missing_data)


def _validate_source_path_item(
    item: Any,
    deterministic_payload: dict[str, Any],
    outcome: TradeInsightAiOutcome,
) -> None:
    source_path = getattr(item, "source_path", None)
    item_payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
    if not source_path:
        if _mentions_missing_data(item_payload):
            return
        raise ValueError(
            "source_path is required unless the item is a missing-data note"
        )
    lowered = source_path.lower()
    # `vanna` and `charm` used to be unavailable in this product; PR #60 made
    # them first-class fields via exposures_summary + strike_exposures. Allow
    # references provided the path family resolves below. `short_interest` is
    # still indirect — only the `short_data` block is forwarded — so it stays
    # gated on a missing-data acknowledgement.
    if "short_interest" in lowered and not _missing_data_mentions(
        outcome, "short_interest"
    ):
        raise ValueError(f"unavailable source field referenced: {source_path}")
    canonical_source_path = _canonical_source_path(source_path, deterministic_payload)
    if canonical_source_path != source_path:
        item.source_path = canonical_source_path
        source_path = canonical_source_path
    if not _path_family_exists(source_path, deterministic_payload):
        raise ValueError(f"source_path prefix does not exist: {source_path}")


# v5 delta-match whitelists. The four directional structures whose net delta
# is unambiguously positive go in LONG; the mirror set goes in SHORT. The
# legacy "no_trade" sentinel is allowed under any directional_bias because
# it explicitly signals "no preferred expression — see scenarios for the
# conditional setup."
_LONG_DELTA_STRUCTURES = frozenset(
    {
        "long_call",
        "call_debit_spread",
        "bull_call_spread",
        "call_diagonal",
    }
)
_SHORT_DELTA_STRUCTURES = frozenset(
    {
        "long_put",
        "put_debit_spread",
        "bear_put_spread",
        "put_diagonal",
    }
)


def _check_mode_structure_consistency(outcome: TradeInsightAiOutcome) -> None:
    """Enforce trade_intent → structure whitelist.

    directional_swing → preferred_expression.structure ∈ DIRECTIONAL_SWING_STRUCTURES
    range_income      → preferred_expression.structure ∈ RANGE_INCOME_STRUCTURES

    Raises ValueError on mismatch. Iron condor / credit spreads / calendars
    surfacing as preferred when trade_intent=directional_swing is the exact
    failure mode v5 is built to eliminate, so this MUST be a hard reject in
    both strict and lenient modes — never a silent coercion."""
    pref = outcome.preferred_expression
    if pref is None:
        return
    trade_intent = outcome.headline.trade_intent
    structure = pref.structure
    if trade_intent == "directional_swing":
        if structure not in DIRECTIONAL_SWING_STRUCTURES:
            raise ValueError(
                f"trade_intent=directional_swing but preferred_expression.structure="
                f"{structure!r} is not in the directional whitelist "
                f"{sorted(DIRECTIONAL_SWING_STRUCTURES)}"
            )
    elif trade_intent == "range_income":
        if structure not in RANGE_INCOME_STRUCTURES:
            raise ValueError(
                f"trade_intent=range_income but preferred_expression.structure="
                f"{structure!r} is not in the range-income whitelist "
                f"{sorted(RANGE_INCOME_STRUCTURES)}"
            )


def _check_delta_match(outcome: TradeInsightAiOutcome) -> None:
    """Enforce directional_bias → structure net-delta sign.

    LONG_DELTA  → structure ∈ _LONG_DELTA_STRUCTURES  (or no_trade)
    SHORT_DELTA → structure ∈ _SHORT_DELTA_STRUCTURES (or no_trade)
    WAIT        → structure == 'no_trade'

    The no_trade escape hatch is allowed under LONG/SHORT bias when the
    model is describing a CONDITIONAL setup (trigger not yet fired); the
    Scenarios section then names the long/short expressions that would
    activate. WAIT, however, must commit to no_trade — anything else
    contradicts the bias decision."""
    pref = outcome.preferred_expression
    if pref is None:
        return
    bias = outcome.headline.directional_bias
    structure = pref.structure
    if structure == "no_trade":
        # Allowed under any bias. WAIT requires it (handled below).
        return
    if bias == "LONG_DELTA":
        if structure not in _LONG_DELTA_STRUCTURES:
            raise ValueError(
                f"directional_bias=LONG_DELTA but preferred_expression.structure="
                f"{structure!r} is not net-positive-delta "
                f"{sorted(_LONG_DELTA_STRUCTURES)}"
            )
    elif bias == "SHORT_DELTA":
        if structure not in _SHORT_DELTA_STRUCTURES:
            raise ValueError(
                f"directional_bias=SHORT_DELTA but preferred_expression.structure="
                f"{structure!r} is not net-negative-delta "
                f"{sorted(_SHORT_DELTA_STRUCTURES)}"
            )
    elif bias == "WAIT":
        # Structure already filtered for no_trade above; reaching here means
        # the model picked a real structure under WAIT, which contradicts the
        # bias decision.
        raise ValueError(
            f"directional_bias=WAIT requires preferred_expression.structure="
            f"'no_trade', got {structure!r}"
        )


def _parse_decimal_loose(value: Any) -> Decimal | None:
    """Loose Decimal parser: strips $ prefix and whitespace; returns None on
    blank/unparseable. Used by v5.1 validator rules that read strike_role
    levels (model emits these as strings)."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.lstrip("$").replace(",", "").strip()
    try:
        return Decimal(raw)
    except Exception as exc:
        _ = repr(exc)  # CI Guardrail 2: surface in repr even on swallow.
        return None


def _short_leg_strike(
    candidate: dict[str, Any] | None, side_right: str
) -> Decimal | None:
    """Return the strike of the candidate's short leg matching `side_right`.

    `side_right` is "C" (LONG_DELTA breakouts — short call leg) or "P"
    (SHORT_DELTA downside breaks — short put leg). Returns None when the
    candidate is missing, has no legs, or the matching short leg is
    absent (e.g. long_call / long_put has no short leg)."""
    if not candidate:
        return None
    legs = candidate.get("legs") or []
    for leg in legs:
        if not isinstance(leg, dict):
            # CandidateStructure objects too
            side = getattr(leg, "side", None)
            right = getattr(leg, "option_right", None)
            strike = getattr(leg, "strike", None)
        else:
            side = leg.get("side")
            right = leg.get("option_right")
            strike = leg.get("strike")
        if side == "short" and right == side_right and strike is not None:
            return _parse_decimal_loose(strike)
    return None


def _check_trigger_strike_consistency(
    outcome: TradeInsightAiOutcome,
    candidates: dict[str, dict[str, Any]],
) -> None:
    """v5.1: short leg must NOT sit AT the trigger level.

    LONG_DELTA breakout (e.g. trigger=close above 430):
        short_call_strike MUST be > trigger_level
    SHORT_DELTA downside break (e.g. trigger=close below 420):
        short_put_strike MUST be < trigger_level

    When a candidate row provides leg strikes, check directly. When the
    preferred is a strategy-family idea (no concrete legs), fall back to
    checking strike_role.target_level vs trigger_level — they must differ
    and point in the directional direction (target > trigger for LONG_DELTA,
    target < trigger for SHORT_DELTA).

    Skipped when structure=no_trade or bias=WAIT (no entry expression to
    validate), or when strike_role.trigger_level is blank (the lenient
    coercer left it empty because market_structure_levels didn't have a
    corresponding wall — typical of data_insufficient setups)."""
    pref = outcome.preferred_expression
    if pref is None or pref.structure == "no_trade":
        return
    bias = outcome.headline.directional_bias
    if bias == "WAIT":
        return
    trigger = _parse_decimal_loose(pref.strike_role.trigger_level)
    if trigger is None:
        # No trigger level → cannot enforce. Lenient stance: skip (the
        # missing field is already a separate gap).
        return

    side_right = "C" if bias == "LONG_DELTA" else "P"
    candidate = candidates.get(pref.idea_id)
    short_strike = _short_leg_strike(candidate, side_right)

    if short_strike is not None:
        if bias == "LONG_DELTA" and short_strike <= trigger:
            raise ValueError(
                f"trigger_strike_mismatch: LONG_DELTA breakout with trigger_level="
                f"{trigger} but short call strike={short_strike} <= trigger. The "
                f"short leg caps payoff at the activation level. Move both legs "
                f"up so the short leg sits at the next target."
            )
        if bias == "SHORT_DELTA" and short_strike >= trigger:
            raise ValueError(
                f"trigger_strike_mismatch: SHORT_DELTA break with trigger_level="
                f"{trigger} but short put strike={short_strike} >= trigger. The "
                f"short leg caps payoff at the activation level. Move both legs "
                f"down so the short leg sits at the next downside target."
            )
        return

    # Strategy-family path — verify target_level vs trigger_level.
    target = _parse_decimal_loose(pref.strike_role.target_level)
    if target is None:
        return
    if bias == "LONG_DELTA" and target <= trigger:
        raise ValueError(
            f"trigger_strike_mismatch: LONG_DELTA expression has target_level="
            f"{target} <= trigger_level={trigger}. Target must be above trigger."
        )
    if bias == "SHORT_DELTA" and target >= trigger:
        raise ValueError(
            f"trigger_strike_mismatch: SHORT_DELTA expression has target_level="
            f"{target} >= trigger_level={trigger}. Target must be below trigger."
        )


def _check_dte_band_consistency(
    outcome: TradeInsightAiOutcome,
    candidates: dict[str, dict[str, Any]],
) -> None:
    """v5.1: chosen entry-expiry DTE must fall inside the emitted dte_band.

    Bands: momentum=[14,30], standard=[31,44], trend=[45,75].

    The candidate row carries its own dte_band (tagged by the assembler
    via _first_leg_dte). When the preferred is a known candidate row,
    compare its dte_band against the emitted headline.dte_band — if they
    disagree, that's a v5 → v5.1 inconsistency (e.g. claude emits
    'momentum' but picks a 34-DTE candidate whose own dte_band is
    'standard').

    For strategy-family preferred (no candidate row), we can't check
    DTE directly — skip in that case."""
    pref = outcome.preferred_expression
    if pref is None or pref.structure == "no_trade":
        return
    emitted_band = outcome.headline.dte_band
    if emitted_band not in DTE_BAND_RANGES:
        # Pydantic Literal would have rejected this already, but guard.
        return
    candidate = candidates.get(pref.idea_id)
    if candidate is None:
        return  # strategy-family path — skip
    candidate_band = candidate.get("dte_band") or ""
    if not candidate_band:
        return  # candidate has no dte_band tag (back-compat) — skip
    if candidate_band != emitted_band:
        raise ValueError(
            f"dte_band_inconsistency: headline.dte_band={emitted_band!r} but the "
            f"selected candidate {pref.idea_id!r} is in band {candidate_band!r}. "
            f"Either pick a candidate inside the {emitted_band} range "
            f"({DTE_BAND_RANGES[emitted_band]}) or emit the band that matches."
        )


def _check_conditional_quote_validity(
    outcome: TradeInsightAiOutcome,
) -> None:
    """v5.1: CONDITIONAL setups must not present pre-trigger numerics as if
    they were post-trigger economics.

    The narrow failure mode this catches: status_observed='candidate'
    under entry_state=CONDITIONAL. 'candidate' means "ready to enter at
    these prices" — but the trigger has not fired, so the candidate-row
    economics WILL change when it does. The TSLA v5 Claude run hit this
    exact failure mode (status='candidate' with $2.35 entry, CONDITIONAL
    on a daily close above 430).

    Acceptable handlings under CONDITIONAL:
      - status='strategy_review'      — post-trigger research, no numerics
      - status='candidate_pre_trigger' — anticipatory pre-trigger entry
                                         (model explicitly argues for it)
      - status='needs_check' / 'blocked' — honest uncertainty preserved
                                           from the deterministic assembler

    Skipped when structure=no_trade, when entry_state != CONDITIONAL, or
    when preferred is None."""
    pref = outcome.preferred_expression
    if pref is None or pref.structure == "no_trade":
        return
    if outcome.headline.entry_state != "CONDITIONAL":
        return
    if pref.status_observed != "candidate":
        return
    raise ValueError(
        "conditional_quote_validity: entry_state=CONDITIONAL but "
        "preferred_expression.status_observed='candidate'. The candidate's "
        "max_profit/loss/entry are pre-trigger references — they will not "
        "survive the trigger fire. Set status to 'strategy_review' "
        "(post-trigger research, blank/annotated numerics) or "
        "'candidate_pre_trigger' (explicit anticipatory pre-trigger entry)."
    )


def _check_active_trigger_evidence(outcome: TradeInsightAiOutcome) -> None:
    """v5.2: entry_state=ACTIVE requires payload-proven trigger fire.

    Reads outcome.trigger_evidence.trigger_fired (computed deterministically
    by the lenient coercer from the latest completed daily close in
    tabs.market_structure.stock_history vs strike_role.trigger_level).
    If the model emitted ACTIVE but trigger_evidence says the trigger has
    not fired, REJECT.

    Skipped when no preferred / structure=no_trade / WAIT / NO_ENTRY:
    in those cases there's no breakout/breakdown to prove."""
    if outcome.preferred_expression is None:
        return
    if outcome.preferred_expression.structure == "no_trade":
        return
    if outcome.headline.entry_state != "ACTIVE":
        return
    if outcome.headline.directional_bias == "WAIT":
        return
    if outcome.trigger_evidence.trigger_fired:
        return
    raise ValueError(
        "active_trigger_evidence: entry_state=ACTIVE but "
        f"trigger_evidence.trigger_fired=False (latest completed close "
        f"{outcome.trigger_evidence.evidence_close} on "
        f"{outcome.trigger_evidence.evidence_close_date} did not satisfy "
        f"trigger {outcome.trigger_evidence.trigger_level}). Intraday spot "
        "is not sufficient. Set entry_state=CONDITIONAL until a completed "
        "daily close satisfies the trigger."
    )


def _check_anti_pin_cap_scope(outcome: TradeInsightAiOutcome) -> None:
    """v5.2: the anti-pin conviction cap applies ONLY when anti_pin.invoked
    =True.

    If invoked=False (default), a low score must NOT be cited as the
    reason conviction was capped. The cap_reason field should be empty
    or describe a non-anti-pin reason (e.g. flow/structure conflict).
    Reject when the model emitted invoked=False AND
    conviction_cap_applied=True with a cap_reason mentioning anti-pin.

    This closes the v5.1 NVDA Claude case where anti-pin scored 1/4 but
    Claude correctly chose downside_break — conviction should not have
    been capped on anti-pin grounds when anti-pin isn't the thesis."""
    ap = outcome.anti_pin
    if not ap.conviction_cap_applied:
        return
    if ap.invoked:
        return
    cap_reason_lower = (ap.cap_reason or "").lower()
    if "anti-pin" in cap_reason_lower or "anti_pin" in cap_reason_lower:
        raise ValueError(
            "anti_pin_cap_scope: anti_pin.invoked=False but "
            "conviction_cap_applied=True with cap_reason citing anti-pin. "
            "Anti-pin scoring is informational when not invoked as the "
            "thesis — do not use a low score as a conviction cap. Either "
            "set anti_pin.invoked=True (the wall-attack thesis is real), "
            "or rewrite cap_reason to cite the actual conflict."
        )


def _check_thesis_archetype_consistency(outcome: TradeInsightAiOutcome) -> None:
    """v5.2: thesis_archetype MUST agree with underlying_path.

    Mapping (HARD):
      resistance_rejection   ↔ bearish_rejection
      support_breakdown      ↔ downside_break
      breakout_continuation  ↔ bullish_continuation
      pin_no_trade           ↔ pinned_no_directional_entry
      data_insufficient      ↔ data_insufficient

    Closes the v5.1 NVDA disagreement where the spatial archetype and
    the directional label were chosen independently and could drift."""
    archetype = outcome.headline.thesis_archetype
    path = outcome.headline.underlying_path
    expected_pairs = {
        "resistance_rejection": "bearish_rejection",
        "support_breakdown": "downside_break",
        "breakout_continuation": "bullish_continuation",
        "pin_no_trade": "pinned_no_directional_entry",
        "data_insufficient": "data_insufficient",
    }
    expected_path = expected_pairs.get(archetype)
    if expected_path is None:
        return  # archetype already validated by Literal
    if path != expected_path:
        raise ValueError(
            f"thesis_archetype_inconsistency: archetype={archetype!r} but "
            f"underlying_path={path!r}; expected {expected_path!r}. The "
            "spatial archetype and directional label must agree."
        )


_TITLE_WORD_MIN = 10
_TITLE_WORD_MAX = 25  # allow slight overshoot; reviewer suggested 10-20


def _check_headline_title_length(
    outcome: TradeInsightAiOutcome, *, lenient: bool
) -> None:
    """v5.2: headline.title must be 10-25 words, NOT a page-title fragment.

    The v5.1 NVDA Codex run emitted 'NVDA AI Analysis' (3 words) which is
    the page title, not the trade thesis. Claude went the other extreme
    with 32 words. Enforce a band that matches the prompt's example.

    REJECT when title has fewer than 10 words or more than 25 words —
    BUT lenient mode (Claude's partial-output capture path) skips the
    check entirely because the coercer's fallback title is "{ticker} —
    partial output" (4 words) and lenient mode is designed to capture
    degraded output rather than reject it."""
    if lenient:
        return
    title = (outcome.headline.title or "").strip()
    if not title:
        raise ValueError("headline.title is empty")
    word_count = len(title.split())
    if word_count < _TITLE_WORD_MIN:
        raise ValueError(
            f"headline_title_too_short: title has {word_count} words "
            f"(min {_TITLE_WORD_MIN}). The title must name the directional "
            "bias + structure + trigger + DTE band. Page-title fragments "
            "like 'NVDA AI Analysis' are not acceptable."
        )
    if word_count > _TITLE_WORD_MAX:
        raise ValueError(
            f"headline_title_too_long: title has {word_count} words "
            f"(max {_TITLE_WORD_MAX})."
        )


def _parse_reward_risk(rr: str) -> Decimal | None:
    """Try several R:R formats: '1.5', '1.5:1', '2.75/2.25', '2.75 / 2.25'."""
    if not rr:
        return None
    s = rr.strip()
    if not s:
        return None
    # 'X:1' form
    if ":" in s:
        left = s.split(":", 1)[0].strip().lstrip("$")
        try:
            return Decimal(left)
        except Exception as exc:
            _ = repr(exc)
            return None
    # 'X/Y' form
    if "/" in s:
        parts = s.split("/", 1)
        try:
            top = Decimal(parts[0].strip().lstrip("$"))
            bot = Decimal(parts[1].strip().lstrip("$"))
            if bot == 0:
                return None
            return top / bot
        except Exception as exc:
            _ = repr(exc)
            return None
    # Bare number
    try:
        return Decimal(s.lstrip("$"))
    except Exception as exc:
        _ = repr(exc)
        return None


_MIN_RR_FOR_CONDITIONAL_C_OR_LOWER = Decimal("1.5")


def _check_min_rr_for_conditional_c(outcome: TradeInsightAiOutcome) -> None:
    """v5.2: minimum reward/risk floor for CONDITIONAL with conviction ≤ C.

    CONDITIONAL setups historically have lower hit rates than ACTIVE; thin
    R:R turns expected value negative. Require >= 1.5 when conviction is
    C/D/F and entry_state=CONDITIONAL.

    Skipped when:
      - no preferred / structure=no_trade
      - entry_state != CONDITIONAL
      - conviction in {A, B}
      - status_observed=strategy_review (numerics are 'Repriced post-trigger'
        placeholders, not real R:R)
      - reward_risk is unparseable (treat as soft missing data, not a hard
        reject — the prompt's R:R format is loose)"""
    pref = outcome.preferred_expression
    if pref is None or pref.structure == "no_trade":
        return
    if outcome.headline.entry_state != "CONDITIONAL":
        return
    if outcome.headline.conviction not in ("C", "D", "F"):
        return
    if pref.status_observed == "strategy_review":
        return  # post-trigger reprice placeholders — no R:R to check
    rr = _parse_reward_risk(pref.reward_risk)
    if rr is None:
        return  # unparseable — soft skip
    if rr < _MIN_RR_FOR_CONDITIONAL_C_OR_LOWER:
        raise ValueError(
            f"min_rr_for_conditional_c: reward_risk={rr} below the "
            f"{_MIN_RR_FOR_CONDITIONAL_C_OR_LOWER} floor for CONDITIONAL "
            f"with conviction={outcome.headline.conviction}. Thin R:R on a "
            "low-conviction conditional setup has negative expected value "
            "given hit-rate < 50%. Either choose a wider spread (push the "
            "short leg farther toward the target) or move to strategy_review."
        )


def _reject_imperative_text(outcome: TradeInsightAiOutcome) -> None:
    checked = [
        outcome.headline.stance_label,
        outcome.preferred_expression.title if outcome.preferred_expression else "",
        outcome.preferred_expression.subtitle if outcome.preferred_expression else "",
    ]
    for text in checked:
        lowered = text.strip().lower()
        if any(lowered.startswith(phrase) for phrase in _IMPERATIVE_PHRASES):
            raise ValueError(f"imperative trade instruction rejected: {text}")

    free_text = json.dumps(outcome.model_dump(mode="json"), default=str)
    for phrase in _IMPERATIVE_PHRASES:
        if re.search(rf"(^|[.!?]\s+){re.escape(phrase)}\b", free_text, re.I):
            raise ValueError(f"imperative trade instruction rejected: {phrase}")
    for pattern in _IMPERATIVE_PATTERNS:
        if pattern.search(free_text):
            raise ValueError("imperative trade instruction rejected")


def _drop_invalid_source_path_in_lenient(
    item: Any,
    deterministic_payload: dict[str, Any],
    outcome: TradeInsightAiOutcome,
    missing_data: list[str],
) -> None:
    """Lenient counterpart to `_validate_source_path_item`: instead of
    raising on an invalid `source_path`, canonicalize valid ones, and set
    invalid ones to None while recording the drop in `missing_data`."""
    source_path = getattr(item, "source_path", None)
    if not source_path:
        return
    lowered = source_path.lower()
    if "short_interest" in lowered and not _missing_data_mentions(
        outcome, "short_interest"
    ):
        item.source_path = None
        note = f"source_path dropped (unavailable): {source_path}"
        if note not in missing_data:
            missing_data.append(note)
        return
    canonical_source_path = _canonical_source_path(source_path, deterministic_payload)
    if canonical_source_path != source_path:
        item.source_path = canonical_source_path
        source_path = canonical_source_path
    if not _path_family_exists(source_path, deterministic_payload):
        item.source_path = None
        note = f"source_path dropped (unknown prefix): {source_path}"
        if note not in missing_data:
            missing_data.append(note)


def validate_trade_insights_ai_outcome(
    outcome: dict[str, Any] | TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    lenient: bool = False,
) -> TradeInsightAiOutcome:
    """Validate model output against immutable deterministic inputs.

    `lenient=True` (Claude only — see issue #67) pre-processes the raw dict
    through `_coerce_claude_outcome_dict` to capture partial/off-schema output,
    then RELAXES only the equality checks that require provider-internal
    consistency:

    * unknown idea_ids in best_expressions / rejected_ideas / preferred /
      conflicts are accepted (lenient capture);
    * source_path validation drops invalid paths to None instead of raising.

    Safety / integrity checks STILL RUN in lenient mode:

    * undefined-risk strategy family (e.g. `short_strangle`) rejection —
      enforces the no-naked-shorts project rule even for Claude;
    * strategy-family status_observed/risk_flags equality (the coercer
      synthesizes the canonical values, so this passes automatically);
    * known-candidate status_observed/risk_flags equality (the coercer
      overwrites these from the deterministic candidate so this passes);
    * guardrails all-true (an explicit False from Claude is rejected);
    * imperative-text rejection (safety guardrail on free text).

    NOTE: A pre-validated TradeInsightAiOutcome instance bypasses the
    coercion step. Production callers always pass dicts from the runner.
    """

    # Function-local import: lenient module depends on this package's constants,
    # so a module-level import here would deadlock at first-load. Deferring keeps
    # the dependency edge runtime-only and matches the pre-split single-file
    # behavior (which late-imported the same symbol at the bottom of the module).
    from uw_scan.reports.trade_insights_ai_lenient import _coerce_claude_outcome_dict

    expected_hash = hash_trade_insights_ai_analysis_input(deterministic_payload)
    if lenient and not isinstance(outcome, TradeInsightAiOutcome):
        outcome = _coerce_claude_outcome_dict(
            outcome,
            deterministic_payload,
            produced_at=produced_at,
            expected_analysis_input_hash=expected_hash,
        )

    parsed = (
        outcome
        if isinstance(outcome, TradeInsightAiOutcome)
        else TradeInsightAiOutcome.model_validate(outcome)
    )
    expected_produced_at = _iso_z(produced_at)
    if _iso_z(parsed.analysis_produced_at) != expected_produced_at:
        raise ValueError(
            "analysis_produced_at does not match worker-produced timestamp"
        )
    if parsed.schema_version != PROMPT_VERSION:
        raise ValueError("schema_version does not match prompt version")
    if parsed.headline.conviction not in FINAL_RATING_VALUES:
        raise ValueError("final rating must be one of A, B, C, D, or F")
    if parsed.ticker != deterministic_payload.get("ticker"):
        raise ValueError("ticker does not match deterministic payload")
    if parsed.snapshot.run_id != deterministic_payload.get("run_id"):
        raise ValueError("snapshot.run_id does not match deterministic payload")
    if parsed.snapshot.trade_insights_input_hash != deterministic_payload.get(
        "trade_insights_input_hash"
    ):
        raise ValueError(
            "trade_insights_input_hash does not match deterministic payload"
        )
    if parsed.snapshot.analysis_input_hash != expected_hash:
        raise ValueError("analysis_input_hash does not match deterministic payload")

    candidates = _candidate_map(deterministic_payload)

    # Strict-only: unknown idea_ids in best_expressions / rejected_ideas /
    # preferred_expression / conflicts are rejected outright. The lenient
    # coercer accepts them so Claude's incoherence is captured visibly.
    if not lenient:
        for item in [*parsed.best_expressions, *parsed.rejected_ideas]:
            if not _known_idea_id(item.idea_id, candidates):
                raise ValueError(f"unknown idea_id referenced: {item.idea_id}")
        if parsed.preferred_expression is not None and not _known_idea_id(
            parsed.preferred_expression.idea_id, candidates
        ):
            raise ValueError(
                f"unknown idea_id referenced: {parsed.preferred_expression.idea_id}"
            )
        for conflict in parsed.conflicts:
            for idea_id in conflict.affected_idea_ids:
                if not _known_idea_id(idea_id, candidates):
                    raise ValueError(f"unknown idea_id referenced: {idea_id}")

    # ALWAYS (both strict and lenient): safety checks for strategy-family
    # ids (undefined-risk rejection, status_observed/risk_flags discipline)
    # and known-candidate status/risk_flags equality. The lenient coercer
    # synthesizes the canonical values so these pass cleanly for Claude.
    echo_items = list(parsed.best_expressions)
    if parsed.preferred_expression is not None:
        echo_items.append(parsed.preferred_expression)
    for item in echo_items:
        if item.idea_id in STRATEGY_FAMILY_IDS:
            if item.idea_id not in PREFERRED_STRATEGY_FAMILY_IDS:
                raise ValueError(
                    f"undefined-risk strategy family cannot be preferred: {item.idea_id}"
                )
            if item.status_observed != "strategy_review":
                raise ValueError(
                    f"strategy status_observed must be strategy_review for {item.idea_id}"
                )
            if item.risk_flags_observed != []:
                raise ValueError(
                    f"strategy risk_flags_observed must be empty for {item.idea_id}"
                )
            continue
        if item.idea_id in candidates:
            candidate = candidates[item.idea_id]
            # v5.1: under entry_state=CONDITIONAL the model may escalate a
            # candidate's status to 'candidate_pre_trigger' (the anticipatory
            # pre-trigger entry handling). All other status mutations remain
            # rejected to preserve the no-whitewashing rule. The check still
            # applies to best_expressions (which don't carry entry_state),
            # so the escalation is allowed only for preferred_expression.
            is_pretrigger_escalation = (
                item is parsed.preferred_expression
                and parsed.headline.entry_state == "CONDITIONAL"
                and item.status_observed == "candidate_pre_trigger"
                and candidate.get("status") == "candidate"
            )
            if (
                item.status_observed != candidate.get("status")
                and not is_pretrigger_escalation
            ):
                raise ValueError(f"status_observed changed for idea_id {item.idea_id}")
            if item.risk_flags_observed != list(candidate.get("risk_flags") or []):
                raise ValueError(
                    f"risk_flags_observed changed for idea_id {item.idea_id}"
                )

    # ALWAYS: guardrails truthiness — an explicit False from Claude must
    # not contradict the persisted "succeeded" status.
    if not (
        parsed.guardrails.statuses_preserved
        and parsed.guardrails.risk_flags_preserved
        and parsed.guardrails.no_executable_recommendations
    ):
        raise ValueError("guardrails must all be true")

    # ALWAYS: v5 mode-structure + delta-match consistency. These are the
    # core directional-swing invariants — picking a vol-seller for a
    # directional swing is the failure mode v5 exists to eliminate, so we
    # enforce in BOTH strict and lenient modes. The lenient coercer can
    # attempt to normalize obvious mismatches, but any residual violation
    # must surface as an error rather than be silently captured (mirrors
    # the undefined-risk strategy-family check above).
    _check_mode_structure_consistency(parsed)
    _check_delta_match(parsed)
    # v5.1 additions: trigger/strike consistency, DTE band consistency,
    # conditional quote validity. Enforced in BOTH strict and lenient modes
    # because they encode the core directional-correctness invariants the
    # v5.1 reviewers (chatgpt + claude) flagged as v5 failure modes.
    _check_trigger_strike_consistency(parsed, candidates)
    _check_dte_band_consistency(parsed, candidates)
    _check_conditional_quote_validity(parsed)
    # v5.2 additions: enforced in BOTH strict and lenient modes.
    _check_active_trigger_evidence(parsed)
    _check_anti_pin_cap_scope(parsed)
    _check_thesis_archetype_consistency(parsed)
    _check_headline_title_length(parsed, lenient=lenient)
    _check_min_rr_for_conditional_c(parsed)

    # Strict: source_path validation raises on invalid prefixes.
    # Lenient: invalid prefixes are dropped to None with a missing_data note.
    if not lenient:
        for card in parsed.metric_cards:
            _validate_source_path_item(card, deterministic_payload, parsed)
        for section in (
            parsed.section_cards.market_structure,
            parsed.section_cards.volatility,
            parsed.section_cards.flow_positioning,
        ):
            for highlight in section.highlights:
                _validate_source_path_item(highlight, deterministic_payload, parsed)
            for level in section.levels:
                _validate_source_path_item(level, deterministic_payload, parsed)
    else:
        missing_data = list(parsed.missing_data)
        for card in parsed.metric_cards:
            _drop_invalid_source_path_in_lenient(
                card, deterministic_payload, parsed, missing_data
            )
        for section in (
            parsed.section_cards.market_structure,
            parsed.section_cards.volatility,
            parsed.section_cards.flow_positioning,
        ):
            for highlight in section.highlights:
                _drop_invalid_source_path_in_lenient(
                    highlight, deterministic_payload, parsed, missing_data
                )
            for level in section.levels:
                _drop_invalid_source_path_in_lenient(
                    level, deterministic_payload, parsed, missing_data
                )
        # Persist any new notes back onto the parsed outcome
        if len(missing_data) != len(parsed.missing_data):
            parsed.missing_data = missing_data

    _reject_imperative_text(parsed)
    return parsed
