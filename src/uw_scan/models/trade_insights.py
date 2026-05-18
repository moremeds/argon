"""Deterministic Trade Insights response contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal

from ._base import _UwBase, _preserve_public_module


class InsightBadge(_UwBase):
    code: str
    label: str
    severity: str = "info"

class TradeInsightsHeader(_UwBase):
    dominant_bias: str = "NEUTRAL"
    primary_setup: str = "NO_CLEAR_SETUP"
    confidence_label: str = "LOW"
    data_quality_label: str = "INSUFFICIENT"
    idea_count: int = 0
    preferred_idea_id: str | None = None
    badges: list[InsightBadge] = []

class SourceReconciliationRow(_UwBase):
    source_pair: str
    price_agreement: str = ""
    iv_agreement: str = ""
    decision: str = ""
    strike: Decimal | None = None
    source_a_call_iv: Decimal | None = None
    source_b_call_iv: Decimal | None = None
    iv_diff: Decimal | None = None

class SourceReconciliation(_UwBase):
    status: str = "UNKNOWN"
    headline: str = "Source reconciliation unavailable"
    primary_iv_source: str | None = None
    relative_shape_source: str | None = None
    rows: list[SourceReconciliationRow] = []
    decision: str = "Use deterministic data only where source agreement is understood."

class InsightSignalRow(_UwBase):
    lens: str
    read: str
    evidence: list[str] = []
    conflicts: list[str] = []

class ChainFlowReadRow(_UwBase):
    strike: Decimal
    call_volume: int | None = None
    call_open_interest: int | None = None
    put_volume: int | None = None
    put_open_interest: int | None = None
    call_put_volume_ratio: Decimal | None = None
    volume_oi_note: str = ""
    read: str = ""
    requires_t1_oi_confirmation: bool = False

class TermMoveRow(_UwBase):
    expiry: _date
    dte: int | None = None
    atm_straddle: Decimal | None = None
    implied_move_perc: Decimal | None = None
    daily_implied_move_perc: Decimal | None = None
    read: str = ""

class InsightLeg(_UwBase):
    side: str
    option_symbol: str
    option_right: str
    expiry: _date
    strike: Decimal
    mid: Decimal | None = None

class CandidateStructure(_UwBase):
    idea_id: str
    structure: str
    thesis: str
    expression_type: str
    legs: list[InsightLeg] = []
    net_credit_debit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = []
    profit_zone: str = ""
    edge_source: str = ""
    risk_flags: list[str] = []
    rank: int
    status: str = "candidate"

class InsightsSynthesis(_UwBase):
    dominant_story: str = ""
    preferred_idea_id: str | None = None
    best_risk_reward_idea_id: str | None = None
    avoid: list[str] = []
    required_before_sizing: list[str] = []

class TradeInsightsResponse(_UwBase):
    ticker: str
    as_of: datetime | None = None
    mode: str = "research"
    header: TradeInsightsHeader
    source_reconciliation: SourceReconciliation = SourceReconciliation()
    signal_stack: list[InsightSignalRow] = []
    flow_table: list[ChainFlowReadRow] = []
    term_structure_table: list[TermMoveRow] = []
    candidate_structures: list[CandidateStructure] = []
    synthesis: InsightsSynthesis = InsightsSynthesis()


_preserve_public_module(
    InsightBadge,
    TradeInsightsHeader,
    SourceReconciliationRow,
    SourceReconciliation,
    InsightSignalRow,
    ChainFlowReadRow,
    TermMoveRow,
    InsightLeg,
    CandidateStructure,
    InsightsSynthesis,
    TradeInsightsResponse,
)
