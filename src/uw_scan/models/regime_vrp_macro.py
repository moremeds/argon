"""VRP macro short-vol signal response models (regime API).

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .regime_cri_vcg import RegimeLiveQuote


class VrpMacroSignalRow(BaseModel):
    """Latest VRP macro short-vol signal for one index. action=TRADE iff weight>0
    (ramp+ vrp-z sizing); `strike_basis` says whether the strikes are real listed
    ones (per-leg IV) or flat-vol modeled — see the field comments below.
    Compare `as_of` to `snapshot_date` for staleness:
    `as_of` is the vol-data date, `snapshot_date` is when the job ran."""

    name: str
    snapshot_date: date
    as_of: date
    spot: float
    iv: float
    rv20: float | None = None
    vrp: float | None = None
    vrp_z: float | None = None
    weight: float
    action: str  # "TRADE" | "SKIP"
    short_put: float | None = None
    long_put: float | None = None
    put_width: float | None = None
    credit: float | None = None
    max_loss: float | None = None
    hold_days: int
    short_delta: float
    wing_delta: float
    bt_n: int | None = None
    bt_sharpe: float | None = None
    bt_maxdd: float | None = None
    bt_annror: float | None = None
    bt_calmar: float | None = None
    # Strike provenance. strike_basis='listed_skew' → short_put/long_put are REAL
    # listed strikes from the nightly grid, priced off each leg's own IV, and
    # short_put_delta/long_put_delta are the deltas they ACTUALLY carry.
    # 'flat_vol_model' → modeled strikes from one flat ATM vol (no grid for this
    # name); the deltas are NULL rather than the untrue target deltas.
    short_put_delta: float | None = None
    long_put_delta: float | None = None
    strike_basis: str | None = None
    strike_grid_date: date | None = None
    expiry: date | None = None


class VrpMacroSignalResponse(BaseModel):
    """Latest VRP macro short-vol signal per tracked index (one row each)."""

    signals: list[VrpMacroSignalRow] = Field(default_factory=list)


class VrpMacroSignalLiveResponse(BaseModel):
    """Live (intraday) VRP macro short-vol signal for SPX. `basis='live'` when computed
    from fresh quotes; `basis='eod'` when it falls back to the latest nightly snapshot.
    `signal` carries the same fields as the EOD row (bt_* may be NULL on the live path)."""

    status: str = "ok"
    basis: Literal["live", "eod"] = "eod"
    signal: VrpMacroSignalRow | None = None
    live_quotes: dict[str, RegimeLiveQuote] = Field(default_factory=dict)
    active_source: str | None = None
