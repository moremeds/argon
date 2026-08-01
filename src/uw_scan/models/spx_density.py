"""API contract models for the SPX density cone (signal-lab v13 display-only port)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from uw_scan.models._base import _preserve_public_module, _UwBase

_DISCLAIMER = (
    "Display-only fan chart (v13 PASS). Not a trading signal; the median is not a "
    "direction call; the band is not claimed tighter than EWMA."
)


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


class SpxDensityForecast(_UwBase):
    """One issued cone: five horizon rows anchored on a single trade date."""

    as_of: date
    anchor_close: float
    origin: str
    fallback_used: bool
    params: dict[str, float] | None = None
    rows: list[SpxDensityHorizon]


class SpxDensityPathPoint(_UwBase):
    date: date
    close: float


class SpxDensityHitRate(_UwBase):
    origin: str
    inside: int
    total: int


class SpxDensityLatestResponse(_UwBase):
    forecast: SpxDensityForecast | None = None
    recent_path: list[SpxDensityPathPoint] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class SpxDensityIssuedResponse(_UwBase):
    forecasts: list[SpxDensityForecast] = Field(default_factory=list)
    hit_rates: list[SpxDensityHitRate] = Field(default_factory=list)


_preserve_public_module(
    SpxDensityHorizon,
    SpxDensityForecast,
    SpxDensityPathPoint,
    SpxDensityHitRate,
    SpxDensityLatestResponse,
    SpxDensityIssuedResponse,
)
