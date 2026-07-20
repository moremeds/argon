"""API contract models for the /stock Technicals tab."""

from __future__ import annotations

from datetime import date, datetime
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
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
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
    # Dual MACD histograms (13/21/9 fast vs 55/89/34 slow), ATR-normalized,
    # plus the fast pair's own MACD/signal lines. Only what the chart draws is
    # typed; deltas/norms stay in JSONB.
    fast_macd_hist_atr: float | None = None
    slow_macd_hist_atr: float | None = None
    fast_macd_line_atr: float | None = None
    fast_macd_signal_atr: float | None = None


class ForwardReturnBandRow(_UwBase):
    band: str
    horizon: int
    count: int
    mean: float
    median: float
    win_rate: float


class VwapPoint(_UwBase):
    as_of: date
    vwap: float


class TechnicalsVwapAnchor(_UwBase):
    """User-set anchored VWAP: the anchor bar + the series from it forward."""

    anchor_date: date
    series: list[VwapPoint] = []


class VwapAnchorRequest(_UwBase):
    anchor_date: date


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
    vwap_anchor: TechnicalsVwapAnchor | None = None


class FormingOhlc(_UwBase):
    """Today's provisional session candle, accumulated live from the WS spot:
    open = first fresh spot of the ET session, high/low = running extremes,
    close = latest spot. Lets the chart draw a real forming candle instead of a
    zero-range doji. `source` tags the feed; when the massive cross-check heals a
    bad xenon read, `source` becomes the massive feed and `stale` flips True."""

    session_date: date
    open: float
    high: float
    low: float
    close: float
    source: str | None = None
    stale: bool = False


class TechnicalsLiveResponse(_UwBase):
    """Latest-only live technicals head (fast-moving subset recomputed off the
    WS spot). `available` is False when no fresh cache row exists — the client
    then falls back to the EOD daily payload."""

    ticker: str
    available: bool
    captured_at: datetime | None = None
    spot: float | None = None
    spot_source: str | None = None
    forming_ohlc: FormingOhlc | None = None
    z: float | None = None
    z_band: str | None = None
    rsi14: float | None = None
    rsi_z: float | None = None
    dual_macd: dict[str, Any] | None = None
    rv20: float | None = None
    kinematics: dict[str, Any] | None = None
    composite: float | None = None


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
_preserve_public_module(
    TechnicalsHeader,
    TechnicalsSeriesRow,
    ForwardReturnBandRow,
    VwapPoint,
    TechnicalsVwapAnchor,
    VwapAnchorRequest,
    TechnicalsResponse,
    FormingOhlc,
    TechnicalsLiveResponse,
)
