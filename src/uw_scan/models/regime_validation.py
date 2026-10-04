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


class VcgStressHistoryEntry(BaseModel):
    """One daily row from the VCG backtest whose interpretation is a
    stress level (PANIC / RISK_OFF / EDR). Drives the all-time stress
    history table on the /regime VCG sub-tab."""

    date: str
    interpretation: Literal["PANIC", "RISK_OFF", "EDR"]
    score: float | None = None
    vcg_adj: float | None = None
    pi_panic: float | None = None
    sign_ok: bool | None = None
    vix: float | None = None
    vvix: float | None = None
    vix_percentile_rank: float | None = None
    vvix_percentile_rank: float | None = None
    fwd_5d_pct: float | None = None
    fwd_20d_pct: float | None = None
    fwd_60d_pct: float | None = None


class VcgStressHistorySummaryRow(BaseModel):
    """Per-interpretation aggregate of realized forward SPX returns
    across all stress days in the backtest run."""

    interpretation: Literal["PANIC", "RISK_OFF", "EDR"]
    n: int
    mean_fwd_5d_pct: float | None = None
    mean_fwd_20d_pct: float | None = None
    mean_fwd_60d_pct: float | None = None
    winrate_20d_pct: float | None = None
    winrate_60d_pct: float | None = None


class VcgStressHistorySummary(BaseModel):
    """Aggregate forward-return stats for the stress_history table."""

    by_interpretation: list[VcgStressHistorySummaryRow]


class VcgValidationResponse(BaseModel):
    """Latest completed VCG backtest run rendered + structured."""

    backtest_md: str
    n_days: int
    composite_version: str
    credit_proxy: str
    interpretation_distribution: list[VcgInterpretationCount]
    named_crash_window: list[VcgNamedCrashEvent]
    stress_history: list[VcgStressHistoryEntry] = []
    stress_history_summary: VcgStressHistorySummary | None = None
