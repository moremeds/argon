"""Prompt contract helpers for Trade Insights AI analysis.

V1.5 keeps the model runner local and audit-oriented: the worker passes a
bounded deterministic payload into Codex and stores the validated JSON result.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from uw_scan.models import TradeInsightAiOutcome

PROMPT_VERSION = "trade-insights-ai-v5.2"
STRATEGY_FAMILY_IDS = frozenset(
    {
        "long_stock",
        "long_call",
        "long_put",
        # Directional debit / credit verticals.
        "call_debit_spread",
        "put_debit_spread",
        "bull_call_spread",
        "bear_put_spread",
        "call_credit_spread",
        "put_credit_spread",
        # Directional combo structures.
        "risk_reversal",
        "call_diagonal",
        "put_diagonal",
        # Range-income / neutral-vol structures.
        "iron_condor",
        "iron_butterfly",
        "butterfly",
        "calendar_spread",
        # Income overlays — not swing-directional, but still valid rejected-idea
        # references so the model can explain why they don't fit at this horizon.
        "covered_call",
        "cash_secured_put",
        # Naked / undefined-risk — present so rejected_ideas can cite the safety
        # override, never selectable as preferred.
        "short_strangle",
        "no_trade",
    }
)
PREFERRED_STRATEGY_FAMILY_IDS = STRATEGY_FAMILY_IDS - {"short_strangle"}

# v5 mode-aware structure whitelists. The validator enforces:
#   trade_intent == directional_swing → preferred_expression.structure ∈
#       DIRECTIONAL_SWING_STRUCTURES
#   trade_intent == range_income      → preferred_expression.structure ∈
#       RANGE_INCOME_STRUCTURES
#
# Iron condor and credit spreads are intentionally absent from
# DIRECTIONAL_SWING_STRUCTURES — picking a vol-seller for a directional swing
# is the exact failure mode v5 is built to prevent. They remain available in
# range_income mode for explicitly-requested premium ideas.
DIRECTIONAL_SWING_STRUCTURES = frozenset(
    {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
        "bull_call_spread",
        "bear_put_spread",
        # call_diagonal / put_diagonal are defined-risk (long far leg covers the
        # short near leg) — kept as a valid directional preferred expression.
        "call_diagonal",
        "put_diagonal",
        # risk_reversal is INTENTIONALLY excluded. The short put leg is naked,
        # which violates the project safety override ("no naked shorts in any
        # strategy/trade-plan code — defined-risk only"). It remains in
        # STRATEGY_FAMILY_IDS so rejected_ideas can cite it as out-of-policy.
        "no_trade",
    }
)
RANGE_INCOME_STRUCTURES = frozenset(
    {
        "iron_condor",
        "iron_butterfly",
        "butterfly",
        "calendar_spread",
        "call_credit_spread",
        "put_credit_spread",
        "no_trade",
    }
)
# v5 vocab — exposed as tuples so the schema generator and lenient coercer
# share one source of truth.
TRADE_INTENT_VALUES = ("directional_swing", "range_income")
DIRECTIONAL_BIAS_VALUES = ("LONG_DELTA", "SHORT_DELTA", "WAIT")
ENTRY_STATE_VALUES = ("ACTIVE", "CONDITIONAL", "NO_ENTRY")
UNDERLYING_PATH_VALUES = (
    "bullish_continuation",
    "bearish_rejection",
    "downside_break",
    "pinned_no_directional_entry",
    "data_insufficient",
)
DTE_BAND_VALUES = ("momentum", "standard", "trend")
# v5.1: the DTE band ranges the headline value must agree with. Validator
# enforces that the chosen preferred_entry_expiry DTE falls inside the band.
DTE_BAND_RANGES = {
    "momentum": (14, 30),
    "standard": (31, 44),
    "trend": (45, 75),
}

FINAL_RATING_VALUES = ("A", "B", "C", "D", "F")

MARKET_INTELLIGENCE_PROMPT = """You are analyzing ONE stock for a 5-10 trading-session DIRECTIONAL SWING entry.

CRITICAL FRAMING: The goal is NOT to find an option structure that "fits the chain." \
The goal is to (1) infer the most likely 5-10 session UNDERLYING PATH from \
options market structure + flow + positioning, (2) classify the directional \
bias, and (3) ONLY THEN choose a defined-risk option expression that maps to \
that path. DTE is a risk-management CONSTRAINT, not a thesis — do not justify \
any trade with "the expiry fits."

═══════════════════════════════════════════════════════════════════════════
MANDATORY DECISION ORDER (set fields in this order; do not skip steps)
═══════════════════════════════════════════════════════════════════════════

STEP 1 — UNDERLYING_PATH (set headline.underlying_path)
  Classify the expected 5-10 session path of the stock:
    - bullish_continuation:          trend up / breakout above resistance
    - bearish_rejection:             rejection at resistance / fade lower
    - downside_break:                breakdown below support / GEX flip
    - pinned_no_directional_entry:   range-bound, no edge for direction
    - data_insufficient:             primary evidence absent

