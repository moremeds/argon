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


class VcgInterpretationCount(BaseModel):
    interpretation: str
    n: int
    pct: float


class VcgNamedCrashOffset(BaseModel):
    """One row of the ±5d named-crash window for a single event."""

    offset_days: int
    vcg: float | None = None
    vcg_adj: float | None = None
    beta1: float | None = None
    beta2: float | None = None
    sign_ok: bool | None = None
    interpretation: str | None = None


class VcgNamedCrashEvent(BaseModel):
    date: str
    label: str
    offsets: list[VcgNamedCrashOffset]


class VcgValidationResponse(BaseModel):
    """Latest completed VCG backtest run rendered + structured."""

    backtest_md: str
    n_days: int
    composite_version: str
    credit_proxy: str
    interpretation_distribution: list[VcgInterpretationCount]
    named_crash_window: list[VcgNamedCrashEvent]
