from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models._base import _preserve_public_module, _UwBase

_FLAT_VOL_DISCLAIMER = (
    "Flat-vol modeled credit (skew ignored): direction is faithful, absolute "
    "credit is approximate. Paper/backtest only — not executed."
)


class VrpCandidateRow(_UwBase):
    ticker: str
    as_of: date
    structure: str
    spot: Decimal | None = None
    iv: Decimal | None = None
    vrp_z: Decimal | None = None
    hold_days: int
    short_put: Decimal | None = None
    long_put: Decimal | None = None
    short_call: Decimal | None = None
    long_call: Decimal | None = None
    entry_credit: Decimal | None = None
    max_loss: Decimal | None = None
    bucket_sector: str | None = None
    bucket_verdict: str | None = None
    earnings_clear: bool
    contracts: int


class VrpCandidatesResponse(_UwBase):
    candidates: list[VrpCandidateRow]
    disclaimer: str = _FLAT_VOL_DISCLAIMER


class VrpBacktestRow(_UwBase):
    unit_type: str
    unit_key: str
    hold_days: int
    scope: str
    n_trades: int
    n_wins: int = 0
    win_rate: Decimal | None = None
    mean_net: Decimal | None = None
    median_net: Decimal | None = None
    total_net: Decimal | None = None
    mean_return_on_risk: Decimal | None = None
    breach_rate: Decimal | None = None
    mean_credit: Decimal | None = None


class VrpBacktestResponse(_UwBase):
    results: list[VrpBacktestRow]
    disclaimer: str = _FLAT_VOL_DISCLAIMER


class VrpPaperPositionRow(_UwBase):
    position_id: int
    ticker: str
    opened_on: date
    expiry_on: date
    hold_days: int
    contracts: int
    short_put: Decimal | None = None
    long_put: Decimal | None = None
    short_call: Decimal | None = None
    long_call: Decimal | None = None
    status: str
    entry_credit: Decimal | None = None
    max_loss: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    mark_source: str


class VrpPaperResponse(_UwBase):
    positions: list[VrpPaperPositionRow]
    total_realized_pnl: Decimal | None = None
    disclaimer: str = _FLAT_VOL_DISCLAIMER


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
# (repo convention — CLAUDE.md "preserve public Pydantic model __module__ metadata").
_preserve_public_module(
    VrpCandidateRow,
    VrpCandidatesResponse,
    VrpBacktestRow,
    VrpBacktestResponse,
    VrpPaperPositionRow,
    VrpPaperResponse,
)
