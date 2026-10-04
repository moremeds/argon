"""Pydantic response schemas for /regime/vrp-macro-signal/entry endpoints.

See docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md (Task 7).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

LegName = Literal["short_above", "short_below", "wing_above", "wing_below"]
# Every leg's NBBO is real: xenon/IB-primary, UW fallback. There is no synthetic
# source — the preview serves persisted legs or none (a fake quote is worse than
# no quote), so 'modeled' is intentionally NOT a permitted source.
LegSource = Literal["xenon_ib", "uw"]
GreeksSource = Literal["ib", "bs", "none"]


class VrpMacroEntryLeg(BaseModel):
    leg: LegName
    strike: float
    nbbo_bid: float | None = None
    nbbo_ask: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None
    und_spot: float | None = None
    source: LegSource
    greeks_source: GreeksSource


class VrpMacroEntryPreview(BaseModel):
    name: str
    as_of: datetime | None = None
    spot: float | None = None
    expiry: _date | None = None
    hold_days: int | None = None
    action: str | None = None  # TRADE | SKIP | None (signal unresolved)
    vrp_z: float | None = None
    weight: float | None = None
    modeled_credit: float | None = (
        None  # short-leg mid − wing-leg mid (consistent bracket)
    )
    legs: list[VrpMacroEntryLeg] = []


class VrpMacroEntryCaptureResponse(BaseModel):
    entry_id: int
    preview: VrpMacroEntryPreview
