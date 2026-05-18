"""Greek exposure contracts."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class GreekExposureRow(_UwBase):
    date: _date
    expiry: _date
    strike: Decimal
    dte: int | None = None
    call_delta: Decimal | None = None
    put_delta: Decimal | None = None
    call_gex: Decimal | None = None
    put_gex: Decimal | None = None
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None

class SpotExposureRow(_UwBase):
    ticker: str
    date: _date
    expiry: _date
    strike: Decimal
    price: Decimal | None = None
    # Selective projection: take the _oi variant (per-strike open-interest weighted)
    call_delta_oi: Decimal | None = None
    put_delta_oi: Decimal | None = None
    call_gamma_oi: Decimal | None = None
    put_gamma_oi: Decimal | None = None
    call_vanna_oi: Decimal | None = None
    put_vanna_oi: Decimal | None = None
    call_charm_oi: Decimal | None = None
    put_charm_oi: Decimal | None = None

class GreeksRow(_UwBase):
    date: _date
    expiry: _date
    strike: Decimal
    call_delta: Decimal | None = None
    put_delta: Decimal | None = None
    call_gamma: Decimal | None = None
    put_gamma: Decimal | None = None
    call_vega: Decimal | None = None
    put_vega: Decimal | None = None
    call_theta: Decimal | None = None
    put_theta: Decimal | None = None
    call_rho: Decimal | None = None
    put_rho: Decimal | None = None
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None
    call_volatility: Decimal | None = None
    put_volatility: Decimal | None = None
    call_option_symbol: str | None = None
    put_option_symbol: str | None = None


_preserve_public_module(
    GreekExposureRow,
    SpotExposureRow,
    GreeksRow,
)
