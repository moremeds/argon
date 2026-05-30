"""Trigger, leg, reward-risk, and entry-state rules."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import TradeInsightAiOutcome

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


# ---------------------------------------------------------------------------
# v5.3 HARD validators: legs-strategy match, mechanical ENTRY_STATE,
# legs-align-with-triggers. All three enforced in both strict and lenient
# modes — they encode the core "trigger components ARE the state machine"
# invariant that v5.3 promises.
# ---------------------------------------------------------------------------

# Structures whose legs[] geometry is fully specified by the validator.
# Other structures (diagonal, butterfly, iron_condor) have looser geometry
# rules that v5.3-minimal does not enforce — those checks are deferred to a
# follow-up so this milestone stays bounded.
_LEG_SPEC_TWO_LEG_DEBIT = {
    "bear_put_spread": ("put", "long_above_short"),
    "put_debit_spread": ("put", "long_above_short"),
    "bull_call_spread": ("call", "long_below_short"),
    "call_debit_spread": ("call", "long_below_short"),
}
_LEG_SPEC_TWO_LEG_CREDIT = {
    "put_credit_spread": ("put", "short_above_long"),
    "call_credit_spread": ("call", "short_below_long"),
}
_LEG_SPEC_ONE_LEG = {
    "long_call": "call",
    "long_put": "put",
}


def _check_legs_match_strategy(outcome: TradeInsightAiOutcome) -> None:
    """v5.3: enforce per-structure legs[] geometry.

    The legs-strategy-match check binds the proposed structure label to
    actual leg geometry: bear_put_spread must be two puts long-above-short
    on the same expiry, credit spreads must include the protective long
    leg (no-naked-shorts), and so on. Lifts the v5.2 gap where
    `structure="bear_put_spread"` was a free-text claim with no
    falsifiable composition behind it.

    Skipped for status_observed='strategy_review', structure='no_trade',
    and legs=[] (these are legitimate "research-only" outputs).
    """
    pref = outcome.preferred_expression
    if pref is None:
        return
    structure = (pref.structure or "").lower()
    if structure in ("", "no_trade"):
        return
    if pref.status_observed == "strategy_review":
        return
    legs = pref.legs
    if not legs:
        # Structured family declared but no legs — only enforce when the
        # structure is one we have a spec for. Otherwise let it pass for
        # diagonal / butterfly / iron_condor / calendar (out of v5.3 scope).
        if (
            structure in _LEG_SPEC_TWO_LEG_DEBIT
            or structure in _LEG_SPEC_TWO_LEG_CREDIT
            or structure in _LEG_SPEC_ONE_LEG
        ):
            raise ValueError(
                f"legs_match_strategy: structure={structure!r} requires "
                "explicit legs[] (v5.3). Emit the leg array, or set "
                "status_observed='strategy_review' if the spread is research-only."
            )
        return

    # One-leg structures
    if structure in _LEG_SPEC_ONE_LEG:
        expected_type = _LEG_SPEC_ONE_LEG[structure]
        if len(legs) != 1:
            raise ValueError(
                f"legs_match_strategy: {structure} requires exactly 1 leg, got {len(legs)}"
            )
        leg = legs[0]
        if leg.option_type != expected_type:
            raise ValueError(
                f"legs_match_strategy: {structure} leg option_type must be "
                f"{expected_type!r}, got {leg.option_type!r}"
            )
        if leg.side != "long":
            raise ValueError(
                f"legs_match_strategy: {structure} leg must be long, got {leg.side!r}"
            )
        return

    # Two-leg debit + credit structures
    spec = _LEG_SPEC_TWO_LEG_DEBIT.get(structure) or _LEG_SPEC_TWO_LEG_CREDIT.get(
        structure
    )
    if spec is None:
        # Out-of-spec structure (diagonal, butterfly, etc.) — pass through.
        return
    expected_type, ordering = spec
    if len(legs) != 2:
        raise ValueError(
            f"legs_match_strategy: {structure} requires exactly 2 legs, got {len(legs)}"
        )
    for leg in legs:
        if leg.option_type != expected_type:
            raise ValueError(
                f"legs_match_strategy: {structure} legs must be "
                f"option_type={expected_type!r}, got {leg.option_type!r}"
            )
    if legs[0].expiry != legs[1].expiry:
        raise ValueError(
            f"legs_match_strategy: {structure} both legs must share the same "
            f"expiry, got {legs[0].expiry} and {legs[1].expiry}"
        )
    longs = [leg for leg in legs if leg.side == "long"]
    shorts = [leg for leg in legs if leg.side == "short"]
    if len(longs) != 1 or len(shorts) != 1:
        # No-naked-shorts: every defined-risk family MUST have exactly one
        # long protective leg + one short leg.
        raise ValueError(
            f"legs_match_strategy: {structure} requires exactly 1 long + 1 short "
            f"leg (defined-risk; no naked shorts), got {len(longs)} long / "
            f"{len(shorts)} short"
        )
    long_strike = longs[0].strike
    short_strike = shorts[0].strike
    if ordering == "long_above_short" and not (long_strike > short_strike):
        raise ValueError(
            f"legs_match_strategy: {structure}: long_strike ({long_strike}) "
            f"must be > short_strike ({short_strike})"
        )
    if ordering == "long_below_short" and not (long_strike < short_strike):
        raise ValueError(
            f"legs_match_strategy: {structure}: long_strike ({long_strike}) "
            f"must be < short_strike ({short_strike})"
        )
    if ordering == "short_above_long" and not (short_strike > long_strike):
        raise ValueError(
            f"legs_match_strategy: {structure}: short_strike ({short_strike}) "
            f"must be > long_strike ({long_strike}) for a defined-risk credit spread"
        )
    if ordering == "short_below_long" and not (short_strike < long_strike):
        raise ValueError(
            f"legs_match_strategy: {structure}: short_strike ({short_strike}) "
            f"must be < long_strike ({long_strike}) for a defined-risk credit spread"
        )


_LEGS_TRIGGER_TOLERANCE = Decimal("0.02")  # 2%


def _check_legs_align_with_triggers(outcome: TradeInsightAiOutcome) -> None:
    """v5.3: long-leg strike must be within 2% of a trigger component.

    Binds the proposed spread back to the trigger state machine. Without
    this, the spread is free-text geometry — the model can claim
    bear_put_spread 215/210 while ALSO claiming trigger_level=220 with no
    enforceable relationship between the two (the v5.2 NVDA gap).

    Skipped when:
      - no preferred / structure='no_trade' / strategy_review (legs may
        be hypothetical research geometry)
      - no triggers populated (data_insufficient case)
      - no long leg (caught by legs_match_strategy)
    """
    pref = outcome.preferred_expression
    if pref is None:
        return
    if (pref.structure or "").lower() in ("", "no_trade"):
        return
    if pref.status_observed == "strategy_review":
        return
    if not pref.legs:
        return
    longs = [leg for leg in pref.legs if leg.side == "long"]
    if not longs:
        return  # legs_match_strategy will catch this case
    long_strike = longs[0].strike
    if long_strike is None:
        return

    levels: list[tuple[str, Decimal]] = []
    if outcome.entry_trigger.level is not None:
        levels.append(("entry_trigger", outcome.entry_trigger.level))
    if outcome.thesis_trigger.level is not None:
        levels.append(("thesis_trigger", outcome.thesis_trigger.level))
    if not levels:
        return  # no triggers to validate against

    for _, level in levels:
        if level == 0:
            continue
        pct_diff = abs(long_strike - level) / level
        if pct_diff <= _LEGS_TRIGGER_TOLERANCE:
            return  # aligned with at least one trigger

    formatted = ", ".join(f"{name}={level}" for name, level in levels)
    raise ValueError(
        f"legs_align_with_triggers: long_leg_strike={long_strike} is not "
        f"within 2% of any trigger component ({formatted}). Either re-pick "
        "the spread to align with the trigger state machine, or revise the "
        "trigger components to reflect the actual entry plan."
    )


def _check_entry_state_derivation(outcome: TradeInsightAiOutcome) -> None:
    """v5.3: ENTRY_STATE is mechanical, not a model judgment.

    Truth table (from STEP 3 of the v5.3 prompt):

      thesis.fired AND entry.fired AND NOT invalidation.fired  → ACTIVE
      thesis.fired AND NOT entry.fired AND NOT invalidation.fired → CONDITIONAL
      NOT thesis.fired AND NOT invalidation.fired              → CONDITIONAL or NO_ENTRY
                                                                 (judgment between
                                                                  data-quality vs.
                                                                  opportunity-quality)
      invalidation.fired                                       → NO_ENTRY

    Strict enforcement:
      - entry_state=ACTIVE without (thesis.fired AND entry.fired) is rejected
      - entry_state=ACTIVE with invalidation.fired is rejected
      - entry_state=CONDITIONAL with invalidation.fired is rejected

    The CONDITIONAL/NO_ENTRY split when no triggers have fired is left to
    the model — both are defensible depending on whether the missing
    triggers reflect a setup still developing or a setup whose primary
    evidence is absent.

    Skipped when directional_bias=WAIT (entry_state should be NO_ENTRY by
    Step 2 of the decision order, but that's caught by mode-structure
    consistency).
    """
    state = outcome.headline.entry_state
    if outcome.headline.directional_bias == "WAIT":
        return

    thesis_fired = outcome.thesis_trigger.fired
    entry_fired = outcome.entry_trigger.fired
    invalidation_fired = outcome.invalidation.fired

    if state == "ACTIVE":
        if invalidation_fired:
            raise ValueError(
                "entry_state_derivation: ACTIVE rejected — invalidation.fired=true "
                "means the thesis is invalidated. Set entry_state=NO_ENTRY and "
                "describe the invalidation in primary_risk."
            )
        if not (thesis_fired and entry_fired):
            raise ValueError(
                f"entry_state_derivation: ACTIVE requires BOTH "
                f"thesis_trigger.fired AND entry_trigger.fired (got "
                f"thesis_fired={thesis_fired}, entry_fired={entry_fired}). "
                "When only thesis has fired, use CONDITIONAL with the "
                "unfired entry_trigger as the watch level. v5.3 ENTRY_STATE "
                "is mechanical — it must match the trigger booleans."
            )
        return

    if state == "CONDITIONAL" and invalidation_fired:
        raise ValueError(
            "entry_state_derivation: CONDITIONAL rejected — invalidation.fired=true "
            "means the thesis is invalidated. Set entry_state=NO_ENTRY."
        )