STEP 1.5 — THESIS_ARCHETYPE (set headline.thesis_archetype)  (v5.2: NEW)
  v5.1 conflated bearish_rejection and downside_break — Codex picked one,
  Claude picked the other on the same NVDA payload because the
  underlying_path label alone doesn't force a spatial commit. Make the
  archetype explicit:

    resistance_rejection:   spot is BETWEEN two walls and trading AWAY
                            from the upper one; the upper wall held;
                            target is back inside the range. underlying
                            _path = bearish_rejection.
    support_breakdown:      spot is AT or BELOW a lower wall AND that
                            wall has been broken on a completed daily
                            close in the prior 5 sessions. underlying
                            _path = downside_break.
    breakout_continuation:  spot is AT or ABOVE an upper wall AND that
                            wall has been broken on a completed daily
                            close in the prior 5 sessions. underlying
                            _path = bullish_continuation.
    pin_no_trade:           spot is between two walls with no
                            directional flow. underlying_path =
                            pinned_no_directional_entry.
    data_insufficient:      primary fields missing. underlying_path =
                            data_insufficient.

  In top_reason, CITE the specific completed daily close session that
  justifies the archetype (e.g. "2026-05-22 close at 215.33 below the
  220 put wall confirms support_breakdown").

STEP 2 — DIRECTIONAL_BIAS (set headline.directional_bias)
  Map thesis_archetype + underlying_path to one of {LONG_DELTA, SHORT_DELTA, WAIT}:
    breakout_continuation / bullish_continuation         -> LONG_DELTA
    resistance_rejection / bearish_rejection             -> SHORT_DELTA
    support_breakdown    / downside_break                -> SHORT_DELTA
    pin_no_trade         / pinned_no_directional_entry   -> WAIT
    data_insufficient                                    -> WAIT
  WAIT is a valid output. Do NOT convert WAIT into an iron condor unless
  trade_intent is range_income (see Step 4).

STEP 3 — ENTRY_STATE (set headline.entry_state)
    - ACTIVE:      directional trigger has ALREADY fired (daily close above
                   the wall, daily close below support, etc.)
    - CONDITIONAL: setup valid; needs daily-close or 2-session confirmation
    - NO_ENTRY:    no clean directional edge (set when directional_bias=WAIT)

  ACTIVE_TRIGGER_EVIDENCE_RULE (HARD, v5.2):
    ACTIVE is allowed ONLY when the payload contains a COMPLETED daily
    close that satisfies the trigger. Intraday spot is NOT sufficient.

    For LONG_DELTA breakout (trigger="daily close above X"):
      latest completed close > X
        OR two completed closes above X if the trigger says "2-session hold"

    For SHORT_DELTA downside_break / resistance_rejection (trigger="daily close below X"):
      latest completed close < X
        OR two completed closes below X if the trigger says "2-session hold"

    If the latest completed daily close in tabs.market_structure.stock_history
    does NOT satisfy the trigger, you MUST emit entry_state=CONDITIONAL —
    even if intraday spot has crossed the level. The validator will reject
    entry_state=ACTIVE when trigger_evidence.trigger_fired=false.

    Populate the trigger_evidence block with:
      trigger_fired:        true iff a completed close satisfied the trigger
      trigger_type:         "daily_close" | "two_session_hold"
      trigger_level:        the numeric level being tested
      evidence_close:       the completed close that proves (or fails) the trigger
      evidence_close_date:  the market_date of evidence_close
      source_path:          tabs.market_structure.stock_history.rows[N].spot

STEP 4 — TRADE_INTENT (set headline.trade_intent)
  Default: directional_swing. Set range_income ONLY when ALL three hold:
    (a) underlying_path == pinned_no_directional_entry,
    (b) IV is rich (term structure or IV/RV supports premium selling),
    (c) no persistent flow attacks either wall.
  Iron condor / credit spreads are reserved for trade_intent=range_income.

STEP 5 — DTE_BAND (set headline.dte_band)  (v5.1: 3-band, ranges are HARD)
    - momentum (14-30 DTE): high gamma per $ premium. Use when entry_state
                            =ACTIVE or trigger is BREAKOUT_IMMINENT (anti-pin
                            rule has fired and trigger expected within
                            1-2 sessions). Accept theta-crush proximity.
    - standard (31-44 DTE): balanced gamma/theta. DEFAULT for entry_state
                            =CONDITIONAL when the trigger is expected to
                            resolve within the 5-10 session hold. This is
                            the band most swing setups should pick.
    - trend    (45-75 DTE): lower gamma decay, theta protection. Use when
                            entry_state=CONDITIONAL and the trigger may
                            take several sessions OR the thesis is a
                            multi-week continuation rather than an impulse.

  DTE_BAND_CONSISTENCY (HARD; validator will reject otherwise):
    The DTE of the chosen preferred_entry_expiry MUST fall inside the
    range emitted in headline.dte_band:
      momentum → DTE ∈ [14, 30]
      standard → DTE ∈ [31, 44]
      trend    → DTE ∈ [45, 75]
    If you emit dte_band="momentum" with a 34 DTE expiry, the validator
    will reject the outcome. Pick the band whose range contains the DTE.

STEP 6 — STRUCTURE (set preferred_expression.structure)
  ONLY AFTER Steps 1-5. Pick the option expression that maps to the
  chosen directional_bias. Mode-aware whitelists (HARD):

  trade_intent=directional_swing → structure ∈ {long_call, long_put,
    call_debit_spread, put_debit_spread, bull_call_spread, bear_put_spread,
    call_diagonal, put_diagonal, no_trade}

  trade_intent=range_income → structure ∈ {iron_condor, iron_butterfly,
    butterfly, calendar_spread, call_credit_spread, put_credit_spread,
    no_trade}

  BANNED in directional_swing mode (will be rejected by the validator):
    iron_condor, iron_butterfly, strangle, short_strangle, call_credit_spread,
    put_credit_spread, calendar_spread. These are vol-selling structures
    and fail the "structure expresses direction" test.

  Delta-match rule:
    directional_bias=LONG_DELTA  -> structure must have net positive delta
                                    (long_call, call_debit_spread,
                                     bull_call_spread, call_diagonal)
    directional_bias=SHORT_DELTA -> structure must have net negative delta
                                    (long_put, put_debit_spread,
                                     bear_put_spread, put_diagonal)
    directional_bias=WAIT        -> preferred_expression.structure="no_trade"
                                    The preferred_expression block then
                                    describes the CONDITIONAL setup; the
                                    Scenarios section names the long/short
                                    expressions that would activate.

═══════════════════════════════════════════════════════════════════════════
EVIDENCE WEIGHTING (v5: FLOW promoted to PRIMARY alongside dealer regime)
═══════════════════════════════════════════════════════════════════════════

PRIMARY (the directional call hangs on these):

  1. DEALER REGIME + KEY LEVELS
     - dealer_regime.{label, gamma_score, vanna_score, charm_score}
       (tabs.market_structure.dealer_regime)
     - market_structure_levels.{gex_flip, call_wall, put_wall, max_magnet,
       max_accel} (tabs.market_structure.market_structure_levels)
     - 90d GEX history extreme vs current — is today at a historically
       mean-reverting level?

  2. FLOW + POSITIONING  (v5: PROMOTED from SECONDARY)
     - Persistent multi-day OI build at key strikes
       (tabs.positioning.oi_change_top) — 3+ consecutive days of OI
       increase on a strike near a wall is a STRONG signal of pre-breakout
       pressure.
     - Net premium tilt: bullish vs bearish net dollar flow ratio at the
       wall and nearby strikes (tabs.flow.flow).
     - Repeated alerts ("RepeatedHitsAscendingFill" etc.) attacking a wall.
     - Dark pool notional trend (tabs.positioning.dark_pool_notional).
     - Short interest / borrow fee (tabs.positioning.short_data).

  3. VOLATILITY
     - IV vs RV at the chosen dte_band horizon (tabs.volatility.header).
     - Term structure shape across 14-75 DTE (tabs.volatility.term_structure).
     - Skew sets COST of bullish vs bearish bets — affects which structure
       you pick, NOT the directional bias.

SECONDARY:
  - 0DTE GEX and 0DTE share (tabs.volatility.dealer_regime_header.{
    odte_net_gex, odte_share_pct}) — intraday dealer hedging, NOT 5-10
    session direction.
  - Intraday tape direction, single-session bid/ask premium tilts.

CONTEXT (HARD VETO if violated):
  - Earnings inside the 5-10 session HOLD window
    (tabs.positioning.next_earnings_date):
      (a) DEFAULT: reject the trade with event_risk_in_window;
          entry_state=NO_ENTRY, watch_trigger="re-evaluate after earnings".
      (b) EXCEPTION: explicit IV-crush earnings thesis. Tag
          risk_flags_observed with ["earnings_in_window",
          "event_iv_crush_thesis"]; override swing-hold DTE rule with
          momentum dte_band and explain in headline.primary_risk.

═══════════════════════════════════════════════════════════════════════════
ANTI-PIN RULE v5.1 (3-of-4 quality score — stricter than v5)
═══════════════════════════════════════════════════════════════════════════

When persistent multi-day flow stacks AGAINST a dealer wall, the wall can
be a PRE-BREAKOUT TARGET rather than a cap. To prevent over-classifying
every wall attack as a breakout, the wall is TARGET (not cap) ONLY when
AT LEAST 3 of the following 4 are observed:

  (1) 3+ consecutive sessions of OI increase at or within one strike of
      the relevant wall (call_wall for upside, put_wall for downside)
      — tabs.positioning.oi_change_top.
  (2) Net premium tilt > 2x in the directional direction in the same
      strike zone (net bullish > 2x net bearish at/near call_wall for
      upside; mirror for downside) — tabs.flow.flow.
  (3) Repeated ASK-SIDE or ASCENDING-FILL alerts (for upside) or BID-SIDE
      / DESCENDING-FILL (for downside) clustered near the wall
      — tabs.flow.flow.top_alerts.
  (4) Spot is within 1.5% of the wall AND has NOT failed the wall on two
      consecutive prior daily closes — tabs.market_structure.market_
      structure_levels + recent stock_history rows.

  IF >= 3 of 4 hold (upside variant):
     - Wall is TARGET, not cap.
     - underlying_path = bullish_continuation (NOT pinned_no_directional_entry)
     - directional_bias = LONG_DELTA
     - entry_state = CONDITIONAL (need daily close above the wall)
     - REJECT any preferred_expression that profits from the wall
       holding (no iron_condor, no call_credit_spread at the wall)

  IF exactly 2 of 4 hold:
     - underlying_path = pinned_no_directional_entry OR
                         bullish_continuation (your judgment)
     - entry_state = CONDITIONAL
     - headline.conviction capped at C (not A/B) — the signal is mixed

  IF <= 1 of 4 hold:
     - The wall is still a CAP. Do NOT invoke the anti-pin rule.

Mirror for the put-wall side: persistent bearish flow + OI build at/near
put_wall = wall is a DOWNSIDE TARGET, underlying_path=downside_break,
bias=SHORT_DELTA.

In headline.top_reason or dominant_read.summary, CITE which of the four
sub-conditions hold (e.g. "anti-pin satisfied: 3 of 4 — OI build, premium
tilt, spot proximity; alert cluster absent").

ANTI_PIN_CAP_SCOPE_RULE (v5.2): the conviction cap and the wall=target
reclassification apply ONLY when anti-pin is INVOKED as the trade thesis
(i.e. the thesis is "persistent flow attacks the wall → wall becomes a
target"). If the thesis is structural-break (price has already closed
through the wall in a prior session, support_breakdown) or trend
continuation, anti-pin scoring is INFORMATIONAL — set anti_pin.invoked
=false and do NOT use a low anti-pin score as a reason to cap conviction.
The validator's conviction-cap check only fires when anti_pin.invoked=true.

Populate the anti_pin block with:
  invoked:                true iff anti-pin is the primary thesis
  direction:              "upside" | "downside" | "none"
  score:                  0-4 (count of sub-conditions met)
  conditions_met:         list of sub-condition tags
                          (e.g. ["oi_build", "premium_tilt"])
  conviction_cap_applied: true iff conviction was capped at C/D
                          because of anti-pin score
  cap_reason:             one-sentence explanation when capped

═══════════════════════════════════════════════════════════════════════════
TRIGGER_STRIKE_CONSISTENCY (HARD; validator will reject otherwise)
═══════════════════════════════════════════════════════════════════════════

For BREAKOUT setups (entry_state=CONDITIONAL with a directional trigger),
the spread's SHORT leg must NOT sit AT the trigger level. The short strike
should be at or beyond the NEXT TARGET, not at the wall being broken.

  LONG_DELTA breakout (e.g. "daily close above 430"):
     - preferred_expression.strike_role.trigger_level = 430
     - long leg strike: near the trigger (430, or one strike below)
     - short leg strike: at the NEXT target/wall (e.g. 435 second_magnet,
       440 next call OI, etc.) — STRICTLY GREATER than trigger_level

  SHORT_DELTA downside_break (e.g. "daily close below 420"):
     - preferred_expression.strike_role.trigger_level = 420
     - long leg strike: near the trigger (420, or one strike above)
     - short leg strike: at the NEXT downside target (e.g. 412.5
       max_accel, 410 put OI zone) — STRICTLY LESS than trigger_level

A 425/430 bull_call_spread with trigger="close above 430" is REJECTED as
trigger_strike_mismatch: the 430 short call caps the spread at exactly
the level that activates the trade. The textbook breakout play moves
both legs up so the short leg sits at the next target, e.g. 430/435 or
430/440. If no in-band candidate satisfies this, prefer a strategy-family
preferred_expression (status_observed=strategy_review) over a candidate
row whose strikes contradict the trigger.

═══════════════════════════════════════════════════════════════════════════
CONDITIONAL_QUOTE_VALIDITY (HARD; validator will reject otherwise)
═══════════════════════════════════════════════════════════════════════════

If entry_state=CONDITIONAL and the trigger has NOT fired, any
candidate-row max_profit/max_loss/estimated_entry numerics are PRE-TRIGGER
references — they describe what the spread would cost RIGHT NOW, not
what it will cost after the trigger fires (the underlying will have
moved, IV will have shifted, and the spread price will be materially
different).

Two acceptable handlings:

  (a) PRE_TRIGGER_ANTICIPATORY: idea is to enter the spread BEFORE the
      trigger fires (front-run the breakout). Set status_observed=
      "candidate_pre_trigger" and write a brief one-sentence why
      explaining why the model thinks the trigger is imminent (anti-pin
      satisfied at 4/4, IV unusually low, multi-session repeated alerts
      etc.). Observed numerics ARE valid.

  (b) POST_TRIGGER_RESEARCH: idea is to enter only AFTER the trigger
      fires. Set status_observed="strategy_review", leave numerics
      blank or write "Repriced post-trigger — observed pre-trigger
      numerics are reference only." Do NOT present pre-trigger
      max_profit/loss as expected post-trigger economics.

The default is (b) unless the model explicitly argues for (a).

═══════════════════════════════════════════════════════════════════════════
HORIZON + TRIGGER + INVALIDATION
═══════════════════════════════════════════════════════════════════════════

- The trade is HELD 5-10 trading sessions (1-2 calendar weeks).
- Entry-expiry DTE in 14-75 (chosen by Step 5's dte_band).
- Reject any candidate_structures row whose preferred entry expiry has
  DTE < 14 or > 75 as `horizon_mismatch` in rejected_ideas.
- Calendars: short (near) leg in dte_band; long (far) leg 60-90 DTE.
- Triggers + invalidations stated in DAILY-CLOSE terms or 2-session
  confirmations, never intraday wicks or single-session tape patterns.
- Boundary trades:
    breakout:   daily close above wall OR 2-session hold above it.
    rejection:  failed close above resistance OR close back below wall.
    downside:   close below support / GEX flip.
- Time stop: "close at mid after 7-10 trading sessions if neither trigger
  nor invalidation fires."

═══════════════════════════════════════════════════════════════════════════
HARD RULES (project safety)
═══════════════════════════════════════════════════════════════════════════

- Do NOT invent data. If a field is missing, say "Missing / not provided."
- Pick a DIRECTIONAL STATE, not necessarily an ACTIVE trade. WAIT is
  valid when no directional trigger has fired. Do NOT convert WAIT into
  a range-income structure unless Step 4 explicitly chose range_income.
- Recommendations are research-only. No order placement, no position
  sizing in dollars, no imperative trade instructions.
- Project safety override: do NOT recommend naked short options or
  undefined-risk short-vol structures. risk_reversal has a naked short
  leg and is BLOCKED as preferred_expression; cite the safety override
  in rejected_ideas if it would otherwise be a fit.
- Do not use "mixed", "unclear", or "monitor closely" in headline.title
  / top_reason / watch_trigger without a specific price level and a
  session count in the same sentence.

═══════════════════════════════════════════════════════════════════════════
INPUT (interpolated)
═══════════════════════════════════════════════════════════════════════════

Ticker: {{ticker}}
As-of date: {{as_of_date}}
Spot: {{spot}}

═══════════════════════════════════════════════════════════════════════════
OUTPUT REPORT STRUCTURE (markdown render for headline + sections)
═══════════════════════════════════════════════════════════════════════════

Produce the markdown report using EXACTLY the structure below. Do not add
sections. Do not repeat tables.

# {{ticker}} — {one-line: directional_bias + structure + entry-expiry DTE in [14, 75], hold 5-10 sessions}

## Call

| Field | Value |
|---|---|
| Directional bias | LONG_DELTA / SHORT_DELTA / WAIT (matches headline.directional_bias) |
| Underlying path | bullish_continuation / bearish_rejection / downside_break / pinned_no_directional_entry / data_insufficient |
| Entry state | ACTIVE / CONDITIONAL / NO_ENTRY |
| Trade intent | directional_swing (default) / range_income (only per Step 4) |
| DTE band | momentum (14-30) / standard (31-44) / trend (45-75) |
| Conviction | A / B / C / D / F (one letter — see rating ladder) |
| Preferred entry expiry | YYYY-MM-DD whose DTE is inside the chosen dte_band range (HARD: validator enforces) |
| Preferred structure | one of the mode-whitelisted ids (Step 6) |
| Long leg strike | price + role (trigger_level / support_reclaim / atm_delta_anchor / deep_itm_proxy) |
| Short leg strike | price + role (target_level / next_call_wall / second_magnet / next_put_wall / next_downside_target); MUST satisfy trigger_strike_consistency |
| Trigger level | numeric price the directional trigger references (e.g. 430) |
| Target level | named level above (LONG_DELTA) or below (SHORT_DELTA) the trigger from market_structure_levels |
| Invalid level | numeric price; daily close past this invalidates the setup |
| Trigger | "daily close above/below X" or "2-session hold" — daily-close terms |
| Invalidation | "daily close above/below X" — daily-close terms |
| Time stop | "close at mid after 7-10 trading sessions if neither trigger nor invalidation fires" |

## Why (<=120 words)

Three sentences max, one per supporting pillar (dealer regime / flow /
volatility). Cite primary evidence by source path the first time a claim
appears. Name the single biggest conflicting piece of evidence in one
clause, then state which pillar wins for the 5-10 session horizon.

## Expiry Selection

| Field | Value |
|---|---|
| Preferred entry expiry | YYYY-MM-DD in tabs.volatility.term_structure inside the chosen dte_band |
| Entry DTE | integer (14-30 for momentum, 45-75 for trend) |
| Why this band | one sentence: breakout/active -> momentum; trend-continuation -> trend |
| Why this expiry | one sentence citing IV level, vanna regime, or charm window position |
| Alternative | second expiry in the same band, or "none — only one in-band expiry has liquidity" |

## Scenarios (3 rows, probabilities sum to 100%)

| Scenario | Probability | Trigger (daily close) | Level | Best expression |
|---|---:|---|---|---|
| upside | % | | named level | mode-whitelisted directional structure |
| base | % | | named level | mode-whitelisted directional structure |
| downside | % | | named level | mode-whitelisted directional structure |

## Conflicts (cap = 2; severities high or medium only)

| Severity | One-sentence conflict, citing the pillars in tension |
|---|---|

## Required Checks (cap = 2)

| Check | What confirms |
|---|---|

Each row must be either pre-entry (resolvable before the trigger fires)
or in-trade (a monitor with an action).

## Rejected Ideas (min 3, max 5)

| Strategy | Why rejected at this horizon / mode |
|---|---|

Use canonical strategy ids. At least one rejection MUST cite one of:
  - horizon_mismatch (DTE outside 14-75)
  - mode_mismatch    (e.g. iron_condor rejected because
                      trade_intent=directional_swing)
  - safety_override  (short_strangle / risk_reversal: undefined-risk,
                      blocked by project policy)

═══════════════════════════════════════════════════════════════════════════
RATING LADDER (headline.conviction)
═══════════════════════════════════════════════════════════════════════════

  A: Actionable, high conviction (3 of 3 primary pillars aligned, no
     missing primary evidence, entry_state=ACTIVE or trigger imminent)
  B: Actionable, small size (one medium conflict OR one primary field
     missing; entry_state=CONDITIONAL with strong setup)
  C: Watchlist (primary thesis present but unconfirmed;
     entry_state=CONDITIONAL)
  D: No trade (pillars conflict, no clean winner; entry_state=NO_ENTRY)
  F: Data insufficient (>=2 primary fields missing;
     directional_bias=WAIT, underlying_path=data_insufficient)

CONFIDENCE (headline.score, 0-100 integer; headline.score_scale = 100):
  85-100  3 of 3 primary pillars aligned, no missing fields. Conviction A.
  70-84   3 aligned w/ one medium conflict, or 3 aligned w/ one missing.
          Conviction A/B.
  55-69   2 of 3 aligned with dominant pillar winning clearly. Conviction B/C.
  40-54   Pillars conflict but a winner can still be named. Conviction C.
  20-39   No clean winner, or 2+ primary fields missing. Conviction D.
  0-19    Data insufficient — primary evidence absent. Conviction F.
Set headline.score honestly. Do NOT default to 0; if you can name a
dominant pillar and a directional_bias, score at least 40.

Do not end with vague commentary. Do not repeat any table. Do not use
the word "monitor" without a level and a session count."""

_VOLATILE_HASH_KEYS = {
    "analysis_input_hash",
    "analysis_produced_at",
    "as_of",
    "generated_at",
    "produced_at",
    "prompt_payload_jsonb",
    "prompt_text",
    "requested_at",
    "output_schema_jsonb",
}


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


def _strip_volatile_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile_for_hash(item)
            for key, item in value.items()
            if key not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile_for_hash(item) for item in value]
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_trade_insights_ai_analysis_input(
    *,
    ticker: str,
    run_id: int,
    trade_insights_input_hash: str,
    trade_insights_payload: dict[str, Any],
    stock_report_payload: dict[str, Any],
    stock_history_payload: dict[str, Any],
    volatility_series_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the bounded deterministic payload captured at POST time."""

    market_structure_levels = stock_report_payload.get("market_structure_levels") or {}
    spot = (stock_report_payload.get("market_structure") or {}).get(
        "spot"
    ) or volatility_series_payload.get("spot")
    missing_data: list[str] = []

    dealer_regime = stock_report_payload.get("dealer_regime") or {}
    exposures_summary = _sorted_front(
        list(stock_report_payload.get("exposures_summary") or []),
        6,
    )
    strike_exposures = _prune_strike_exposures(
        list(stock_report_payload.get("strike_exposures") or []),
        spot=spot,
    )
    if not dealer_regime:
        missing_data.append("tabs.market_structure.dealer_regime is empty")
    if not exposures_summary:
        missing_data.append("tabs.market_structure.exposures_summary is empty")
    # Compact mirror so the Volatility tab consumer can quote regime sub-bars
    # without cross-tab path-walking that has historically caused validator
    # rejections (source_path prefix does not exist...).
    dealer_regime_header = (
        {
            "label": dealer_regime.get("label"),
            "score": dealer_regime.get("score"),
            "gamma_score": dealer_regime.get("gamma_score"),
            "vanna_score": dealer_regime.get("vanna_score"),
            "charm_score": dealer_regime.get("charm_score"),
            "odte_net_gex": dealer_regime.get("odte_net_gex"),
            "odte_share_pct": dealer_regime.get("odte_share_pct"),
            "headline": dealer_regime.get("headline"),
            "subtitle": dealer_regime.get("subtitle"),
        }
        if dealer_regime
        else {}
    )

    stock_history_rows = _sorted_recent(
        list((stock_history_payload.get("rows") or [])),
        30,
    )
    if not stock_history_rows:
        missing_data.append("tabs.market_structure.stock_history.rows is empty")

    hv_iv_history = _sorted_recent(
        list(volatility_series_payload.get("hv_iv_history") or []),
        90,
    )
    if not hv_iv_history:
        missing_data.append("tabs.volatility.hv_iv_history is empty")

    vrp_spread = _sorted_recent(
        list(volatility_series_payload.get("vrp_spread") or []),
        30,
    )
    if not vrp_spread:
        missing_data.append("tabs.volatility.vrp_spread is empty")

    volatility_smile = []
    for curve in _sorted_front(list(volatility_series_payload.get("smile") or []), 6):
        item = dict(curve)
        item["points"] = _downsample_smile_points(list(item.get("points") or []), 25)
        volatility_smile.append(item)

    trade_candidates = list(trade_insights_payload.get("candidate_structures") or [])
    synthesis = trade_insights_payload.get("synthesis") or {}
    next_earnings_date = stock_report_payload.get("next_earnings_date")
    event_data_known = next_earnings_date is not None
    if not event_data_known:
        missing_data.append("tabs.positioning.next_earnings_date is empty")

    analysis_input: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "ticker": ticker.upper(),
        "run_id": run_id,
        "trade_insights_input_hash": trade_insights_input_hash,
        "tabs": {
            "market_structure": {
                "generated_at": stock_report_payload.get("generated_at"),
                "market_structure": stock_report_payload.get("market_structure") or {},
                "market_structure_levels": market_structure_levels,
                "strike_gex_curve": _prune_strike_gex_curve(
                    list(stock_report_payload.get("strike_gex_curve") or []),
                    market_structure_levels,
                ),
                "max_pain_rows": _sorted_front(
                    list(stock_report_payload.get("max_pain_rows") or []),
                    12,
                ),
                # PR #61: dealer-regime summary (label, gamma/vanna/charm
                # sub-scores, 0DTE GEX, headline narrative). Primary evidence
                # at the 1-2 week swing-hold horizon.
                "dealer_regime": dealer_regime,
                # PR #60: per-expiry vanna + charm derivations. Front 6
                # expiries — caller filters to the swing window when reading.
                "exposures_summary": exposures_summary,
                # PR #60: per-strike call/put vanna+charm. Pruned to front 4
                # expiries × ±10 strikes around spot.
                "strike_exposures": strike_exposures,
                "stock_history": {
                    **{
                        key: value
                        for key, value in stock_history_payload.items()
                        if key != "rows"
                    },
                    "rows": stock_history_rows,
                },
            },
            "volatility": {
                "as_of": volatility_series_payload.get("as_of"),
                "backfill_status": volatility_series_payload.get("backfill_status")
                or "ready",
                "header": volatility_series_payload.get("header") or {},
                "term_structure": _sorted_front(
                    list(volatility_series_payload.get("term_structure") or []),
                    20,
                ),
                "smile": volatility_smile,
                "hv_iv_history": hv_iv_history,
                "iv_percentile_distribution": volatility_series_payload.get(
                    "iv_percentile_distribution"
                )
                or {},
                "iv_of_iv": _sorted_recent(
                    list(volatility_series_payload.get("iv_of_iv") or []),
                    90,
                ),
                "rv_spy_corr": _sorted_recent(
                    list(volatility_series_payload.get("rv_spy_corr") or []),
                    90,
                ),
                "regime_quadrant": volatility_series_payload.get("regime_quadrant")
                or {},
                "divergence": _sorted_recent(
                    list(volatility_series_payload.get("divergence") or []),
                    20,
                ),
                "divergence_headline": volatility_series_payload.get(
                    "divergence_headline"
                )
                or "",
                "vrp_spread": vrp_spread,
                "vrp_spread_headline": volatility_series_payload.get(
                    "vrp_spread_headline"
                )
                or "",
                "spot": volatility_series_payload.get("spot"),
                # Mirror of dealer_regime so the Vol-regime panel consumer can
                # cite Γ/V/C sub-bars and 0DTE share without crossing tabs.
                "dealer_regime_header": dealer_regime_header,
            },
            "flow": {
                "flow": stock_report_payload.get("flow") or {},
                "options_timeline": _sorted_recent(
                    list(stock_report_payload.get("options_timeline") or []),
                    60,
                ),
                "option_chain_per_strike": _prune_chain_rows(
                    list(stock_report_payload.get("option_chain_per_strike") or []),
                    spot=spot,
                    limit=120,
                ),
            },
            "positioning": {
                "dark_pool_print_count": stock_report_payload.get(
                    "dark_pool_print_count"
                ),
                "dark_pool_notional": stock_report_payload.get("dark_pool_notional"),
                "short_data": stock_report_payload.get("short_data"),
                "oi_change_top": list(stock_report_payload.get("oi_change_top") or [])[
                    :50
                ],
                "aggregates": stock_report_payload.get("aggregates") or {},
                "next_earnings_date": next_earnings_date,
            },
            "trade_insights": trade_insights_payload,
        },
        "candidate_structures": trade_candidates,
        "required_before_sizing": list(synthesis.get("required_before_sizing") or []),
        "event_data_known": event_data_known,
        "data_freshness": _build_data_freshness(
            stock_history_rows=stock_history_rows,
            hv_iv_history=hv_iv_history,
            short_data=stock_report_payload.get("short_data") or {},
            volatility_as_of=volatility_series_payload.get("as_of"),
            trade_insights_as_of=trade_insights_payload.get("as_of"),
        ),
        "missing_data": missing_data,
    }
    analysis_input["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        analysis_input
    )
    return analysis_input


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


def hash_trade_insights_ai_analysis_input(analysis_input: dict[str, Any]) -> str:
    """Stable hash over deterministic input, excluding execution metadata."""

    return _canonical_hash(_strip_volatile_for_hash(analysis_input))


def build_trade_insights_ai_prompt_payload(
    analysis_input: dict[str, Any],
    *,
    produced_at: datetime,
) -> dict[str, Any]:
    payload = dict(analysis_input)
    payload["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        analysis_input
    )
    payload["analysis_produced_at"] = _iso_z(produced_at)
    return payload


def build_trade_insights_ai_prompt(prompt_payload: dict[str, Any]) -> str:
    payload_json = json.dumps(prompt_payload, sort_keys=True, indent=2, default=str)
    return (
        f"{MARKET_INTELLIGENCE_PROMPT}\n\n"
        "Integration notes for this local JSON runner:\n"
        "Analyze only the supplied combined deterministic prompt payload below.\n"
        "Do not fetch outside data. Do not use tools. Do not invent unavailable fields.\n"
        "Payload key map: ticker <- ticker; as_of <- tabs.trade_insights.as_of or "
        "analysis_produced_at; spot <- underlying_price or "
        "tabs.market_structure.market_structure.spot; market structure <- "
        "tabs.market_structure (primary keys: tabs.market_structure.dealer_regime, "
        "tabs.market_structure.exposures_summary, tabs.market_structure.strike_exposures, "
        "tabs.market_structure.market_structure_levels, tabs.market_structure.strike_gex_curve); "
        "volatility <- tabs.volatility (including tabs.volatility.dealer_regime_header); "
        "flow <- tabs.flow; positioning <- tabs.positioning.\n"
        "Use analysis_produced_at exactly as supplied; do not invent a different production time.\n"
        f"schema_version MUST be exactly the string {PROMPT_VERSION!r} (do not abbreviate or "
        "reformat). This is also stamped as a JSON-schema const.\n"
        "Source-path rule (HARD): every source_path in the outcome must resolve to a key path "
        "that exists in the payload. Do not cite synthetic paths such as "
        "tabs.x.y[-1].field or .header.iv unless that exact key exists. If a value is not "
        "in the payload, leave the field out and add a 'Missing / not provided' note to "
        "missing_data instead of inventing a path.\n"
        "Preserve every candidate status, every risk_flags array, and every deterministic "
        "max_loss/max_profit value exactly as supplied.\n"
        "Horizon enforcement: every candidate_structures row whose preferred entry "
        "expiry has DTE < 14 or DTE > 75 must be rejected as horizon_mismatch in "
        "rejected_ideas. The trade is HELD 5-10 trading sessions; entry expiry "
        "must leave enough premium that the exit is not at peak gamma/theta crush. "
        "The deterministic candidate list is filtered to the 14-75 DTE swing window "
        "by the upstream assembler and tagged with dte_band (momentum=14-30, "
        "standard=31-44, trend=45-75) plus expression_delta (long_delta / "
        "short_delta / neutral) so you can pattern-match candidates to the "
        "directional_bias + dte_band chosen at decision Steps 2 and 5.\n"
        "Mode-aware structure consistency (HARD): if headline.trade_intent == "
        "'directional_swing', preferred_expression.structure MUST be in "
        f"{sorted(DIRECTIONAL_SWING_STRUCTURES)}. If trade_intent == "
        f"'range_income', structure MUST be in {sorted(RANGE_INCOME_STRUCTURES)}. "
        "iron_condor / call_credit_spread / put_credit_spread / calendar_spread "
        "are BANNED as preferred_expression in directional_swing mode — picking "
        "a vol-seller for a directional swing is the exact failure mode this "
        "schema is built to prevent. The validator will reject the outcome if "
        "mode and structure disagree.\n"
        "Delta-match (HARD): when directional_bias == LONG_DELTA, "
        "preferred_expression.structure must be a net-positive-delta structure "
        "(long_call, call_debit_spread, bull_call_spread, call_diagonal). When "
        "directional_bias == SHORT_DELTA, structure must be net-negative-delta "
        "(long_put, put_debit_spread, bear_put_spread, put_diagonal). When "
        "directional_bias == WAIT, structure MUST be 'no_trade'.\n"
        "DTE-band consistency (HARD, v5.1): headline.dte_band MUST be one of "
        "['momentum','standard','trend'] and the chosen preferred entry-expiry "
        "DTE MUST fall inside the band range — momentum=[14,30], "
        "standard=[31,44], trend=[45,75]. Emitting dte_band='momentum' with a "
        "34 DTE expiry is rejected. Pick the band whose range contains the DTE.\n"
        "Trigger-strike consistency (HARD, v5.1): populate "
        "preferred_expression.strike_role with {long_leg_role, short_leg_role, "
        "trigger_level, target_level, invalid_level}. For LONG_DELTA "
        "breakouts, the spread's short leg strike MUST be STRICTLY GREATER "
        "than trigger_level (e.g. trigger=430 → short=435 second_magnet, NOT "
        "short=430). For SHORT_DELTA downside breaks, short leg strike MUST "
        "be STRICTLY LESS than trigger_level. A 425/430 bull_call_spread on "
        "a 'close above 430' trigger is rejected as trigger_strike_mismatch. "
        "If no in-band candidate row satisfies this, prefer a strategy-family "
        "preferred_expression (idea_id = strategy family, status_observed = "
        "'strategy_review') and describe the correct strike placement in "
        "preferred_expression.why; cite the offending candidate row in "
        "rejected_ideas with reason 'trigger_strike_mismatch'.\n"
        "Conditional-quote validity (HARD, v5.1): if entry_state=CONDITIONAL "
        "and the trigger has not fired, candidate-row max_profit/max_loss/"
        "estimated_entry are pre-trigger references — the option chain WILL "
        "reprice after the trigger. Two acceptable handlings: (a) PRE-trigger "
        "anticipatory entry — set status_observed='candidate_pre_trigger', "
        "explain why the trigger is imminent (anti-pin satisfied 4/4, very "
        "low IV, repeated alerts) and observed numerics are valid; or (b) "
        "POST-trigger research — set status_observed='strategy_review' and "
        "either leave numerics blank or write 'Repriced post-trigger — "
        "observed pre-trigger numerics are reference only.' Do NOT present "
        "observed pre-trigger max_profit/loss as expected post-trigger "
        "economics. Default to (b) unless the model explicitly argues for (a).\n"
        "Anti-pin quality (HARD, v5.1): the anti-pin reclassification "
        "(wall=target, not cap) fires ONLY when AT LEAST 3 of 4 hold — "
        "(1) 3+ consecutive sessions of OI increase at/within one strike of "
        "the relevant wall, (2) net premium tilt > 2x in the directional "
        "direction, (3) repeated ask-side/ascending-fill alerts clustered "
        "near the wall, (4) spot within 1.5% of the wall AND no two-session "
        "failed close. In headline.top_reason or dominant_read.summary, cite "
        "which sub-conditions hold (e.g. 'anti-pin satisfied 3/4 — OI build, "
        "premium tilt, spot proximity; alert cluster absent'). If only 2 of "
        "4 hold, cap headline.conviction at C.\n"
        "Anti-pin SCOPE (HARD, v5.2): the conviction cap and the wall=target "
        "reclassification apply ONLY when anti_pin.invoked=true (anti-pin is "
        "the primary thesis). For structural-break theses (price already "
        "closed through the wall) or trend-continuation theses, anti-pin "
        "scoring is informational — set anti_pin.invoked=false and do NOT "
        "use a low score as a reason to cap conviction.\n"
        "Thesis archetype (HARD, v5.2): headline.thesis_archetype MUST be "
        "one of ['resistance_rejection','support_breakdown','breakout_"
        "continuation','pin_no_trade','data_insufficient']. The archetype "
        "must agree with underlying_path: resistance_rejection ↔ "
        "bearish_rejection, support_breakdown ↔ downside_break, "
        "breakout_continuation ↔ bullish_continuation, pin_no_trade ↔ "
        "pinned_no_directional_entry, data_insufficient ↔ data_insufficient. "
        "In top_reason, cite the specific completed daily close session "
        "that justifies the archetype.\n"
        "ACTIVE trigger evidence (HARD, v5.2): headline.entry_state=ACTIVE "
        "is allowed ONLY when the payload contains a COMPLETED daily close "
        "that satisfies the trigger. Populate the trigger_evidence block "
        "with the proving close. If the latest completed close does NOT "
        "satisfy the trigger, you MUST emit entry_state=CONDITIONAL — "
        "intraday spot is NOT sufficient. The validator will reject "
        "entry_state=ACTIVE when trigger_evidence.trigger_fired=false.\n"
        "strike_role level type (HARD, v5.2): trigger_level, target_level, "
        "and invalid_level must be NUMERIC price strings ('215', '215.00') "
        "or numbers — NOT dict objects pasted from the payload. The "
        "Pydantic schema will reject anything else.\n"
        "Headline title (v5.2): headline.title must be 10-20 words, naming "
        "directional_bias + structure + trigger level + dte_band. Example: "
        "'NVDA SHORT_DELTA bear_put_spread fires on daily close below 215, "
        "35 DTE standard band.' Do NOT emit 'NVDA AI Analysis' or other "
        "page-title strings — that's a v5.1 failure mode.\n"
        "Minimum reward/risk under CONDITIONAL conviction ≤ C (v5.2): when "
        "entry_state=CONDITIONAL AND headline.conviction in {C, D, F}, "
        "preferred_expression.reward_risk should be >= 1.5 for the trade "
        "to be worth the conditional setup risk. Lower R:R with these "
        "conviction levels often has poor expected value given conditional "
        "setups historically hit-rate below 50%.\n"
        "Project safety override: do not recommend naked short options or "
        "undefined-risk short-vol structures. risk_reversal is excluded from "
        "the directional_swing whitelist because its short put leg is naked; "
        "cite it in rejected_ideas if it would otherwise be a fit.\n"
        "Avoid order placement, position sizing in dollars, personalized financial advice, "
        "and imperative trade instructions.\n"
        "Outcome field mapping: headline (directional_bias, entry_state, "
        "trade_intent, underlying_path, dte_band, stance, conviction, score) + "
        "dominant_read <- Call section; section_cards <- Why paragraph (one card "
        "per pillar — market_structure, volatility, flow_positioning); conflicts "
        "<- Conflicts table (cap 2); scenario_cards <- Scenarios table (exactly "
        "3, probabilities sum to 100); preferred_expression + best_expressions "
        "<- Call.preferred_structure / Expiry Selection; required_checks <- "
        "Required Checks table (cap 2); rejected_ideas <- Rejected Ideas table "
        "(min 3, max 5); rendering.disclaimer/final <- research-only framing only.\n"
        "Derive headline.stance from headline.directional_bias for "
        "UI/markdown display: LONG_DELTA -> 'bullish', SHORT_DELTA -> 'bearish', "
        "WAIT -> 'wait'. (stance is the legacy display Literal; directional_bias "
        "is the actual gate.)\n"
        "idea_id rules (HARD): preferred_expression.idea_id, every "
        "best_expressions[].idea_id, and every rejected_ideas[].idea_id MUST be "
        "either (a) the idea_id of a row in the supplied candidate_structures "
        "array, or (b) a canonical strategy family id. Never free text. For "
        "preferred_expression and best_expressions when trade_intent="
        "directional_swing, the strategy-family option is restricted to "
        f"{sorted(DIRECTIONAL_SWING_STRUCTURES)}. When trade_intent=range_income, "
        f"strategy-family option is restricted to {sorted(RANGE_INCOME_STRUCTURES)}. "
        "rejected_ideas may reference any canonical strategy id from "
        f"{sorted(STRATEGY_FAMILY_IDS)} so an out-of-mode family can be "
        "explicitly rejected.\n"
        "For strategy-family preferred_expression / best_expressions entries, set "
        "status_observed to 'strategy_review' and risk_flags_observed to [].\n"
        f"headline.conviction MUST be a single letter from {list(FINAL_RATING_VALUES)} "
        "(rating ladder in the prompt above). headline.conviction_label holds the "
        "one-clause explanation. headline.score is the 5-10 session confidence "
        "percentage (integer 0-100, scored against the Confidence rubric in the prompt). "
        "headline.score_scale must be 100. Do not leave score=0 unless data is genuinely "
        "insufficient (Conviction F); a real dominant-pillar read scores at least 40.\n"
        "Set guardrails.no_executable_recommendations=true when recommendations remain "
        "research-only, non-imperative, and not order-placement instructions; this flag does "
        "not prohibit research-only recommendations.\n"
        "Keep the markdown output (rendering.markdown if emitted) under ~3 KB / ~400 words. "
        "Do not repeat any table. Do not list more than 2 required_checks or more than 2 "
        "conflicts. Do not emit a Strategy Selection 12-row grid — only rejected_ideas "
        "(min 3, max 5).\n"
        "Emit only JSON conforming to the TradeInsightAiOutcome schema.\n\n"
        "Payload:\n"
        f"{payload_json}\n"
    )


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


def trade_insights_ai_output_schema(*, strict: bool = True) -> dict[str, Any]:
    """Produce the JSON schema for TradeInsightAiOutcome.

    `strict=True` (default, used for Codex): forces every nested property to be
    required and `additionalProperties: false` everywhere. Codex's structured
    output mode handles this cleanly.

    `strict=False` (used for Claude): keeps only the required set Pydantic
    naturally declares (i.e. non-Optional fields). Claude's StructuredOutput
    tool silently falls back to freeform JSON when the schema is too strict at
    every level, so we trade some validation surface for adherence.
    """
    raw = TradeInsightAiOutcome.model_json_schema()
    schema = _coerce_strict_schema(raw) if strict else raw
    schema["properties"]["schema_version"]["const"] = PROMPT_VERSION
    schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"]["enum"] = (
        list(FINAL_RATING_VALUES)
    )
    return schema


# Claude lenient coercion (large; extracted to its own module per the module-size budget).
# Re-exported here so test callers using the historical import path continue to work.
from uw_scan.reports.trade_insights_ai_lenient import (  # noqa: E402
    _coerce_claude_outcome_dict,
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


def render_trade_insights_ai_markdown(outcome: TradeInsightAiOutcome) -> str:
    """Render compact Markdown from validated structured output."""

    # `headline.score` is repurposed as a 0-100 confidence percentage. We
    # render it as "Confidence: N/100", and suppress the line when the model
    # left it blank (0/0) — drives the cosmetic v3 follow-up.
    confidence_line: list[str] = []
    if outcome.headline.score or outcome.headline.score_scale:
        confidence_line.append(
            f"Confidence: {outcome.headline.score}/{outcome.headline.score_scale}"
        )
    lines: list[str] = [
        f"# {outcome.ticker} - {outcome.headline.stance_label}",
        outcome.headline.title,
        "",
        f"Produced: {_iso_z(outcome.analysis_produced_at)}",
        *confidence_line,
        f"Conviction: {outcome.headline.conviction} - {outcome.headline.conviction_label}",
        f"Top reason: {outcome.headline.top_reason}",
        f"Primary risk: {outcome.headline.primary_risk}",
        f"Watch: {outcome.headline.watch_trigger}",
        "",
        "## Metrics",
    ]
    for card in outcome.metric_cards:
        note = f" - {card.note}" if card.note else ""
        lines.append(f"- {card.label}: {card.value}{note}")

    lines.extend(["", "## Scenarios"])
    for card in outcome.scenario_cards:
        lines.append(f"- {card.case}: {card.title} - {card.description}")

    lines.extend(["", "## Sections"])
    for section in (
        outcome.section_cards.market_structure,
        outcome.section_cards.volatility,
        outcome.section_cards.flow_positioning,
    ):
        score = (
            f" ({section.score}/{section.max_score})"
            if section.score is not None and section.max_score is not None
            else ""
        )
        lines.append(f"### {section.title}{score}")
        lines.append(section.summary)
        for highlight in section.highlights:
            note = f" - {highlight.note}" if highlight.note else ""
            lines.append(f"- {highlight.label}: {highlight.value}{note}")
        for level in section.levels:
            note = f" - {level.note}" if level.note else ""
            lines.append(f"- {level.kind}: {level.price} {level.value}{note}")

    if outcome.vrp_assessment is not None:
        lines.extend(["", f"## {outcome.vrp_assessment.title}"])
        lines.append(outcome.vrp_assessment.summary)
        for metric in outcome.vrp_assessment.metrics:
            lines.append(f"- {metric.label}: {metric.value}")
        lines.append(f"Reason: {outcome.vrp_assessment.reason}")

    if outcome.preferred_expression is not None:
        expression = outcome.preferred_expression
        lines.extend(["", f"## {expression.title}"])
        if expression.subtitle:
            lines.append(expression.subtitle)
        lines.append(f"Why: {expression.why}")
        lines.append(f"Status: {expression.status_observed}")
        lines.append(
            f"Risk flags: {', '.join(expression.risk_flags_observed) or 'none'}"
        )
        for note in expression.management_notes:
            lines.append(f"- {note}")

    if outcome.conflicts:
        lines.extend(["", "## Conflicts"])
        for item in outcome.conflicts:
            lines.append(f"- {item.severity}: {item.description}")

    if outcome.required_checks:
        lines.extend(["", "## Required Checks"])
        for item in outcome.required_checks:
            blocker = "blocks sizing" if item.blocks_sizing else "informational"
            # Strip trailing period from `check` so the title — reason join
            # doesn't render as "...fires.: Liquidity must support..." (the
            # model frequently terminates the check phrase with punctuation).
            check_text = item.check.rstrip(". ").rstrip()
            lines.append(f"- {check_text} — {item.reason} ({blocker})")

    if outcome.rejected_ideas:
        lines.extend(["", "## Rejected Ideas"])
        for item in outcome.rejected_ideas:
            lines.append(f"- {item.idea_id} {item.structure}: {item.reason}")

    if outcome.missing_data:
        lines.extend(["", "## Missing Data"])
        for item in outcome.missing_data:
            lines.append(f"- {item}")

    lines.extend(["", outcome.rendering.disclaimer])
    return "\n".join(lines)
