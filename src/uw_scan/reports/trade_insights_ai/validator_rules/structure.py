"""Structure, delta, DTE, and quote consistency rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from uw_scan.models import TradeInsightAiOutcome
from uw_scan.reports.trade_insights_ai.prompt_text import (
    DIRECTIONAL_SWING_STRUCTURES,
    DTE_BAND_RANGES,
    RANGE_INCOME_STRUCTURES,
)

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

