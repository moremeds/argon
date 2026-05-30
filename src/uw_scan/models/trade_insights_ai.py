"""Trade Insights AI request, response, and outcome contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from ._base import _preserve_public_module
from .trade_insights_ai_parts.base import (
    AntiPinDirection,
    ConsensusGrade,
    DirectionalBias,
    DteBand,
    EntryState,
    LongLegRole,
    OptionSide,
    OptionType,
    ShortLegRole,
    ThesisArchetype,
    TradeInsightAiBase,
    TradeInsightAiProvider,
    TradeIntent,
    UnderlyingPath,
)
from .trade_insights_ai_parts.framework import (
    TradeFramework,
    TradeFrameworkAsymmetry,
    TradeFrameworkBestSetup,
    TradeFrameworkCandidate,
    TradeFrameworkCatalyst,
    TradeFrameworkConfluence,
    TradeFrameworkConviction,
    TradeFrameworkDirection,
    TradeFrameworkFactor,
    TradeFrameworkGamma,
    TradeFrameworkHeader,
    TradeFrameworkPitfall,
    TradeFrameworkSignal,
    TradeFrameworkThreeAxis,
    TradeFrameworkVega,
    TradeFrameworkWhatChanges,
)


class TradeInsightAiDominantRead(TradeInsightAiBase):
    headline: str
    summary: str
    confidence_commentary: str
    data_quality_commentary: str


class TradeInsightAiSnapshotMeta(TradeInsightAiBase):
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    data_as_of: str | None = None
    freshness_label: str = "unknown"
    source_notes: list[str] = Field(default_factory=list)


class TradeInsightAiHeadline(TradeInsightAiBase):
    # v5 directional fields — the actual decision the swing trader makes.
    # `directional_bias` is the gate; `stance` is kept for UI/markdown display
    # and is auto-derived in the lenient coercer when the model omits it.
    trade_intent: TradeIntent
    directional_bias: DirectionalBias
    entry_state: EntryState
    underlying_path: UnderlyingPath
    dte_band: DteBand
    # v5.2: thesis archetype is the spatial commit the model must make
    # alongside underlying_path. resistance_rejection vs support_breakdown
    # produce the same DIRECTIONAL bias but materially different management
    # logic, so the prompt forces a commit and the validator can check
    # archetype↔path consistency.
    thesis_archetype: ThesisArchetype = "data_insufficient"
    title: str
    stance: Literal["bullish", "bearish", "neutral", "mixed", "wait"]
    stance_label: str
    score: int
    score_scale: int = 100
    conviction: str
    conviction_label: str
    top_reason: str
    primary_risk: str
    watch_trigger: str


class TradeInsightAiMetricCard(TradeInsightAiBase):
    label: str
    value: str
    tone: str = "neutral"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiScenarioCard(TradeInsightAiBase):
    case: Literal["upside", "base", "downside"] | str
    tone: str = "neutral"
    title: str
    description: str


class TradeInsightAiScoreBreakdown(TradeInsightAiBase):
    section: str
    score: int
    max_score: int
    summary: str


class TradeInsightAiHighlight(TradeInsightAiBase):
    label: str
    value: str
    source_path: str | None = None
    note: str = ""


class TradeInsightAiLevel(TradeInsightAiBase):
    price: str
    kind: str
    value: str
    importance: str = "normal"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiSectionCard(TradeInsightAiBase):
    title: str
    score: int | None = None
    max_score: int | None = None
    summary: str
    highlights: list[TradeInsightAiHighlight] = Field(default_factory=list)
    levels: list[TradeInsightAiLevel] = Field(default_factory=list)
    data_quality: str = "unknown"


class TradeInsightAiSectionCards(TradeInsightAiBase):
    market_structure: TradeInsightAiSectionCard
    volatility: TradeInsightAiSectionCard
    flow_positioning: TradeInsightAiSectionCard


class TradeInsightAiVrpAssessment(TradeInsightAiBase):
    signal: str
    title: str
    summary: str
    metrics: list[TradeInsightAiMetricCard] = Field(default_factory=list)
    reason: str


def _coerce_strike_level(value: Any) -> Decimal | None:
    """v5.2: pre-validator for strike_role level fields.

    Accepts:
      - Decimal / int / float / numeric-string ("215", "215.00", "$215")
      - dict-like objects that contain a 'strike' / 'price' / 'level' key
        (this is the v5.1 Claude failure mode — the model pasted the
        entire strike-curve row instead of just the strike price)

    Rejects:
      - None / empty string (returns None — field is optional)
      - lists, complex objects without a recognized strike key

    The return type is Decimal | None; downstream validators treat None
    as "model declined to populate" (legal for data_insufficient or WAIT)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip().lstrip("$").replace(",", "")
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation as exc:
            _ = repr(exc)
            raise ValueError(
                f"strike_role level cannot parse string {value!r} as a price"
            ) from exc
    if isinstance(value, dict):
        for key in ("strike", "price", "level"):
            if key in value:
                inner = value[key]
                try:
                    return Decimal(str(inner))
                except (InvalidOperation, ValueError, TypeError) as exc:
                    _ = repr(exc)
                    raise ValueError(
                        f"strike_role level dict had {key}={inner!r} which is not numeric"
                    ) from exc
        raise ValueError(
            f"strike_role level dict had no strike/price/level key: keys={list(value.keys())}"
        )
    raise ValueError(
        f"strike_role level must be numeric, string, or dict with strike key; got {type(value).__name__}"
    )


