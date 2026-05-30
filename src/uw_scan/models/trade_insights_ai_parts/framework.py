"""Trade Framework (v6.0) contract — the ported trade-skills decision stack.

Additive block on TradeInsightAiOutcome. Prose fields are intentionally
unvalidated (free narrative). Structural invariants (conviction bounds,
defined-risk, best_setup<->candidates linkage) are enforced by
reports/trade_insights_ai/validator_rules/framework.py, not here.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .base import (
    FrameworkCatalystHandling,
    FrameworkDirectionVerdict,
    FrameworkFactorStatus,
    FrameworkGammaRegime,
    FrameworkPositionType,
    FrameworkStructureFamily,
    FrameworkVegaRegime,
    TradeInsightAiBase,
)


class TradeFrameworkHeader(TradeInsightAiBase):
    thesis_one_liner: str
    position_type: FrameworkPositionType
    spot: Decimal | None = None
    conviction_n: int = Field(
        ge=0, le=8
    )  # canonical == conviction.score (validator-enforced)


class TradeFrameworkDirection(TradeInsightAiBase):
    verdict: FrameworkDirectionVerdict
    prose: str


class TradeFrameworkVega(TradeInsightAiBase):
    regime: FrameworkVegaRegime
    ivr: Decimal | None = None
    term_slope: str | None = None
    prose: str


class TradeFrameworkAsymmetry(TradeInsightAiBase):
    rule_on: bool
    structure_family: FrameworkStructureFamily
    prose: str


class TradeFrameworkThreeAxis(TradeInsightAiBase):
    direction: TradeFrameworkDirection
    vega: TradeFrameworkVega
    asymmetry: TradeFrameworkAsymmetry


class TradeFrameworkGamma(TradeInsightAiBase):
    regime: FrameworkGammaRegime
    flip_strike: Decimal | None = None
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    prose: str


class TradeFrameworkCatalyst(TradeInsightAiBase):
    next_er_date: str | None = None
    dte_to_er: int | None = None
    implied_move: Decimal | None = None
    handling: FrameworkCatalystHandling
    prose: str


class TradeFrameworkFactor(TradeInsightAiBase):
    name: str
    status: FrameworkFactorStatus
    note: str = ""


class TradeFrameworkConviction(TradeInsightAiBase):
    score: int = Field(ge=0, le=8)
    # Exactly the 8 canonical bull-conviction factors (KB strategies.md / pitfall 24).
    # min/max 8 surfaces as minItems/maxItems in the strict schema so Codex/DeepSeek
    # emit all 8; the leniency layer pads missing canonical factors as `na` before
    # Claude output is validated. `score` counts only `yes` -> the N/8 denominator is fixed.
    factors: list[TradeFrameworkFactor] = Field(min_length=8, max_length=8)
    prose: str = ""


class TradeFrameworkSignal(TradeInsightAiBase):
    name: str
    direction: str


class TradeFrameworkConfluence(TradeInsightAiBase):
    aligned: bool
    signals: list[TradeFrameworkSignal] = Field(default_factory=list)
    prose: str = ""


class TradeFrameworkPitfall(TradeInsightAiBase):
    id: str
    title: str
    triggered: bool
    note: str = ""


class TradeFrameworkCandidate(TradeInsightAiBase):
    name: str
    legs: list[str] = Field(default_factory=list)
    debit_credit: str | None = None
    net_delta: Decimal | None = None
    net_vega: Decimal | None = None
    pnl_bull: str | None = None
    pnl_base: str | None = None
    pnl_bear: str | None = None
    defined_risk: bool


class TradeFrameworkBestSetup(TradeInsightAiBase):
    structure: (
        str  # a candidates[].name OR the literal "stand_aside" (validator-checked)
    )
    legs: list[str] = Field(default_factory=list)
    # cost / max_risk / pnl_* are intentionally expressive STRINGS, not Decimal: the
    # trade-skills counterfactual style uses ranges/multiples ("~97%", "2-3x", "$1.20
    # debit", "capped +$380") — central to the TSEM lesson. The machine-checked safety
    # property is `candidates[].defined_risk: bool` (no naked shorts), not a parsed number.
    cost: str | None = None
    max_risk: str | None = None
    rationale: str
    why_not_alternatives: str = ""
    invalidation: str


class TradeFrameworkWhatChanges(TradeInsightAiBase):
    signal: str
    effect: str


class TradeFramework(TradeInsightAiBase):
    header: TradeFrameworkHeader
    three_axis: TradeFrameworkThreeAxis
    gamma: TradeFrameworkGamma
    catalyst: TradeFrameworkCatalyst
    conviction: TradeFrameworkConviction
    confluence: TradeFrameworkConfluence
    pitfalls: list[TradeFrameworkPitfall] = Field(default_factory=list)
    candidates: list[TradeFrameworkCandidate] = Field(default_factory=list)
    best_setup: TradeFrameworkBestSetup
    what_changes: list[TradeFrameworkWhatChanges] = Field(default_factory=list)
    bottom_line: str
