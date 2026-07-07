"""Trade-lifecycle read models for the VRP-macro entry-capture cohorts.

The macro Short-Vol signal captures the SPX bull-put-spread it would place into
``vrp_macro_entry`` (8 marks/day tracked to expiry). These models read that back
as a *portfolio*: every cohort with its entry credit, latest mark, running P&L,
and expiry status. See issue #223 and reports/vrp_lifecycle.py.

P&L is expressed in **option points** for a single 1-lot spread (multiply by the
100× SPX contract multiplier for dollars). It is modeled from persisted NBBO
mids — paper/backtest only, never an executed fill.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from uw_scan.models._base import _preserve_public_module, _UwBase

_LIFECYCLE_DISCLAIMER = (
    "Modeled P&L from persisted NBBO mids of the short_above/wing_above bull-put "
    "bracket, in option points for one 1-lot spread (×100 for SPX dollars). "
    "Paper/backtest only — not executed."
)


class VrpMacroPositionRow(_UwBase):
    entry_id: int
    name: str
    origin: str  # 'auto' | 'button'
    birth_date: date
    born_at: datetime
    expiry: date
    hold_days: int
    action_at_birth: str | None = None
    vrp_z_at_birth: Decimal | None = None
    weight_at_birth: Decimal | None = None
    spot_at_birth: Decimal | None = None
    # Traded bracket strikes (short higher, wing lower — defined risk).
    short_strike: Decimal
    wing_strike: Decimal
    width: Decimal | None = None
    # Lifecycle status.
    status: str  # 'open' | 'expired'
    dte: int  # calendar days to expiry (negative once expired)
    days_held: int
    n_marks: int
    # Marks.
    entry_credit: Decimal | None = None  # first-mark short_mid − wing_mid
    current_value: Decimal | None = (
        None  # last-mark short_mid − wing_mid (cost to close)
    )
    unrealized_pnl: Decimal | None = None  # entry_credit − current_value
    max_loss: Decimal | None = None  # width − entry_credit
    return_on_risk: Decimal | None = None  # unrealized_pnl / max_loss
    last_mark_at: datetime | None = None
    last_spot: Decimal | None = None


class VrpMacroPositionsResponse(_UwBase):
    positions: list[VrpMacroPositionRow]
    open_count: int
    total_unrealized_pnl: Decimal | None = None
    disclaimer: str = _LIFECYCLE_DISCLAIMER


class VrpMacroPositionPnlPoint(_UwBase):
    as_of: datetime
    session: str | None = None
    spot: Decimal | None = None
    current_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None


class VrpMacroPositionDetail(_UwBase):
    position: VrpMacroPositionRow
    pnl_series: list[VrpMacroPositionPnlPoint]
    disclaimer: str = _LIFECYCLE_DISCLAIMER


_preserve_public_module(
    VrpMacroPositionRow,
    VrpMacroPositionsResponse,
    VrpMacroPositionPnlPoint,
    VrpMacroPositionDetail,
)
