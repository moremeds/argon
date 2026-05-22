"""Trade Insights AI request, response, and outcome contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import _preserve_public_module


class TradeInsightAiBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


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
    dominant_read: TradeInsightAiDominantRead
    best_expressions: list[TradeInsightAiBestExpression] = Field(default_factory=list)
    conflicts: list[TradeInsightAiConflict] = Field(default_factory=list)
    required_checks: list[TradeInsightAiRequiredCheck] = Field(default_factory=list)
    rejected_ideas: list[TradeInsightAiRejectedIdea] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rendering: TradeInsightAiRendering
    guardrails: TradeInsightAiGuardrails


TradeInsightAiProvider = Literal["codex", "claude"]


class TradeInsightAiAnalysisRequest(TradeInsightAiBase):
    force_rerun: bool = False


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


class TradeInsightAiLatestPair(TradeInsightAiBase):
    """GET /latest response — null per provider when no succeeded row exists."""

    codex: TradeInsightAiAnalysisResponse | None = None
    claude: TradeInsightAiAnalysisResponse | None = None


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
)
