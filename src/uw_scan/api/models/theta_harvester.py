"""Theta Harvester API contract models.

The candidate is a SHORT strangle, so every greek here carries POSITION signs
(theta > 0, gamma < 0, vega < 0) — the opposite of the long-contract convention
in option_surface_grid_daily. The negation happens once, in
scanners.theta_harvester.select_short_strangle; nothing downstream re-signs.

`entry_credit_theo` is the Black-Scholes mark that every markout is measured
against and is always populated. `credit_ib` is an optional live NBBO quote for
eyeballing only — it never becomes the markout basis, because a basis that
exists for some rows and not others is not comparable across the panel.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ThetaHarvesterCandidate(BaseModel):
    ticker: str
    as_of: date
    expiry: date
    dte: int
    put_strike: float
    call_strike: float
    underlying_spot: float
    entry_credit_theo: float
    credit_ib: float | None = None
    credit_quoted_at: datetime | None = None
    credit_source: str | None = None
    net_delta: float
    theta: float
    gamma: float
    vega: float
    score: float
    verdict: str
    weights_version: str | None = None
    iv: float | None = None
    hv20: float | None = None
    hv60: float | None = None
    iv_rv_edge: float | None = None
    iv_rv_ratio: float | None = None
    trend_20d_pct: float | None = None
    range_score: float | None = None
    dealer_support: str | None = None
    net_gex: float | None = None
    gex_flip: float | None = None
    gate_delta_near_zero: bool
    gate_iv_rich_vs_rv: bool
    gate_dealer_support: bool
    gate_theta_positive: bool
    gate_gamma_controlled: bool
    gate_range_bound: bool


class ThetaHarvesterResponse(BaseModel):
    as_of: date | None
    generated_at: datetime
    candidates: list[ThetaHarvesterCandidate]


class ThetaHarvesterScanResult(BaseModel):
    as_of: str | None = None
    tickers_scanned: int
    candidates_written: int
    harvest_count: int


class ThetaHarvesterQuoteResult(BaseModel):
    quoted: int
    failed: int