class TradeInsightAiStrikeRole(TradeInsightAiBase):
    """v5.2: explicit market-structure roles + Decimal-strict price levels.

    Levels were strings in v5.1; that let Claude emit nested dicts which
    Pydantic silently stringified and rendered as JSON literals in the UI.
    v5.2 coerces to Decimal via a pre-validator that knows how to extract
    the strike key from a dict.

    Source paths are optional but encouraged so the UI can attribute each
    level to a specific key in the deterministic payload."""

    long_leg_role: LongLegRole = "n/a"
    short_leg_role: ShortLegRole = "n/a"
    trigger_level: Decimal | None = None
    target_level: Decimal | None = None
    invalid_level: Decimal | None = None
    trigger_source_path: str = ""
    target_source_path: str = ""
    invalid_source_path: str = ""

    @field_validator("trigger_level", "target_level", "invalid_level", mode="before")
    @classmethod
    def _coerce_levels(cls, value: Any) -> Decimal | None:
        return _coerce_strike_level(value)


class TradeInsightAiTriggerEvidence(TradeInsightAiBase):
    """v5.2: payload-proven trigger fire evidence.

    The deterministic ACTIVE_TRIGGER_EVIDENCE_RULE check uses these fields
    to verify that entry_state=ACTIVE is justified by an actual completed
    daily close in the payload — not by intraday spot or model inference.

    trigger_fired=False is the default; the lenient coercer fills this in
    by reading the latest completed stock_history row and comparing its
    close to strike_role.trigger_level.

    When trigger_fired=False but the model emitted entry_state=ACTIVE,
    the validator rejects (or auto-downgrades) to CONDITIONAL."""

    trigger_fired: bool = False
    trigger_type: Literal["daily_close", "two_session_hold", "unknown"] = "unknown"
    trigger_level: Decimal | None = None
    evidence_close: Decimal | None = None
    evidence_close_date: date | None = None
    source_path: str = ""

    @field_validator("trigger_level", "evidence_close", mode="before")
    @classmethod
    def _coerce_decimals(cls, value: Any) -> Decimal | None:
        return _coerce_strike_level(value)


class TradeInsightAiAntiPin(TradeInsightAiBase):
    """v5.2: structured anti-pin score + scope tag.

    invoked=False means anti-pin is not the thesis (e.g. structural break
    or trend continuation). The validator's conviction cap (cap at C when
    2/4 hold, anti-pin doesn't fire when ≤1/4) ONLY applies when
    invoked=True. This closes the v5.1 issue where Claude scored 1/4 on
    NVDA but correctly chose downside_break — anti-pin scoring should
    have been informational only, not a conviction blocker."""

    invoked: bool = False
    direction: AntiPinDirection = "none"
    score: int = 0
    max_score: int = 4
    conditions_met: list[str] = Field(default_factory=list)
    conviction_cap_applied: bool = False
    cap_reason: str = ""


