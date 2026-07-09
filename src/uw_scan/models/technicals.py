"""API contract models for the /stock Technicals tab."""

from __future__ import annotations

from datetime import date
from typing import Any

from uw_scan.models._base import _preserve_public_module, _UwBase


class TechnicalsHeader(_UwBase):
    price: float | None = None
    sma200: float | None = None
    dist_pct: float | None = None
    z: float | None = None
    z_band: str | None = None
    slope_ann: float | None = None
    slope_regime: str | None = None
    composite: float | None = None


class TechnicalsSeriesRow(_UwBase):
    as_of: date
    close: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    z: float | None = None
    rsi14: float | None = None
    macd_hist_atr: float | None = None
    rs_ratio: float | None = None
    # Derived per-session metric history (from the metrics JSONB) so each
    # detail tile can sparkline its own past. Sigmoid stays latest-only.
    rv20: float | None = None
    rv20_z: float | None = None
    vol_of_vol: float | None = None
    skew60: float | None = None
    kurt60: float | None = None
    jerk20: float | None = None
    rsi_z: float | None = None
    rsi_slope5: float | None = None
    macd_slope3: float | None = None
    kin_slope20: float | None = None
    kin_slope50: float | None = None
    kin_slope200: float | None = None
    alignment: float | None = None
    # Dual MACD histograms (13/21/9 fast vs 55/89/34 slow), ATR-normalized.
    # Only the two charted histograms are typed; deltas/norms stay in JSONB.
    fast_macd_hist_atr: float | None = None
    slow_macd_hist_atr: float | None = None


class ForwardReturnBandRow(_UwBase):
    band: str
    horizon: int
    count: int
    mean: float
    median: float
    win_rate: float


class TechnicalsResponse(_UwBase):
    ticker: str
    backfill_status: str  # "ready" | "empty"
    as_of: date | None = None
    bars_n: int | None = None
    header: TechnicalsHeader | None = None
    series: list[TechnicalsSeriesRow] = []
    detail: dict[str, Any] | None = None
    macd_watchlist_pctile: float | None = None
    forward_returns: list[ForwardReturnBandRow] = []


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
_preserve_public_module(
    TechnicalsHeader, TechnicalsSeriesRow, ForwardReturnBandRow, TechnicalsResponse
)
