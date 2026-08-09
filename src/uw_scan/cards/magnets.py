"""Magnet-view geometry (spec 2026-08-08 §4).

The ZigZag threshold is in ATR(14) units rather than a fixed percentage, which
is why this is worth keeping over the reference's own detector: an ATR threshold
adapts to each ticker's volatility instead of applying one percentage to a $20
stock and a $900 one.

The 0.618 extension levels this module computes have **no measured edge**. The
Phase-1 first-passage study (`docs/research/2026-08-08-magnet-cone-calibration/`)
tested whether price reaches STRETCH before it reaches the opposite pivot more
often than a random level at the same distance would, and it does not. They are
kept as chart geometry because the reference chart draws them and because a
reader who knows the construction can place them; they are never a target.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pandas as pd

from uw_scan.cards.technicals import atr14


class Pivot(NamedTuple):
    index: int  # bar the extreme occurred on
    kind: str  # "top" | "bottom"
    price: float  # close at `index`
    confirmed_index: int  # bar the reversal threshold was crossed — the FIRST bar
    # on which this pivot was knowable. Never backtest from
    # `index`; measured lag is 3-25 bars and 8-14% of price.


def all_pivots(df: pd.DataFrame, k: float = 3.0) -> list[Pivot]:
    """Every confirmed ATR-zigzag pivot, oldest first.

    A pivot is a swing extreme that LATER reverses by >= k * ATR(14). Confirmation
    is retrospective by construction, so the newest extreme is never a pivot until
    price has moved away from it — that lag is the price of not repainting.

    Each pivot therefore carries TWO indices. `index` is where the extreme sits on
    the chart; `confirmed_index` is where a live system would first have known
    about it. Drawing uses `index`; any forward test MUST use `confirmed_index`.
    """
    if len(df) < 30:
        return []
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    pivots: list[Pivot] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(Pivot(ext_i, "top", float(close[ext_i]), i))
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(Pivot(ext_i, "bottom", float(close[ext_i]), i))
                direction, ext_i = 1, i
    return pivots


FIB = 0.618


def magnet_levels(df: pd.DataFrame, k: float = 3.0) -> dict | None:
    """The four levels, SMA20 and leg state from the last two ZigZag pivots.

    `leg_state` is "rising" when the LATER pivot is the bottom (price is working
    up off support) and "falling" otherwise. Returns None when fewer than two
    pivots exist — a chart with no measurable swing has no magnet levels, and
    fabricating them from the window's min/max would invent a swing.

    Uses `Pivot.index`, not `confirmed_index`: this draws where the extreme sits
    on the chart. Any forward test must use `confirmed_index` instead.
    """
    pivots = all_pivots(df, k=k)
    if len(pivots) < 2:
        return None
    a, b = pivots[-2], pivots[-1]
    rising = b.kind == "bottom"
    resistance = a.price if rising else b.price
    support = b.price if rising else a.price
    if resistance <= support:
        return None
    leg = resistance - support
    close = df["close"].astype(float)
    return {
        "resistance": float(resistance),
        "support": float(support),
        "stretch": float(resistance + FIB * leg),
        "down": float(support - FIB * leg),
        "sma20": float(close.tail(20).mean()) if len(close) >= 20 else None,
        "last": float(close.iloc[-1]),
        "leg_state": "rising" if rising else "falling",
        "pivot_a": {"index": a.index, "kind": a.kind, "price": float(a.price)},
        "pivot_b": {"index": b.index, "kind": b.kind, "price": float(b.price)},
    }


TRADING_DAYS = 252
CONE_HORIZONS = (5, 10, 21)
CONE_BANDS = (1.0, 1.96)

# Measured 2026-08-09 on 47,034 observations / 119 tickers, 2025-12-26..2026-07-31.
# These are what each band ACTUALLY contained, not the lognormal nominal. The
# legend shows these numbers. Source: confidence_curve.csv.
# No 2.576 band: the far tail needs 8-17% more width than the closed form.
MEASURED_CONFIDENCE: dict[tuple[int, float], float] = {
    (5, 1.0): 0.709,
    (5, 1.96): 0.951,
    (10, 1.0): 0.712,
    (10, 1.96): 0.947,
    (21, 1.0): 0.677,
    (21, 1.96): 0.933,
}

# 95% panel block bootstrap (resample blocks of dates, keep every ticker). Ships
# WITH the point estimate because the intervals are 2.4-11.4pt wide: a bare
# "70.9%" reads as a probability, and it is a backward-looking frequency over one
# ~8-month regime. The label shows both.
MEASURED_CONFIDENCE_CI: dict[tuple[int, float], tuple[float, float]] = {
    (5, 1.0): (0.677, 0.755),
    (5, 1.96): (0.939, 0.963),
    (10, 1.0): (0.666, 0.758),
    (10, 1.96): (0.924, 0.965),
    (21, 1.0): (0.617, 0.731),
    (21, 1.96): (0.901, 0.964),
}

# Sessions behind each horizon's estimate — shown in the legend so the window is
# never implicit.
MEASURED_N_DATES: dict[int, int] = {5: 149, 10: 144, 21: 133}


def cone(
    spot: float,
    atm_iv_by_horizon: dict[int, float | None],
    k_shrink: float = 1.0,
) -> list[dict]:
    """Options-implied price bands, inverting the calibration's z exactly.

        z = (ln(S_t+h / S_t) + 0.5*sigma^2*T) / (sigma*sqrt(T))
    =>  S_t+h = S_t * exp(z*sigma*sqrt(T) - 0.5*sigma^2*T)

    k_shrink MULTIPLIES z, so k < 1 narrows the band — matching both the name and
    the calibration's own convention. The research computes coverage as
    `coverage(z_test / k_train, level)` (`magnet_cone_calibration.py:314`), i.e.
    the calibrated band at `level` accepts realised residuals with
    `|z| < k*level`. In price space that is `z_draw = band * k`. Dividing here
    instead would draw the RECIPROCAL band: feed in the research's own
    `k_train = 0.9747` and you would get a band 2.6% too WIDE where the
    calibration made it 2.5% narrower. The parameter ships at 1.0 so the
    direction is currently inert — which is exactly why it has a test.

    Ships at 1.0. The G2 gate's fitted scale passed at 5d only (coverage
    0.7000 -> 0.6873 against a 0.6827 nominal) and moved 10d/21d the WRONG way,
    because it fits by `std` and cannot correct an over-coverage miss. Shipping
    a constant justified by one horizon out of three would be worse than
    shipping none, and at k=1.0 every drawn band's nominal coverage already sits
    inside its measured 95% CI. The corrected estimator (MAD, or direct quantile
    targeting) is pre-registered in VERDICT.md as research, not build.
    """
    if k_shrink <= 0:
        raise ValueError(f"k_shrink must be positive, got {k_shrink}")
    out: list[dict] = []
    for h in CONE_HORIZONS:
        sigma = atm_iv_by_horizon.get(h)
        if sigma is None or sigma <= 0:
            continue
        t = h / TRADING_DAYS
        drift = 0.5 * sigma**2 * t
        vol = sigma * math.sqrt(t)
        for band in CONE_BANDS:
            z = band * k_shrink
            out.append(
                {
                    "horizon": h,
                    "band_sigma": band,
                    "measured_confidence": MEASURED_CONFIDENCE[(h, band)],
                    "measured_ci_lo": MEASURED_CONFIDENCE_CI[(h, band)][0],
                    "measured_ci_hi": MEASURED_CONFIDENCE_CI[(h, band)][1],
                    "measured_n_dates": MEASURED_N_DATES[h],
                    "upper": float(spot * math.exp(z * vol - drift)),
                    "lower": float(spot * math.exp(-z * vol - drift)),
                }
            )
    return out
