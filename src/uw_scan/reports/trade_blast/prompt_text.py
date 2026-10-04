"""Static prompt text and vocabulary constants for Trade Insights AI.

Holds the v5.2 (and onward) MARKET_INTELLIGENCE_PROMPT plus every immutable
vocabulary tuple / frozenset the schema, validators, and lenient coercer
share. Pure data — no I/O, no helpers that touch the DB.

The blast lane assembles its prompt from the shared trade_insights_ai
fragments — the base lane owns the shared wording exactly once — and
substitutes only its own deltas (the worked example, the qualitative-
likelihood scenario table, and the framework decision-stack directive)
so the shared wording can never drift between lanes.
"""

from __future__ import annotations

from uw_scan.reports._shared_validation.constants import (  # noqa: F401
    DIRECTIONAL_BIAS_VALUES,
    DIRECTIONAL_SWING_STRUCTURES,
    DTE_BAND_RANGES,
    DTE_BAND_VALUES,
    ENTRY_STATE_VALUES,
    FINAL_RATING_VALUES,
    PREFERRED_STRATEGY_FAMILY_IDS,
    RANGE_INCOME_STRUCTURES,
    STRATEGY_FAMILY_IDS,
    TRADE_INTENT_VALUES,
    UNDERLYING_PATH_VALUES,
)
from uw_scan.reports.trade_insights_ai.prompt_text import (
    CONTRACT_PROMPT,  # noqa: F401
    _MARKET_INTELLIGENCE_BODY,
    _MARKET_INTELLIGENCE_HEAD,
    _MARKET_INTELLIGENCE_TAIL,
)

from .trade_framework_kb import TRADE_FRAMEWORK_KNOWLEDGE  # noqa: F401

PROMPT_VERSION = "trade-blast-v2"

# M6 blast-only insertion between the shared head and body fragments: the
# v5.3 NVDA / TSLA worked example that teaches the trigger-state machine.
_MARKET_INTELLIGENCE_WORKED_EXAMPLE = """    WORKED EXAMPLE (the v5.3 NVDA / TSLA failure mode):
      Setup: support_breakdown thesis. Put wall at 440 was broken on
      2026-05-22 close at 437.50 (thesis_trigger.fired = TRUE). The plan
      is to enter the bear_put_spread on a confirming close below 435
      (entry_trigger.level = 435). Latest completed close 2026-05-29 =
      435.79 — above 435, so entry_trigger.fired = FALSE.

      Correct emission:
        thesis_trigger.fired = TRUE
        entry_trigger.fired  = FALSE
        invalidation.fired   = FALSE
        headline.entry_state = "CONDITIONAL"   <- NOT "ACTIVE"
        headline.watch_trigger names the unfired entry_trigger level

      Common mistake: emitting entry_state="ACTIVE" because the thesis is
      confirmed and the spread "looks ready." If entry has not fired on a
      COMPLETED daily close, the trade is CONDITIONAL — full stop. The
      validator will overwrite ACTIVE -> CONDITIONAL with an auto-correct
      note, but the model should not depend on the safety net.

"""

# M6 blast-only substitution for the base lane's numeric-probability
# scenario table — qualitative buckets tied to directional_bias.
_MARKET_INTELLIGENCE_SCENARIOS = """## Scenarios (exactly 3 rows: upside, base, downside)

| Scenario | Likelihood | Trigger (daily close) | Level | Best expression |
|---|---|---|---|---|
| upside   | <one of: primary, plausible, tail> | | named level | mode-whitelisted directional structure |
| base     | <one of: primary, plausible, tail> | | named level | mode-whitelisted directional structure |
| downside | <one of: primary, plausible, tail> | | named level | mode-whitelisted directional structure |

Likelihood vocabulary (pick exactly one per scenario):
  - "primary"   — the path you expect to play out
  - "plausible" — a credible alternative the evidence supports
  - "tail"      — possible but not the dominant read

EXACTLY ONE scenario is "primary." The "primary" scenario must
correspond to the directional_bias chosen at Step 2. Do NOT emit
numeric percentages — we cannot calibrate them and presenting
"45%" as a precise estimate is a fake-precision pitfall. The
qualitative bucket is the honest signal.

"""


MARKET_INTELLIGENCE_PROMPT = (
    _MARKET_INTELLIGENCE_HEAD
    + _MARKET_INTELLIGENCE_WORKED_EXAMPLE
    + _MARKET_INTELLIGENCE_BODY
    + _MARKET_INTELLIGENCE_SCENARIOS
    + _MARKET_INTELLIGENCE_TAIL
)


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

EARNINGS (swing-default, LEAPS-aware): decide catalyst.handling FIRST
against a fixed pre-structure ~10-14 day hold window. The four values:
  - "no_conflict"       — earnings is absent OR dte_to_er > hold window
                          (no event risk in the trade horizon). DEFAULT
                          when next_er_date is None or far in the future.
                          ALLOWED to pair with any best_setup.
  - "exit_before_print" — earnings is inside the hold window AND you
                          intend to close the trade before the print.
  - "stand_aside"       — earnings is inside the hold window AND the
                          event risk eliminates the trade entirely.
                          MUST pair with best_setup.structure="stand_aside".
  - "hold_through_leaps"— position_type="leaps" only.
THEN choose a best_setup consistent with that handling.

Common mistake: do NOT emit "stand_aside" when there is no actual
conflict — that's what "no_conflict" is for. "stand_aside" is reserved
for genuine no-trade conditions where event risk kills the setup.

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