class TradeInsightAiTargetFeasibility(TradeInsightAiBase):
    """v5.2: target-distance vs expected-move sanity layer.

    Optional — when expected_move data is missing from the payload the
    feasibility is 'missing' and the validator does not block. When
    present, this surfaces whether the target is realistic within the
    5-10 session hold."""

    distance_to_target_pct: Decimal | None = None
    expected_move_available: bool = False
    expected_move_source_path: str = ""
    feasibility: Literal["inside_expected_move", "outside_expected_move", "missing"] = (
        "missing"
    )

    @field_validator("distance_to_target_pct", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Decimal | None:
        return _coerce_strike_level(value)


class TradeInsightAiProviderConsensus(TradeInsightAiBase):
    """v5.2: cross-provider agreement signal computed at GET /latest time.

    Not stored per row — derived by comparing the two providers' headline
    fields whenever both have a succeeded row. Surfaces actionable
    disagreement to the operator (e.g. "ACTIVE vs CONDITIONAL depends on
    whether the latest daily close cleared 215")."""

    bias_agreement: bool = False
    structure_agreement: bool = False
    entry_state_agreement: bool = False
    path_agreement: bool = False
    dte_band_agreement: bool = False
    consensus_grade: ConsensusGrade = "missing"
    actionable_disagreement: str = ""


class TradeInsightAiTriggerComponent(TradeInsightAiBase):
    """v5.3: a single point on the trade's state machine.

    The v5.2 schema overloaded `trigger_level` across two distinct
    semantics (NVDA Codex emitted 220 as "broken wall — already fired",
    Claude emitted 215 as "continuation entry — not yet fired"), which
    is why providers split on ENTRY_STATE despite agreeing on archetype
    and direction. v5.3 decomposes that into three required components —
    `thesis_trigger`, `entry_trigger`, `invalidation` — each carrying its
    own level, semantic meaning, and `fired` boolean evaluated against
    actual daily-close evidence. ENTRY_STATE becomes a mechanical
    function of the trigger booleans rather than a model judgment.

    Both `thesis_trigger` and `entry_trigger` may share the same level
    when the trade plan treats the broken wall as both the thesis
    confirmation AND the entry signal — but their `meaning` strings
    must differ, and their `fired` booleans are evaluated independently
    against their own evidence rules.
    """

    level: Decimal | None = None
    meaning: str = ""
    fired: bool = False
    evidence_close: Decimal | None = None
    evidence_date: date | None = None
    source_path: str = ""

    @field_validator("level", "evidence_close", mode="before")
    @classmethod
    def _coerce_decimals(cls, value: Any) -> Decimal | None:
        return _coerce_strike_level(value)


class TradeInsightAiOptionLeg(TradeInsightAiBase):
    """v5.3: one leg of a defined-risk option expression.

    Replaces v5.2's implicit "trigger_level + long_leg_role + short_leg_role"
    coupling with explicit, validator-checkable leg geometry. The
    legs-strategy-match validator enforces, e.g., that a bear_put_spread
    has exactly one long put + one short put with long.strike > short.strike
    and matching expiry. The legs-align-triggers validator enforces that
    the long leg's strike is within tolerance of entry_trigger.level OR
    thesis_trigger.level — making "is the actual long-put strike 215 or
    220?" a falsifiable claim against the model output.

    No naked shorts: per project safety policy, credit-spread families
    must always include the long protective leg. The validator rejects
    a single-leg short.
    """

    option_type: OptionType
    side: OptionSide
    strike: Decimal
    expiry: date

    @field_validator("strike", mode="before")
    @classmethod
    def _coerce_strike(cls, value: Any) -> Decimal:
        coerced = _coerce_strike_level(value)
        if coerced is None:
            raise ValueError("option leg strike is required and must be numeric")
        return coerced


class TradeInsightAiPreferredExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    title: str
    subtitle: str = ""
    estimated_entry: str = ""
    max_profit_observed: str = ""
    max_loss_observed: str = ""
    reward_risk: str = ""
    why: str
    management_notes: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)
    # v5.1: strike-role + trigger/target/invalid levels. Optional for backwards
    # compatibility during the migration; the validator+coercer fills it in
    # from candidate_structures when the model omits it.
    strike_role: TradeInsightAiStrikeRole = Field(
        default_factory=TradeInsightAiStrikeRole
    )
    # v5.3: explicit option legs. Empty list is valid for
    # status_observed='strategy_review' / structure='no_trade'; the
    # legs-strategy-match validator enforces structure-specific leg
    # geometry when the list is non-empty.
    legs: list[TradeInsightAiOptionLeg] = Field(default_factory=list)


class TradeInsightAiBestExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    role: str
    why: str
    caveats: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)


class TradeInsightAiConflict(TradeInsightAiBase):
    lens: str
    severity: str
    description: str
    affected_idea_ids: list[str] = Field(default_factory=list)


