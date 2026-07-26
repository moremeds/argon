"""Pydantic response schemas for GET /regime/sector-crowding.

See docs/superpowers/plans/2026-07-26-sector-crowding-panel.md (Task 5).
"""

from __future__ import annotations

from datetime import date as _date
from typing import Literal

from pydantic import BaseModel

LegName = Literal["price", "flow", "premium"]
CrowdingBand = Literal["CROWDED", "WARM", "NORMAL", "COLD"]


class SectorCrowdingLeg(BaseModel):
    name: LegName
    raw: float | None = None
    score: float | None = None
    band: CrowdingBand | None = None


class SectorCrowdingSeriesPoint(BaseModel):
    obs_date: _date
    etf_cum_return: float
    bench_cum_return: float
    flow_aum_pct: float | None = None


class SectorCrowdingRow(BaseModel):
    ticker: str
    price: SectorCrowdingLeg
    flow: SectorCrowdingLeg
    premium: SectorCrowdingLeg
    score: float | None = None
    # Weakest leg's band, not the mean's -- the legs are conjunctive.
    state: CrowdingBand | None = None
    binding_leg: LegName | None = None
    series: list[SectorCrowdingSeriesPoint] = []


class SectorCrowdingResponse(BaseModel):
    as_of: _date | None = None
    benchmark: str
    rows: list[SectorCrowdingRow] = []
