"""Static prompt text and vocabulary constants for Trade Insights AI.

Holds the v5.2 (and onward) MARKET_INTELLIGENCE_PROMPT plus every immutable
vocabulary tuple / frozenset the schema, validators, and lenient coercer
share. Pure data — no I/O, no helpers that touch the DB.
"""

from __future__ import annotations

from .trade_framework_kb import TRADE_FRAMEWORK_KNOWLEDGE

PROMPT_VERSION = "trade-blast-v1"
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

STEP 2.5 — TRIGGER_COMPONENTS  (v5.3: NEW — three structured fields)

  v5.2 used a single trigger_level overloaded across two meanings: "the
  wall that confirmed the thesis" vs "the level where I would actually
  enter the trade." On NVDA, Codex emitted 220 (broken wall) and Claude
  emitted 215 (next confirmation level) — both defensible, but the
  schema could not represent that they meant DIFFERENT things. v5.3
  decomposes into three required TriggerComponent blocks, each carrying
  its own level, semantic meaning, and `fired` boolean evaluated
  against actual daily-close evidence:

    thesis_trigger   — the level that, if crossed in the right
                       direction, VALIDATES the spatial archetype.
                       For support_breakdown: the put_wall that was
                       broken. For breakout_continuation: the
                       call_wall that was broken. For
                       resistance_rejection: the resistance level
                       that REJECTED price.

    entry_trigger    — the level that, if crossed, signals to actually
                       OPEN the planned trade. MAY equal
                       thesis_trigger.level when the plan is "enter on
                       the same close that confirms the thesis" — but
                       the meaning strings MUST differ. More often
                       entry_trigger is a confirmation level (next put
                       OI strike for downside, max_pain for upside)
                       and IS the long-leg strike of the spread.

    invalidation     — the level that, if crossed AGAINST the trade,
                       kills the thesis. For SHORT_DELTA, typically a
                       reclaim of the broken wall. For LONG_DELTA,
                       typically a close back below the breakout base.

  Each TriggerComponent block:
    {
      "level":           <Decimal: the price line>,
      "meaning":         "<short label, e.g. 'support_breakdown_confirmed'>",
      "fired":           <bool — has a COMPLETED daily close crossed
                         level in the relevant direction?>,
      "evidence_close":  <the daily close that proves fired=true;
                         when fired=false, cite the latest completed
                         close that was checked>,
      "evidence_date":   "YYYY-MM-DD",
      "source_path":     "tabs.market_structure.stock_history.rows[N].spot"
    }

  For thesis_trigger and entry_trigger, fired=true requires a COMPLETED
  daily close from tabs.market_structure.stock_history.rows that crosses
  `level` in the relevant direction (below for SHORT_DELTA, above for
  LONG_DELTA). INTRADAY SPOT IS NOT SUFFICIENT. The validator rejects
  fired=true without a real evidence_close.

  invalidation.fired=true means the trade is already dead — practically
  this should be rare since you only emit a recommendation when the
  setup hasn't already invalidated.

