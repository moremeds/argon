"""Pydantic response schemas for /regime/canary endpoints.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §10.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Literal

from pydantic import BaseModel

Band = Literal["NONE", "WATCH", "BUY", "STRONG_BUY"]
WarningState = Literal[
    "NONE",
    "CONFIRMED_CANARY_ACTIVE",
    "BUY_THE_DIP_ACTIVE",
    "BOTH_ACTIVE_AMBIGUOUS",
]
ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


class CanaryLatestResponse(BaseModel):
    data_date: _date
    composite_version: int
    score_form: ScoreForm
    score: float
    raw_score: float
    band: Band
    tactical_score: float
    structural_score: float
    speed_score: int
    warning_state: WarningState
    payload: dict[str, Any]


class CanaryHistoryRow(BaseModel):
    data_date: _date
    score: float
    band: Band
    tactical_score: float
    structural_score: float
    speed_score: int
    warning_state: WarningState


class CanaryHistoryResponse(BaseModel):
    rows: list[CanaryHistoryRow]


class CanaryValidationResponse(BaseModel):
    run_id: int
    composite_version: int
    score_form: ScoreForm
    summary: dict[str, Any]
    rendered_markdown: str
