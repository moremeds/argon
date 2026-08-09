"""Contract models for the Technicals magnet sub-tab."""

from __future__ import annotations

from datetime import date

from uw_scan.models._base import _preserve_public_module, _UwBase


class MagnetPivot(_UwBase):
    index: int
    kind: str
    price: float


class MagnetLevels(_UwBase):
    resistance: float
    support: float
    stretch: float
    down: float
    sma20: float | None
    last: float
    leg_state: str
    pivot_a: MagnetPivot
    pivot_b: MagnetPivot


class MagnetConeBand(_UwBase):
    horizon: int
    band_sigma: float
    measured_confidence: float
    measured_ci_lo: float
    measured_ci_hi: float
    measured_n_dates: int
    upper: float
    lower: float


class MagnetCandle(_UwBase):
    date: date
    open: float
    high: float
    low: float
    close: float
    # Nullable: daily_ohlc.volume is `int | None`, and the route's NaN filter
    # covers OHLC only. A bar with a real price and an unknown volume is still
    # drawable — a non-optional float here would 500 on it.
    volume: float | None


class MagnetsResponse(_UwBase):
    ticker: str
    as_of: date
    levels: MagnetLevels | None
    bands: list[MagnetConeBand]
    pivots: list[MagnetPivot]
    read: list[str]
    candles: list[MagnetCandle]
    atm_iv_30d: float | None
    atm_iv_30d_chg_5d: float | None


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
_preserve_public_module(
    MagnetPivot,
    MagnetLevels,
    MagnetConeBand,
    MagnetCandle,
    MagnetsResponse,
)