STEP 3 — ENTRY_STATE  (v5.3: DERIVED MECHANICALLY from STEP 2.5)
    ENTRY_STATE is not a model judgment in v5.3 — it is a deterministic
    function of the three trigger booleans you populated in STEP 2.5:

      thesis_trigger.fired AND entry_trigger.fired AND NOT invalidation.fired
          → ACTIVE

      thesis_trigger.fired AND NOT entry_trigger.fired AND NOT invalidation.fired
          → CONDITIONAL  (thesis confirmed, waiting for entry confirmation)

      NOT thesis_trigger.fired AND NOT invalidation.fired
          → CONDITIONAL  if the setup has a clean directional read and
                         the trigger is expected to resolve within the
                         5-10 session hold
          → NO_ENTRY     when directional_bias=WAIT or the trigger
                         requires a setup the data does not yet support

      invalidation.fired = true
          → NO_ENTRY     (thesis is dead; record what invalidated it
                         in primary_risk + watch_trigger)

    The validator enforces this derivation table. Emitting
    entry_state=ACTIVE when entry_trigger.fired=false (or
    thesis_trigger.fired=false) is rejected.

    ACTIVE_TRIGGER_EVIDENCE_RULE (HARD, v5.3): ACTIVE is allowed ONLY
    when BOTH thesis_trigger AND entry_trigger have fired=true with a
    real evidence_close pulled from tabs.market_structure.stock_history.
    If thesis has fired but entry has not (the common case immediately
    after a wall break), the trade is CONDITIONAL with entry_trigger
    as the watch level.

    The v5.2 trigger_evidence block is RETAINED for backwards-
    compatible audit (it now mirrors thesis_trigger's evidence) but the
    authoritative state lives in thesis_trigger / entry_trigger /
    invalidation.

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

STEP 6.5 — OPTION_LEGS  (v5.3: NEW — explicit legs[] on preferred_expression)

  Every structured preferred_expression MUST emit
  preferred_expression.legs as an explicit array of option legs:

    legs = [
      {"option_type": "put",  "side": "long",  "strike": 215, "expiry": "2026-06-26"},
      {"option_type": "put",  "side": "short", "strike": 210, "expiry": "2026-06-26"}
    ]

  Per-structure leg geometry (HARD; validator rejects otherwise):

    bear_put_spread  /  put_debit_spread (SHORT_DELTA):
       exactly 2 legs — 1 long put + 1 short put
       long.strike > short.strike, SAME expiry

    bull_call_spread /  call_debit_spread (LONG_DELTA):
       exactly 2 legs — 1 long call + 1 short call
       long.strike < short.strike, SAME expiry

    put_credit_spread (SHORT_DELTA, range_income only):
       exactly 2 legs — 1 short put + 1 long put (protective)
       short.strike > long.strike, SAME expiry, DEFINED-RISK ONLY

    call_credit_spread (LONG_DELTA, range_income only):
       exactly 2 legs — 1 short call + 1 long call (protective)
       short.strike < long.strike, SAME expiry, DEFINED-RISK ONLY

    long_call (LONG_DELTA): exactly 1 leg — option_type=call, side=long
    long_put  (SHORT_DELTA): exactly 1 leg — option_type=put,  side=long

    call_diagonal (LONG_DELTA): 2 legs — short call near + long call far
                                 (long DTE > short DTE; defined-risk)
    put_diagonal  (SHORT_DELTA): mirror of call_diagonal

    iron_condor / iron_butterfly / butterfly / calendar_spread:
       provide all 3-4 legs honestly; validator enforces structure
       per family.

    no_trade  /  strategy_review:
       legs may be empty []; the structure-leg check is skipped.

  PROJECT SAFETY: NO NAKED SHORTS. Every credit-spread family MUST
  include BOTH the short leg AND the protective long leg. A single-
  leg short_call or short_put is rejected by the validator as a
  naked-short policy violation.

  LEGS_ALIGN_WITH_TRIGGERS (HARD, v5.3): for any spread, the LONG
  leg's strike MUST be within 2% of either entry_trigger.level or
  thesis_trigger.level. This makes "is the actual long-put strike
  215 or 220?" a falsifiable claim that ties the proposed expression
  back to the trigger components from STEP 2.5.

  The legacy preferred_expression.strike_role block from v5.2 is
  RETAINED for the existing strike-role tile in the UI — populate it
  consistently with legs[] (the long leg corresponds to long_leg_role,
  short to short_leg_role).

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


# CONTRACT_PROMPT — the JSON-contract clause every provider must see.
#
# Lifted verbatim from the historical Claude-only `_JSON_ONLY_SYSTEM_PROMPT`
# at worker/jobs/trade_insights_claude_runner.py (pre-deepseek-decoupling).
# Codex was getting these rules indirectly via the integration-notes appendix
# in analysis_input.build_trade_insights_ai_prompt; Claude was getting them via
# --append-system-prompt. DeepSeek would have gotten nothing. Centralizing here
# means every provider sees the same contract through the user-prompt path.
#
# The final Claude-specific sentence ("Use the StructuredOutput tool if
# available; otherwise emit the JSON object as the entire response.") is
# INTENTIONALLY DROPPED here — that sentence is provider-mechanic advice and
# lives only inside ClaudeRunner.run() comments where it belongs.
#
# The phrase "the supplied --json-schema" (Claude CLI flag name) was rewritten
# to "the supplied JSON schema" so the constant is provider-neutral.
CONTRACT_PROMPT = """\
Emit a single raw JSON object conforming EXACTLY to the supplied JSON schema. \
Use exact field names at every nesting level; additionalProperties is false \
everywhere. No markdown, no code fences, no prose before/after.

Populate EVERY field below; do not leave any blank, null, or set to placeholder \
strings like "n/a" or "unknown".

VOCAB MAPPINGS (the user prompt uses analyst vocabulary; translate to schema \
Literals on output):
- headline.trade_intent MUST be one of: "directional_swing", "range_income". \
  Default to "directional_swing" unless Step 4 of the decision order selected \
  range_income.
- headline.directional_bias MUST be one of: "LONG_DELTA", "SHORT_DELTA", "WAIT". \
  NEVER emit "bullish_continuation" or "long" or "bull" — those values belong \
  in underlying_path. The bias is the trader-facing directional gate.
- headline.entry_state MUST be one of: "ACTIVE", "CONDITIONAL", "NO_ENTRY".
- headline.underlying_path MUST be one of: "bullish_continuation", \
  "bearish_rejection", "downside_break", "pinned_no_directional_entry", \
  "data_insufficient".
- headline.dte_band MUST be one of: "momentum", "standard", "trend". v5.1 \
  restored the standard band (31-44 DTE). The DTE of the chosen \
  preferred_entry_expiry MUST fall inside the band: momentum=[14,30], \
  standard=[31,44], trend=[45,75].
- headline.stance MUST be derived from headline.directional_bias for legacy \
  UI display: LONG_DELTA -> "bullish", SHORT_DELTA -> "bearish", WAIT -> "wait".
- headline.conviction MUST be exactly one of: "A", "B", "C", "D", "F".
- vrp_assessment.signal MUST be one of: "long_vol", "short_vol", "neutral".

MODE-STRUCTURE CONSISTENCY (HARD; validator will reject otherwise):
- If trade_intent == "directional_swing", preferred_expression.structure MUST \
  be in {long_call, long_put, call_debit_spread, put_debit_spread, \
  bull_call_spread, bear_put_spread, call_diagonal, put_diagonal, no_trade}. \
  iron_condor / iron_butterfly / strangle / credit_spread / calendar_spread \
  are BANNED as preferred when trade_intent=directional_swing.
- If trade_intent == "range_income", preferred_expression.structure MUST be \
  in {iron_condor, iron_butterfly, butterfly, calendar_spread, \
  call_credit_spread, put_credit_spread, no_trade}.

DELTA-MATCH (HARD):
- directional_bias = LONG_DELTA  -> preferred_expression structure MUST be \
  net-positive-delta (long_call, call_debit_spread, bull_call_spread, \
  call_diagonal).
- directional_bias = SHORT_DELTA -> net-negative-delta (long_put, \
  put_debit_spread, bear_put_spread, put_diagonal).
- directional_bias = WAIT        -> preferred_expression.structure = \
  "no_trade". The preferred_expression block then describes the CONDITIONAL \
  setup; the Scenarios section names the long/short expressions that would \
  activate.

REQUIRED STRINGS in headline (each substantive, one sentence; not a fragment):
- title (v5.2: 10-20 words, naming bias + structure + trigger level + DTE band — \
  NOT the page title "NVDA AI Analysis"; example: \
  "NVDA SHORT_DELTA bear_put_spread fires on daily close below 215, 35 DTE standard band."),
- stance_label, conviction_label, top_reason, primary_risk, watch_trigger.

section_cards has THREE required keys: market_structure, volatility, \
flow_positioning. Each MUST have title, summary (>=1 sentence of real \
analysis), data_quality, and >=1 highlight or level with a real source_path \
from the supplied payload.

vrp_assessment is REQUIRED (not null). Provide {signal, title, summary, \
metrics, reason}. When data is incomplete, set signal="neutral" and explain \
in summary/reason.

preferred_expression: provide {idea_id, structure, title, why, \
status_observed, risk_flags_observed, strike_role, legs}. \
strike_role is a nested object with {long_leg_role, short_leg_role, \
trigger_level, target_level, invalid_level, trigger_source_path, \
target_source_path, invalid_source_path}. v5.2: trigger_level / \
target_level / invalid_level MUST be a NUMERIC PRICE STRING (e.g. "215" \
or "215.00") — NOT a dict, NOT a row object from the payload.

v5.3 LEGS REQUIREMENT (HARD): preferred_expression.legs is an array of \
option legs, each {option_type: "call"|"put", side: "long"|"short", \
strike: numeric, expiry: "YYYY-MM-DD"}. Required structures: \
bear_put_spread / put_debit_spread = 2 legs (long put + short put, \
long_strike > short_strike, same expiry); bull_call_spread / \
call_debit_spread = 2 legs (long call + short call, long_strike < \
short_strike, same expiry); put_credit_spread = 2 legs (short put + \
long put, short_strike > long_strike, same expiry, DEFINED-RISK); \
call_credit_spread = 2 legs (short call + long call, short_strike < \
long_strike, same expiry, DEFINED-RISK); long_call = 1 long call; \
long_put = 1 long put. NO NAKED SHORTS — every credit-spread family MUST \
include the protective long leg. no_trade / strategy_review can have \
legs=[].

v5.3 LEGS_ALIGN_WITH_TRIGGERS (HARD): for any spread, the long leg's \
strike MUST be within 2% of either entry_trigger.level or \
thesis_trigger.level. This binds the proposed spread to the trigger \
state machine.

For estimated_entry, max_profit_observed, max_loss_observed, reward_risk: \
if entry_state=CONDITIONAL and the trigger has NOT fired, set \
status_observed="strategy_review" with blanks or the placeholder string \
"Repriced post-trigger — observed pre-trigger numerics are reference only." \
v5.2 removed the "candidate_pre_trigger" escape hatch as dead code — \
under CONDITIONAL always use strategy_review. For trade_intent= \
range_income or directional_bias=WAIT, structure="no_trade" is \
acceptable; the other fields then describe the conditional setup.

v5.3 TRIGGER COMPONENTS (HARD): emit thesis_trigger, entry_trigger, and \
invalidation as TOP-LEVEL TriggerComponent blocks on the outcome (NOT \
inside preferred_expression). Each block has {level: numeric, meaning: \
short label, fired: bool, evidence_close: numeric, evidence_date: \
"YYYY-MM-DD", source_path: "tabs.market_structure.stock_history.rows[N].spot"}. \
thesis_trigger is the level that validates the spatial archetype \
(broken put_wall for support_breakdown, broken call_wall for \
breakout_continuation). entry_trigger is the level that signals the \
actual trade entry — often the long-leg strike. invalidation is the \
level that kills the thesis. For thesis/entry, fired=true requires a \
COMPLETED daily close that crossed `level` in the relevant direction; \
intraday spot is NOT sufficient. The two triggers MAY share the same \
level but their meaning strings MUST differ.

v5.3 ENTRY_STATE DERIVATION (HARD; mechanical, validator rejects \
mismatches): entry_state = ACTIVE iff thesis_trigger.fired AND \
entry_trigger.fired AND NOT invalidation.fired. entry_state = \
CONDITIONAL iff thesis_trigger.fired AND NOT entry_trigger.fired (or \
neither fired but the setup is otherwise valid). entry_state = NO_ENTRY \
iff invalidation.fired OR directional_bias=WAIT.

TRIGGER-STRIKE CONSISTENCY (HARD; validator will reject otherwise):
- For LONG_DELTA breakouts, the spread's short leg strike MUST be STRICTLY \
  GREATER than strike_role.trigger_level. A 425/430 bull_call_spread with \
  trigger_level=430 is rejected — the short call caps payoff at the \
  trigger. Move both legs up so short sits at the next target (e.g. 435 \
  second_magnet, 440 next call wall).
- For SHORT_DELTA downside breaks, the spread's short leg strike MUST be \
  STRICTLY LESS than trigger_level.

DTE-BAND CONSISTENCY (HARD; validator will reject otherwise):
- The chosen preferred_entry_expiry's DTE must be inside the band emitted \
  in headline.dte_band: momentum=[14,30], standard=[31,44], trend=[45,75].

dominant_read MUST have all four fields populated (headline, summary, \
confidence_commentary, data_quality_commentary).

guardrails defaults: {statuses_preserved: true, risk_flags_preserved: true, \
no_executable_recommendations: true} unless you changed a candidate.

scenario_cards: 3 items with case in {"upside","base","downside"}.

required_checks: 1-2 items. rejected_ideas: 3-5 items. At least one rejected \
idea MUST cite one of: horizon_mismatch (DTE outside 14-75), mode_mismatch \
(e.g. iron_condor rejected because trade_intent=directional_swing), or \
safety_override (short_strangle / risk_reversal: undefined-risk, blocked by \
project policy).

If the supplied deterministic payload truly lacks data for a required field, \
write a brief specific placeholder ("source_reconciliation status UNKNOWN; \
treating IV magnitude as relative-shape signal") rather than leaving blank.
"""


# FRAMEWORK_DIRECTIVE — the decision-stack output contract for the `framework`
# object. Wired into the assembled system prompt alongside the embedded
# TRADE FRAMEWORK KNOWLEDGE so the model produces the full conviction-ledger
# decision stack rather than only the legacy headline/preferred_expression view.
FRAMEWORK_DIRECTIVE = """\
═══════════════════════════════════════════════════════════════════════════
FRAMEWORK DECISION STACK (populate the output's `framework` object)
═══════════════════════════════════════════════════════════════════════════

Produce a full decision stack into the output's `framework` object, in THIS
order: header -> three_axis (direction / vega / asymmetry) -> gamma ->
catalyst -> conviction -> confluence -> pitfalls -> candidates (each with
Bull/Base/Bear P/L) -> best_setup -> what_changes -> bottom_line.

BEST SETUP (TSEM counterfactual): run a counterfactual P/L across the
candidates and pick the single best one. best_setup.why_not_alternatives
MUST justify the pick versus the runners-up by name. A high internal-vs-
consensus gap => directional_defined_risk, NOT pin_vega. Use a calendar /
diagonal (the pin_vega family) ONLY when implied-move ÷ distance-to-short-
strike <= ~0.75.

ASSERTIVE BUT HONEST: commit to exactly ONE best_setup. Any factor with no
data is status:"na" — never bluffed. When core inputs (tape / flow / IV)
are absent => header.position_type:"stand_aside" and conviction prose
"insufficient data".

EARNINGS (swing-default, LEAPS-aware): decide catalyst.handling FIRST,
against a fixed pre-structure ~10-14 day hold window — set
catalyst.handling to "exit_before_print" or "stand_aside" when the earnings
date falls inside that window; use "hold_through_leaps" ONLY when
position_type:"leaps". THEN choose a best_setup consistent with that
handling.

DEFINED-RISK ONLY: every candidates[] entry and best_setup MUST be
defined-risk. No naked shorts.

CONVICTION LEDGER (EXACTLY the 8 canonical factors below, emitted in THIS
order with these VERBATIM names; an absent or unsourceable factor is
status:"na", NEVER a bluffed "yes"):
  1. "3+ independent channel checks aligned bullish" — always na (out of scope).
  2. "Sector / thematic narrative actively re-rating" — yes/no from news/flow else na.
  3. "Stock down >20% from recent high (de-risked setup)" — from tape drawdown-from-6M-high.
  4. "Past 4 quarters: >=3 positive earnings reactions" — from earnings history.
  5. "NEW information likely to be disclosed (new customer tier/product/guide raise/M&A)" — usually na (whisper/channel).
  6. "Net options flow back-month bullish (call-premium dominance, 5-day rolling)" — from flow_series.
  7. "Short interest >10% (squeeze potential)" — from positioning SI% float.
  8. "Implied move materially below recent realized average" — from vol IV-vs-RV.
Factors 1 and 5 are structurally na under our data scope => realistic
ceiling ~6/8. header.conviction_n MUST equal conviction.score MUST equal
the count of conviction.factors with status:"yes" (so score is 0..8).
asymmetry.rule_on MUST equal (conviction.score >= 4) in both directions.

POSITION TYPE GATE: header.position_type:"stand_aside" if and only if
best_setup.structure:"stand_aside".

CANDIDATE NAMING: each candidates[].name MUST be a GENERIC strategy
identifier (e.g. "bull put spread", "call debit spread", "iron condor") —
put all strikes / expirations / ratios in the legs array, NOT in the name.
best_setup.structure echoes the chosen candidate's name EXACTLY (or the
literal "stand_aside").
"""