class TradeInsightAiRequiredCheck(TradeInsightAiBase):
    check: str
    reason: str
    blocks_sizing: bool = True
    source: str = ""


class TradeInsightAiRejectedIdea(TradeInsightAiBase):
    idea_id: str
    structure: str
    reason: str


class TradeInsightAiRendering(TradeInsightAiBase):
    disclaimer: str
    card_order: list[str] = Field(default_factory=list)


class TradeInsightAiGuardrails(TradeInsightAiBase):
    statuses_preserved: bool
    risk_flags_preserved: bool
    no_executable_recommendations: bool


class TradeInsightAiOutcome(TradeInsightAiBase):
    schema_version: str
    analysis_produced_at: datetime
    ticker: str
    underlying_price: str | None = None
    snapshot: TradeInsightAiSnapshotMeta
    headline: TradeInsightAiHeadline
    metric_cards: list[TradeInsightAiMetricCard]
    scenario_cards: list[TradeInsightAiScenarioCard]
    score_breakdown: list[TradeInsightAiScoreBreakdown]
    section_cards: TradeInsightAiSectionCards
    vrp_assessment: TradeInsightAiVrpAssessment | None = None
    preferred_expression: TradeInsightAiPreferredExpression | None = None
    # v5.2: structured trigger/anti-pin/feasibility blocks. Optional —
    # the lenient coercer fills them in from the deterministic payload
    # when the model omits them. The validator's ACTIVE_TRIGGER_EVIDENCE
    # check reads trigger_evidence; the anti_pin scope check reads
    # anti_pin.invoked.
    trigger_evidence: TradeInsightAiTriggerEvidence = Field(
        default_factory=TradeInsightAiTriggerEvidence
    )
    anti_pin: TradeInsightAiAntiPin = Field(default_factory=TradeInsightAiAntiPin)
    target_feasibility: TradeInsightAiTargetFeasibility = Field(
        default_factory=TradeInsightAiTargetFeasibility
    )
    # v5.3: decomposed trigger state machine. ENTRY_STATE is mechanically
    # derived from these three components — see the v5.3 prompt for the
    # truth table. Optional with defaults so v5.2 outcomes still parse
    # (the lenient coercer populates v5.3 fields from v5.2 inputs where
    # possible: trigger_evidence.trigger_level/evidence_close → thesis_trigger,
    # strike_role.invalid_level → invalidation).
    thesis_trigger: TradeInsightAiTriggerComponent = Field(
        default_factory=TradeInsightAiTriggerComponent
    )
    entry_trigger: TradeInsightAiTriggerComponent = Field(
        default_factory=TradeInsightAiTriggerComponent
    )
    invalidation: TradeInsightAiTriggerComponent = Field(
        default_factory=TradeInsightAiTriggerComponent
    )
    dominant_read: TradeInsightAiDominantRead
    best_expressions: list[TradeInsightAiBestExpression] = Field(default_factory=list)
    conflicts: list[TradeInsightAiConflict] = Field(default_factory=list)
    required_checks: list[TradeInsightAiRequiredCheck] = Field(default_factory=list)
    rejected_ideas: list[TradeInsightAiRejectedIdea] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rendering: TradeInsightAiRendering
    guardrails: TradeInsightAiGuardrails
    framework: TradeFramework | None = None


class TradeInsightAiAnalysisRequest(TradeInsightAiBase):
    force_rerun: bool = False
    # Optional per-provider filter. None = all enabled providers (legacy behavior).
    # Lets the UI re-run a single provider without affecting an in-flight peer
    # (e.g. claude can re-run while a hung codex row is still pending).
    providers: list[TradeInsightAiProvider] | None = None


class TradeInsightAiAnalysisResponse(TradeInsightAiBase):
    analysis_id: UUID
    ticker: str
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    model: str
    provider: TradeInsightAiProvider = "codex"
    prompt_version: str
    status: Literal["queued", "running", "succeeded", "failed"]
    produced_at: datetime | None = None
    outcome: TradeInsightAiOutcome | None = None
    markdown: str | None = None
    error_message: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reused: bool = False


class TradeInsightAiAnalysisStub(TradeInsightAiBase):
    """Lightweight stub returned by POST when enqueueing per-provider rows."""

    provider: TradeInsightAiProvider
    analysis_id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    reused: bool
    model: str


