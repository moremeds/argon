"""Skew First-Principles tab response contracts."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class SkewHistoryPoint(_UwBase):
    date: _date
    rr: Decimal | None = None
    z: Decimal | None = None
    pct: Decimal | None = None


class SkewRhoPoint(_UwBase):
    date: _date
    rho: Decimal | None = None


class SkewExpiryPoint(_UwBase):
    expiry: _date
    rr: Decimal | None = None
    dte: int | None = None


class SkewSmilePoint(_UwBase):
    strike: Decimal
    iv: Decimal | None = None


class SkewSmileExpiryCurve(_UwBase):
    expiry: _date
    points: list[SkewSmilePoint] = []


class SkewStructureLeg(_UwBase):
    action: str = ""  # BUY | SELL
    right: str = ""  # PUT | CALL
    strike: Decimal | None = None
    target_delta: Decimal | None = None  # the delta we aimed for (e.g. -0.25)
    actual_delta: Decimal | None = None  # delta of the chosen strike
    expiry: _date | None = None
    dte: int | None = None


class SkewStructureDetail(_UwBase):
    kind: str = ""  # put_debit_spread | call_debit_spread
    legs: list[SkewStructureLeg] = []
    dte_target: int | None = None
    status: str = "ready"  # ready | no_chain | suppressed
    note: str = ""  # e.g. "defined risk; exit before earnings 2026-07-18"


class SkewDirectionalLean(_UwBase):
    lean: str = "NEUTRAL"  # BULLISH_TILT | BEARISH_TILT | NEUTRAL
    confidence: str = "low"  # low | med | high
    basis: str = ""
    express: str = ""
    structure_detail: SkewStructureDetail | None = None


class SkewReadBullet(_UwBase):
    label: str = ""
    body: str = ""


class SkewRead(_UwBase):
    tail: str = ""
    rho: Decimal | None = None
    rho_confirms: bool = False
    drive: str = ""
    deviation_class: str = ""
    class_context: str = ""
    borrow_context: str = ""
    earnings_gate: str = ""
    summary_line: str = ""
    summary_bullets: list[SkewReadBullet] = []
    directional_lean: SkewDirectionalLean = SkewDirectionalLean()


class SkewAnalysisResponse(_UwBase):
    ticker: str
    as_of: _date
    backfill_status: str = "ready"
    spot: Decimal | None = None
    rr_25d: Decimal | None = None
    rr_z_180d: Decimal | None = None
    rr_pct_252d: Decimal | None = None
    deviation_class: str = "NORMAL"
    skew_term_class: str = "unknown"
    front_rr: Decimal | None = None
    back_rr: Decimal | None = None
    rho_spotvol_63d: Decimal | None = None
    rho_spotvol_21d: Decimal | None = None
    rho_sign: int | None = None
    drive_class: str = "STRUCTURAL"
    asset_class: str = "single_name"
    class_expected_sign: str = "mixed"
    borrow_flag: str = "unknown"
    borrow_fee_rate: Decimal | None = None
    days_to_cover: Decimal | None = None
    earnings_gate: str = "unknown"
    regime: str = "UNKNOWN"
    directional_lean: str = "NEUTRAL"
    lean_confidence: str = "low"
    lean_basis: str = ""
    read: SkewRead = SkewRead()
    history: list[SkewHistoryPoint] = []
    rho_series: list[SkewRhoPoint] = []
    term_structure: list[SkewExpiryPoint] = []
    smile: list[SkewSmileExpiryCurve] = []


_preserve_public_module(
    SkewHistoryPoint,
    SkewRhoPoint,
    SkewExpiryPoint,
    SkewSmilePoint,
    SkewSmileExpiryCurve,
    SkewStructureLeg,
    SkewStructureDetail,
    SkewDirectionalLean,
    SkewReadBullet,
    SkewRead,
    SkewAnalysisResponse,
)
