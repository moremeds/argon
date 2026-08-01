"""API contract models for the SPX density cone (signal-lab v13 display-only port)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from uw_scan.models._base import _preserve_public_module, _UwBase

_DISCLAIMER = (
    "Display-only fan chart (v13 PASS). Not a trading signal; the median is not a "
    "direction call; the band is not claimed tighter than EWMA."
)


class SpxDensityBins(_UwBase):
    """Histogram of the Monte-Carlo draws behind one horizon, in cumulative simple-return
    units (the same units as q05..q95). Bin i spans
    [lo + i*(hi-lo)/n_bins, lo + (i+1)*(hi-lo)/n_bins).

    `lo`/`hi` are the 0.5th/99.5th percentile of the draws, not the min/max, so one tail
    path cannot squash the body; `clipped` is how many draws fell outside."""

    lo: float
    hi: float
    n_bins: int
    counts: list[int]
    total: int
    clipped: int


class SpxDensityHorizon(_UwBase):
    """One horizon row of a cone: quantiles, the EWMA baseline, and its outcome."""

    h: int
    target_date: date
    scored_horizon: bool
    q05: float
    q10: float
    q25: float
    q50: float
    q75: float
    q90: float
    q95: float
    baseline_q05: float
    baseline_q10: float
    baseline_q25: float
    baseline_q50: float
    baseline_q75: float
    baseline_q90: float
    baseline_q95: float
    band80_width: float
    baseline_band80_width: float
    width_ratio: float
    realised_return: float | None = None
    inside_band80: bool | None = None
    # None for cones issued before migration 112 — the chart draws bands only.
    density: SpxDensityBins | None = None


class SpxDensityForecast(_UwBase):
    """One issued cone: five horizon rows anchored on a single trade date."""

    as_of: date
    anchor_close: float
    origin: str
    fallback_used: bool
    params: dict[str, float] | None = None
    rows: list[SpxDensityHorizon]


class SpxDensityPathPoint(_UwBase):
    """One SPX session. open/high/low are nullable: vol_index_daily carries close-only
    rows, and the chart drops those sessions from the candle series rather than
    manufacturing a bar out of the close."""

    date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None


class SpxGammaLevels(_UwBase):
    """Dealer levels for the chart overlay. Any field may be None — a level that failed
    the side-guard is omitted and named in `dropped`, never drawn on the wrong side of
    spot. See reports/gamma_levels.py for why the guard exists."""

    as_of: date | None = None
    spot: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    gamma_flip: float | None = None
    source: str | None = None
    dropped: list[str] = Field(default_factory=list)


class SpxDensityHitRate(_UwBase):
    origin: str
    inside: int
    total: int


class SpxDensityLatestResponse(_UwBase):
    forecast: SpxDensityForecast | None = None
    recent_path: list[SpxDensityPathPoint] = Field(default_factory=list)
    gamma_levels: SpxGammaLevels = Field(default_factory=SpxGammaLevels)
    disclaimer: str = _DISCLAIMER


class SpxDensityIssuedResponse(_UwBase):
    forecasts: list[SpxDensityForecast] = Field(default_factory=list)
    hit_rates: list[SpxDensityHitRate] = Field(default_factory=list)


_preserve_public_module(
    SpxDensityBins,
    SpxDensityHorizon,
    SpxDensityForecast,
    SpxDensityPathPoint,
    SpxGammaLevels,
    SpxDensityHitRate,
    SpxDensityLatestResponse,
    SpxDensityIssuedResponse,
)