class TradeInsightAiAnalysisEnqueueResponse(TradeInsightAiBase):
    """POST response — one stub per enabled provider."""

    analyses: list[TradeInsightAiAnalysisStub]


class TradeInsightAiPriorRow(TradeInsightAiBase):
    """One row from the trade_insight_provider_archetype_priors view.

    Surfaced by /api/trade-insights/priors. `hit_rate_pct` is computed
    over RESOLVED outcomes only (excludes pending + expired_no_resolution)
    so an all-pending cohort doesn't appear as a 0% hit rate. NULL when
    no outcomes have resolved yet.
    """

    provider: TradeInsightAiProvider
    prompt_version: str
    thesis_archetype: str | None = None
    directional_bias: str | None = None
    entry_state: str | None = None
    sample_count: int
    target_hit_count: int
    invalidation_hit_count: int
    pending_count: int
    expired_no_resolution_count: int
    hit_rate_pct: Decimal | None = None
    median_days_to_resolution: Decimal | None = None


class TradeInsightAiPriorsResponse(TradeInsightAiBase):
    """Wrapper so the endpoint can grow filter metadata + a `priors` list
    without a breaking change."""

    priors: list[TradeInsightAiPriorRow] = Field(default_factory=list)


class TradeInsightAiLatestPair(TradeInsightAiBase):
    """GET /latest response — null per provider when no succeeded row exists.

    v5.2: provider_consensus is computed at read time by comparing the
    two providers' headline fields whenever both have succeeded. The
    UI surfaces consensus_grade + actionable_disagreement above the
    [Codex] [Claude] tabs as a quality signal.

    v5.3 (deepseek-decoupling, 2026-05-28): adds the deepseek slot.
    DeepSeek surfaces in /latest but DOES NOT participate in
    provider_consensus — that remains a 2-way codex-vs-claude comparison
    (see _compute_provider_consensus docstring for the scope decision).
    The UI still renders only [Codex] [Claude] tabs; the deepseek field
    is queued + persisted today and ignored by the frontend until a
    follow-up PR adds a [DeepSeek] tab."""

    current_prompt_version: str
    current_prompt_label: str | None = None
    codex: TradeInsightAiAnalysisResponse | None = None
    claude: TradeInsightAiAnalysisResponse | None = None
    deepseek: TradeInsightAiAnalysisResponse | None = None
    provider_consensus: TradeInsightAiProviderConsensus = Field(
        default_factory=TradeInsightAiProviderConsensus
    )


_preserve_public_module(
    TradeInsightAiBase,
    TradeInsightAiDominantRead,
    TradeInsightAiSnapshotMeta,
    TradeInsightAiHeadline,
    TradeInsightAiMetricCard,
    TradeInsightAiScenarioCard,
    TradeInsightAiScoreBreakdown,
    TradeInsightAiHighlight,
    TradeInsightAiLevel,
    TradeInsightAiSectionCard,
    TradeInsightAiSectionCards,
    TradeInsightAiVrpAssessment,
    TradeInsightAiStrikeRole,
    TradeInsightAiTriggerEvidence,
    TradeInsightAiAntiPin,
    TradeInsightAiTargetFeasibility,
    TradeInsightAiProviderConsensus,
    TradeInsightAiTriggerComponent,
    TradeInsightAiOptionLeg,
    TradeInsightAiPreferredExpression,
    TradeInsightAiBestExpression,
    TradeInsightAiConflict,
    TradeInsightAiRequiredCheck,
    TradeInsightAiRejectedIdea,
    TradeInsightAiRendering,
    TradeInsightAiGuardrails,
    TradeInsightAiOutcome,
    TradeInsightAiAnalysisRequest,
    TradeInsightAiAnalysisResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiLatestPair,
    TradeInsightAiPriorRow,
    TradeInsightAiPriorsResponse,
    TradeFramework,
    TradeFrameworkHeader,
    TradeFrameworkThreeAxis,
    TradeFrameworkDirection,
    TradeFrameworkVega,
    TradeFrameworkAsymmetry,
    TradeFrameworkGamma,
    TradeFrameworkCatalyst,
    TradeFrameworkConviction,
    TradeFrameworkFactor,
    TradeFrameworkConfluence,
    TradeFrameworkSignal,
    TradeFrameworkPitfall,
    TradeFrameworkCandidate,
    TradeFrameworkBestSetup,
    TradeFrameworkWhatChanges,
)
