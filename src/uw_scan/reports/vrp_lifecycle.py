"""Assemble the VRP-macro trade-lifecycle portfolio from persisted cohorts.

Pure functions: storage dicts (headers + first/last mids, or a full mid series)
→ response models. No I/O. The strategy trades the short_above / wing_above
bull-put bracket (short strike higher, wing lower — defined risk), so entry
credit / current value / P&L are all computed from those two legs' mids. A mid is
None when either NBBO side was missing at capture; that propagates to a None
credit rather than a fabricated number. See models/vrp_lifecycle.py and #223.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.models.vrp_lifecycle import (
    VrpMacroPositionDetail,
    VrpMacroPositionPnlPoint,
    VrpMacroPositionRow,
    VrpMacroPositionsResponse,
)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _spread(short_mid: Any, wing_mid: Any) -> Decimal | None:
    """Bull-put value = short leg mid − wing leg mid. None if either is absent."""
    s, w = _dec(short_mid), _dec(wing_mid)
    if s is None or w is None:
        return None
    return s - w


def build_position_row(row: dict[str, Any], *, today: date) -> VrpMacroPositionRow:
    short_k = _dec(row["short_strike_above"])
    wing_k = _dec(row["wing_strike_above"])
    width = short_k - wing_k if short_k is not None and wing_k is not None else None
    entry_credit = _spread(row.get("entry_short_mid"), row.get("entry_wing_mid"))
    current_value = _spread(row.get("last_short_mid"), row.get("last_wing_mid"))
    unrealized = (
        entry_credit - current_value
        if entry_credit is not None and current_value is not None
        else None
    )
    max_loss = (
        width - entry_credit if width is not None and entry_credit is not None else None
    )
    ror = (
        unrealized / max_loss
        if unrealized is not None and max_loss is not None and max_loss != 0
        else None
    )
    expiry: date = row["expiry"]
    birth: date = row["birth_date"]
    dte = (expiry - today).days
    return VrpMacroPositionRow(
        entry_id=row["entry_id"],
        name=row["name"],
        origin=row["origin"],
        birth_date=birth,
        born_at=row["born_at"],
        expiry=expiry,
        hold_days=row["hold_days"],
        action_at_birth=row.get("action_at_birth"),
        vrp_z_at_birth=_dec(row.get("vrp_z_at_birth")),
        weight_at_birth=_dec(row.get("weight_at_birth")),
        spot_at_birth=_dec(row.get("spot_at_birth")),
        short_strike=short_k,
        wing_strike=wing_k,
        width=width,
        status="open" if dte >= 0 else "expired",
        dte=dte,
        days_held=(today - birth).days,
        n_marks=row.get("n_marks", 0),
        entry_credit=entry_credit,
        current_value=current_value,
        unrealized_pnl=unrealized,
        max_loss=max_loss,
        return_on_risk=ror,
        last_mark_at=row.get("last_as_of"),
        last_spot=_dec(row.get("last_spot")),
    )


def build_positions_response(
    rows: list[dict[str, Any]], *, today: date
) -> VrpMacroPositionsResponse:
    positions = [build_position_row(r, today=today) for r in rows]
    open_positions = [p for p in positions if p.status == "open"]
    total = sum(
        (p.unrealized_pnl for p in open_positions if p.unrealized_pnl is not None),
        Decimal(0),
    )
    return VrpMacroPositionsResponse(
        positions=positions,
        open_count=len(open_positions),
        total_unrealized_pnl=total if open_positions else None,
    )


def build_position_detail(
    header: dict[str, Any], series: list[dict[str, Any]], *, today: date
) -> VrpMacroPositionDetail:
    position = build_position_row(header, today=today)
    entry_credit = position.entry_credit
    points: list[VrpMacroPositionPnlPoint] = []
    for mark in series:
        value = _spread(mark.get("short_mid"), mark.get("wing_mid"))
        pnl = (
            entry_credit - value
            if entry_credit is not None and value is not None
            else None
        )
        points.append(
            VrpMacroPositionPnlPoint(
                as_of=mark["as_of"],
                session=mark.get("session"),
                spot=_dec(mark.get("und_spot")),
                current_value=value,
                unrealized_pnl=pnl,
            )
        )
    return VrpMacroPositionDetail(position=position, pnl_series=points)
