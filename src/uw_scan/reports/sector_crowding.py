"""Sector-ETF crowding score (板块拥挤度).

Three conjunctive legs, adapted from
https://x.com/bitfool1/status/2079479920162734401 (2026-07-21):

  price    3M return minus the benchmark's, expressed as that ETF's OWN
           trailing percentile. Absolute spread is not comparable across the
           universe -- the trailing SD of the 3M spread ranges from 3.1 (XLY)
           to 16.5 (XLE), so ranking on raw spread ranks volatility, not
           crowding. XLF at +3.14% is its 99th percentile; SMH at +17.88% is
           its 46th.
  flow     21-session net premium flow / AUM, scored on the tweet's published
           2% / 5% / 10% bands. Dividing by AUM already removes the size
           effect, so absolute bands ARE comparable here and are kept.
  premium  iv_rank minus the benchmark's iv_rank. Substitutes for the tweet's
           NTM P/E, which needs constituent forward EPS that neither UW nor
           massive expose on our tier. Same question -- is the crowd paying up
           -- asked about convexity instead of earnings.

STATE is the weakest leg's band, not the mean's. The tweet is explicit that
the legs are conjunctive (三者同时出现，才算真正拥挤); a mean would let one
extreme leg manufacture a CROWDED badge on its own. SCORE stays the mean so
rows sort with some granularity inside a state, and `binding_leg` names which
leg is holding the state down so a demotion is always explainable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

RETURN_WINDOW = 63
FLOW_WINDOW = 21
MIN_SESSIONS = RETURN_WINDOW + FLOW_WINDOW
MIN_HISTORY_POINTS = 60
LOOKBACK_DAYS = 400

BENCHMARK = "SPY"
SECTOR_CROWDING_TICKERS = (
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "SOXX",
    "SMH",
    "IGV",
)
# ARKK is deliberately absent: UW's /api/etfs/ARKK/in-outflow returns 0 rows.
# Verified 2026-07-24. Re-add if UW starts publishing it.

# (flow_pct, score) anchors for piecewise-linear interpolation, clamped
# outside the ends. Derived from the tweet's bands: <2% normal, 2-5% warm,
# 5%+ crowded, 10%+ extreme.
FLOW_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (-5.0, 0.0),
    (0.0, 20.0),
    (2.0, 40.0),
    (5.0, 70.0),
    (10.0, 90.0),
    (25.0, 100.0),
)
IVR_SPREAD_CAP = 60.0

BAND_CROWDED = 75.0
BAND_WARM = 50.0
BAND_NORMAL = 25.0

_BAND_RANK = {"COLD": 0, "NORMAL": 1, "WARM": 2, "CROWDED": 3}


@dataclass(frozen=True)
class CrowdingLeg:
    name: str
    raw: float | None
    score: float | None
    band: str | None


def pct_rank(history: Sequence[float], value: float) -> float | None:
    """Percentile of `value` within `history`, 0-100. None if no history."""
    if not history:
        return None
    below = sum(1 for h in history if h < value)
    return 100.0 * below / len(history)


def flow_score(flow_aum_pct: float) -> float:
    """Map 1M-flow/AUM percent onto 0-100 via the tweet's bands."""
    lo_x, lo_y = FLOW_BREAKPOINTS[0]
    if flow_aum_pct <= lo_x:
        return lo_y
    for (x0, y0), (x1, y1) in zip(FLOW_BREAKPOINTS, FLOW_BREAKPOINTS[1:], strict=False):
        if flow_aum_pct <= x1:
            span = x1 - x0
            return y0 + (flow_aum_pct - x0) / span * (y1 - y0)
    return FLOW_BREAKPOINTS[-1][1]


def premium_score(ivr_spread: float) -> float:
    """Map an iv_rank spread (percentage points vs benchmark) onto 0-100."""
    if ivr_spread <= 0.0:
        return 0.0
    return min(ivr_spread, IVR_SPREAD_CAP) / IVR_SPREAD_CAP * 100.0


def band_of(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= BAND_CROWDED:
        return "CROWDED"
    if score >= BAND_WARM:
        return "WARM"
    if score >= BAND_NORMAL:
        return "NORMAL"
    return "COLD"


def combine(
    legs: Sequence[CrowdingLeg],
) -> tuple[float | None, str | None, str | None]:
    """(mean score, weakest-leg band, name of the leg pinning that band).

    Needs at least two present legs -- a single leg is a reading, not a
    conjunction, and badging it would overstate what we know.
    """
    present = [leg for leg in legs if leg.score is not None and leg.band is not None]
    if len(present) < 2:
        return (None, None, None)
    score = sum(leg.score for leg in present) / len(present)
    weakest = min(_BAND_RANK[leg.band] for leg in present)
    in_band = [leg for leg in present if _BAND_RANK[leg.band] == weakest]
    binding = min(in_band, key=lambda leg: leg.score)
    return (score, binding.band, binding.name)
