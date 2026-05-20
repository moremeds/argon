"""Response models for the /api/regime/validation + /guidance endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OosLabel(BaseModel):
    name: str
    definition: str


class OosScore(BaseModel):
    model: str
    auc_dd5: float | None = None
    auc_vix30: float | None = None
    auc_dd10: float | None = None


class OosSummary(BaseModel):
    as_of: str
    notebook: str
    method: str
    labels: list[OosLabel]
    scores: list[OosScore]
    interpretation: str


class ValidationResponse(BaseModel):
    """Combined warm-store backtest + OOS notebook summary."""

    backtest_md: str
    backtest_csv_rows: int
    oos: OosSummary | None = None


class GuidanceResponse(BaseModel):
    state: str
    posture: Literal["opportunistic", "neutral", "cautious", "defensive"]
    body_md: str
    matched_condition: str
