"""Pure technicals derivers for the Technicals tab. No DB access, no I/O.

Spec: docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md
Everything is a z-score or ratio (dimensionless, cross-ticker comparable).

# ponytail: prices are float end-to-end here — chart-grade series, not money
# math. Decimal boundary conversion buys nothing for ±1e-9 on a z-score.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# (lo, hi, label) — lo-inclusive, hi-exclusive.
Z_BANDS: list[tuple[float, float, str]] = [
    (-math.inf, -2.0, "DEEPLY OVERSOLD"),
    (-2.0, -1.5, "OVERSOLD"),
    (-1.5, -1.0, "STRETCHED LOW"),
    (-1.0, -0.5, "MILD LOW"),
    (-0.5, 0.5, "NEUTRAL"),
    (0.5, 1.0, "MILD HIGH"),
    (1.0, 1.5, "STRETCHED HIGH"),
    (1.5, 2.0, "OVERBOUGHT"),
    (2.0, math.inf, "DEEPLY OVERBOUGHT"),
]


def z_band_label(z: float | None) -> str | None:
    if z is None:
        return None
    try:
        zf = float(z)
    except (TypeError, ValueError) as exc:
        log.debug("z coercion skipped: %s", repr(exc))
        return None
    if not math.isfinite(zf):
        return None
    for lo, hi, label in Z_BANDS:
        if lo <= zf < hi:
            return label
    return None


def _lastf(s: pd.Series) -> float | None:
    """Last value of a series as a finite float, else None."""
    if len(s) == 0:
        return None
    v = s.iloc[-1]
    if pd.isna(v):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


# Derived per-session metrics stored (as a JSONB blob) on every technical_daily
# row so each detail tile can render its own history. Sigmoid is deliberately
# excluded — a curve_fit per row is too expensive to backfill across the
# watchlist, so it stays a latest-only readout.
SERIES_METRIC_COLS: tuple[str, ...] = (
    "rv20",
    "rv20_z",
    "vol_of_vol",
    "skew60",
    "kurt60",
    "jerk20",
    "rsi_z",
    "rsi_slope5",
    "macd_slope3",
    "kin_slope20",
    "kin_slope50",
    "kin_slope200",
    "alignment",
    "fast_macd_hist_atr",
    "slow_macd_hist_atr",
    "fast_macd_delta",
    "slow_macd_delta",
    "fast_macd_delta2",
    "fast_macd_norm",
    "slow_macd_norm",
)


def _rolling_z(s: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - mu) / sd.replace(0.0, np.nan)


def _rolling_ols_slope(s: pd.Series, w: int = 10) -> pd.Series:
    """Vectorized rolling OLS slope via a fixed centered-x weight vector —
    slope = Σ (x-x̄)(y-ȳ) / Σ (x-x̄)² over the trailing `w`-bar window."""
    x = np.arange(w, dtype=float)
    xc = x - x.mean()
    denom = float(np.sum(xc * xc)) or 1.0
    return s.rolling(w).apply(
        lambda y: float(np.dot(xc, y - np.mean(y)) / denom), raw=True
    )


def bars_frame(bars: list[dict]) -> pd.DataFrame:
    """Coerce an apex /bars payload (time = ISO-8601 UTC string) into a
    sorted, deduped daily frame with an ``as_of`` date column."""
    cols = ["as_of", "open", "high", "low", "close", "volume"]
    if not bars:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(bars)
    df["as_of"] = pd.to_datetime(df["time"], utc=True).dt.date
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return (
        df[cols]
        .dropna(subset=["close"])
        .drop_duplicates(subset=["as_of"], keep="last")
        .sort_values("as_of")
        .reset_index(drop=True)
    )


def atr14(df: pd.DataFrame) -> pd.Series:
    """Wilder ATR(14)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def rsi14(close: pd.Series) -> pd.Series:
    """Wilder RSI(14)."""
    delta = close.diff()
    up = delta.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = up / dn.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # No losses but gains present: RSI saturates at 100 (rs -> inf limit).
    # Flat series (up == dn == 0) stays undefined (nan).
    return rsi.mask((dn == 0.0) & (up > 0.0), 100.0)


def macd_hist(
    close: pd.Series, fast: int = 8, slow: int = 17, signal: int = 9
) -> pd.Series:
    """MACD histogram, Shepherd's 8/17/9 default."""
    macd = (
        close.ewm(span=fast, adjust=False).mean()
        - close.ewm(span=slow, adjust=False).mean()
    )
    return macd - macd.ewm(span=signal, adjust=False).mean()


def _num(v: Any) -> float:
    """Coerce to a finite float, else 0.0 (matches apex _safe_float)."""
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        log.debug("dual_macd coercion skipped: %s", repr(exc))
        return 0.0
    return f if math.isfinite(f) else 0.0


def _rolling_pctile_rank(s: pd.Series, window: int = 252) -> pd.Series:
    """Causal rolling percentile rank (0-1) of each value within its trailing
    `window` (ports apex _rolling_pctile_rank; needs >=2 valid points)."""
    return s.rolling(window, min_periods=2).apply(
        lambda w: float(np.mean(w <= w[-1])), raw=True
    )


def dual_macd_series(df: pd.DataFrame, *, slope_lookback: int = 3) -> pd.DataFrame:
    """Fast (13/21/9) + slow (55/89/34) MACD histograms, each ATR(14)-normalized,
    with slopes, fast curvature, and 252d percentile-rank magnitudes. Ports
    apex momentum/dual_macd.py with argon's ATR normalization in place of the
    raw x2 multiplier."""
    close = df["close"]
    atr = atr14(df).replace(0.0, np.nan)
    fast = macd_hist(close, fast=13, slow=21, signal=9) / atr
    slow = macd_hist(close, fast=55, slow=89, signal=34) / atr
    fast_delta = fast.diff(slope_lookback)
    slow_delta = slow.diff(slope_lookback)
    return pd.DataFrame(
        {
            "fast_macd_hist_atr": fast,
            "slow_macd_hist_atr": slow,
            "fast_macd_delta": fast_delta,
            "slow_macd_delta": slow_delta,
            "fast_macd_delta2": fast_delta.diff(1),
            "fast_macd_norm": _rolling_pctile_rank(fast.abs()),
            "slow_macd_norm": _rolling_pctile_rank(slow.abs()),
        },
        index=df.index,
    )


def dual_macd_state(row: Mapping[str, Any], *, eps: float = 1e-3) -> dict:
    """Trend / tactical / balance / confidence from a dual_macd_series row.
    Direct port of apex DualMACDIndicator._get_state (override-first trend,
    countertrend-decelerating tactical, freeze-zone balance, curvature conf)."""
    h_slow = _num(row.get("slow_macd_hist_atr"))
    h_fast = _num(row.get("fast_macd_hist_atr"))
    dh_slow = _num(row.get("slow_macd_delta"))
    dh_fast = _num(row.get("fast_macd_delta"))
    ddh_fast = _num(row.get("fast_macd_delta2"))
    slow_norm = _num(row.get("slow_macd_norm"))
    fast_norm = _num(row.get("fast_macd_norm"))

    if h_slow > 0 and dh_slow < 0:
        trend = "DETERIORATING"
    elif h_slow < 0 and dh_slow > 0:
        trend = "IMPROVING"
    elif h_slow > 0:
        trend = "BULLISH"
    else:
        trend = "BEARISH"

    tactical = "NONE"
    if h_slow > 0 and h_fast < 0 and abs(dh_fast) > abs(dh_slow) and dh_fast >= 0:
        tactical = "DIP_BUY"
    elif h_slow < 0 and h_fast > 0 and abs(dh_fast) > abs(dh_slow) and dh_fast <= 0:
        tactical = "RALLY_SELL"

    if slow_norm < 0.15 and fast_norm < 0.15:
        balance = "BALANCED"
    elif fast_norm > slow_norm * 1.5:
        balance = "FAST_DOMINANT"
    elif slow_norm > fast_norm * 1.5:
        balance = "SLOW_DOMINANT"
    else:
        balance = "BALANCED"

    confidence = 0.0
    if tactical == "DIP_BUY":
        confidence = float(np.clip(ddh_fast / max(abs(h_fast), eps), 0.0, 1.0))
    elif tactical == "RALLY_SELL":
        confidence = float(np.clip(-ddh_fast / max(abs(h_fast), eps), 0.0, 1.0))

    return {
        "fast_hist": h_fast,
        "slow_hist": h_slow,
        "fast_delta": dh_fast,
        "slow_delta": dh_slow,
        "trend_state": trend,
        "tactical_signal": tactical,
        "momentum_balance": balance,
        "confidence": confidence,
    }


def z_vs_200dma(close: pd.Series, z_window: int = 252) -> pd.Series:
    """Price distance from the 200 DMA in σ of that distance.

    z_t = (close_t - sma200_t) / rolling_std(close - sma200, z_window).
    No mean subtraction: distance 0 == sitting on the MA, by construction.
    """
    sma200 = close.rolling(200).mean()
    dist = close - sma200
    sd = dist.rolling(z_window, min_periods=126).std()
    return dist / sd.replace(0.0, np.nan)


def sma200_slope_ann(close: pd.Series, lookback: int = 21) -> pd.Series:
    """Annualized growth rate of the 200 DMA over the last `lookback` sessions."""
    sma200 = close.rolling(200).mean()
    return (sma200 / sma200.shift(lookback)) ** (252.0 / lookback) - 1.0


def slope_regime(slope_ann: float | None) -> str | None:
    if slope_ann is None:
        return None
    try:
        s = float(slope_ann)
    except (TypeError, ValueError) as exc:
        log.debug("slope coercion skipped: %s", repr(exc))
        return None
    if not math.isfinite(s):
        return None
    if s >= 0.10:
        return "STRONG UPTREND"
    if s >= 0.02:
        return "UPTREND"
    if s > -0.02:
        return "FLAT"
    if s > -0.10:
        return "DOWNTREND"
    return "STRONG DOWNTREND"


def ma_kinematics(df: pd.DataFrame, *, reg_window: int = 10) -> dict:
    """ATR-normalized velocity/acceleration + slope t-stat per SMA, plus a
    three-pair alignment score in [-3, 3].

    slope_atr: OLS slope of the last `reg_window` SMA values / ATR(14) —
    dimensionless "ATRs per day". curv_atr: change in that slope vs the
    window ending 5 sessions earlier. tstat: slope / SE(slope) — replaces
    crossover folklore with a significance readout.
    """
    close = df["close"]
    atr = atr14(df)
    atr_now = _lastf(atr)
    out: dict[str, object] = {}
    for n in (20, 50, 200):
        key = f"sma{n}"
        sma = close.rolling(n).mean().dropna()
        if len(sma) < reg_window + 5 or atr_now is None or atr_now <= 0:
            out[key] = {"slope_atr": None, "curv_atr": None, "tstat": None}
            continue
        t = np.arange(reg_window, dtype=float)
        y = sma.tail(reg_window).to_numpy(dtype=float)
        slope, intercept = np.polyfit(t, y, 1)
        resid = y - (slope * t + intercept)
        denom = float(np.sum((t - t.mean()) ** 2))
        se = math.sqrt(float(np.sum(resid**2)) / (reg_window - 2) / denom)
        y_prev = sma.iloc[:-5].tail(reg_window).to_numpy(dtype=float)
        prev_slope = np.polyfit(t, y_prev, 1)[0] if len(y_prev) == reg_window else None
        out[key] = {
            "slope_atr": float(slope) / atr_now,
            "curv_atr": (float(slope - prev_slope) / atr_now)
            if prev_slope is not None
            else None,
            "tstat": (float(slope) / se) if se > 0 else None,
        }
    alignment = 0
    px = _lastf(close)
    sma_vals = {n: _lastf(close.rolling(n).mean()) for n in (20, 50, 200)}
    pairs = [
        (px, sma_vals[20]),
        (sma_vals[20], sma_vals[50]),
        (sma_vals[50], sma_vals[200]),
    ]
    for a, b in pairs:
        if a is not None and b is not None:
            alignment += 1 if a > b else -1
    out["alignment"] = alignment
    return out


def last_pivot_index(df: pd.DataFrame, *, k: float = 3.0) -> int:
    """Most recent confirmed ATR-zigzag pivot index.

    Pivot = a swing extreme that later reverses by >= k * ATR(14). Falls back
    to len-126 when no pivot confirms (young or drift-only series).
    """
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    if n < 30:
        return 0
    pivots: list[int] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = 1, i
    if not pivots:
        return max(0, n - 126)
    return pivots[-1]


def fit_sigmoid(closes: np.ndarray) -> dict:
    """Fit logistic b + L/(1+e^(-k(t-t0))) to a price segment; only *valid*
    when it beats a plain linear fit (r2_sigmoid >= 0.80 AND >= r2_linear
    + 0.05 AND k > 0) — the honesty guard from the spec."""
    out: dict[str, object] = {
        "valid": False,
        "phase": None,
        "k": None,
        "s": None,
        "r2_sigmoid": None,
        "r2_linear": None,
        "n": int(len(closes)),
    }
    if len(closes) < 30 or not np.all(np.isfinite(closes)):
        return out
    from scipy.optimize import curve_fit  # first scipy consumer in src/

    t = np.arange(len(closes), dtype=float)

    def logistic(tt: np.ndarray, big_l: float, kk: float, t0: float, b: float):
        return b + big_l / (1.0 + np.exp(-np.clip(kk * (tt - t0), -500.0, 500.0)))

    ss_tot = float(np.sum((closes - closes.mean()) ** 2)) or 1.0
    lin = np.polyval(np.polyfit(t, closes, 1), t)
    r2_lin = 1.0 - float(np.sum((closes - lin) ** 2)) / ss_tot
    out["r2_linear"] = r2_lin
    span = float(closes.max() - closes.min()) or 1.0
    sign = 1.0 if closes[-1] >= closes[0] else -1.0
    p0 = [sign * span, 0.1, len(closes) / 2.0, float(closes[0])]
    try:
        popt, _ = curve_fit(logistic, t, closes, p0=p0, maxfev=10000)
    except Exception as exc:
        log.debug("sigmoid fit failed: %s", repr(exc))
        return out
    fit = logistic(t, *popt)
    r2_sig = 1.0 - float(np.sum((closes - fit) ** 2)) / ss_tot
    kk, t0 = float(popt[1]), float(popt[2])
    s = kk * (float(t[-1]) - t0)
    out.update({"r2_sigmoid": r2_sig, "k": kk, "s": s})
    if r2_sig >= 0.80 and r2_sig >= r2_lin + 0.05 and kk > 0:
        out["valid"] = True
        # Ship the actual segment + fitted logistic so the UI can chart the
        # per-request fit (only when valid — a rejected fit has nothing honest
        # to draw). Kept as plain lists (JSONB-friendly, small: <=126 points).
        out["actual"] = closes.tolist()
        out["fit"] = fit.tolist()
        if s < -2.0:
            out["phase"] = "EARLY"
        elif s < 0.0:
            out["phase"] = "ACCELERATING"
        elif s <= 2.0:
            out["phase"] = "DECELERATING"
        else:
            out["phase"] = "SATURATED"
    return out


def return_distribution(close: pd.Series) -> dict:
    """20d realized σ z-scored vs its own 252d history, vol-of-vol,
    60d skew/kurtosis, and second-difference 'jerkiness'."""
    rets = close.pct_change()
    rv20 = rets.rolling(20).std() * math.sqrt(252)
    mu = rv20.rolling(252, min_periods=126).mean()
    sd = rv20.rolling(252, min_periods=126).std()
    return {
        "rv20": _lastf(rv20),
        "rv20_z": _lastf((rv20 - mu) / sd.replace(0.0, np.nan)),
        "vol_of_vol": _lastf(rv20.diff().rolling(60).std()),
        "skew60": _lastf(rets.rolling(60).skew()),
        "kurt60": _lastf(rets.rolling(60).kurt()),
        "jerk20": _lastf(rets.diff().rolling(20).std()),
    }


def _local_extrema_idx(
    vals: np.ndarray, *, order: int = 5, lookback: int = 120, mode: str = "max"
) -> list[int]:
    n = len(vals)
    start = max(order, n - lookback)
    idx: list[int] = []
    for i in range(start, n - order):
        win = vals[i - order : i + order + 1]
        if mode == "max" and vals[i] == win.max():
            idx.append(i)
        elif mode == "min" and vals[i] == win.min():
            idx.append(i)
    return idx


def rsi_enhanced(df: pd.DataFrame) -> dict:
    """RSI(14) z-scored vs its 252d distribution, 5d slope, and a
    pivot-based divergence detector (price HH + RSI LH => BEARISH)."""
    close = df["close"]
    r = rsi14(close)
    mu = r.rolling(252, min_periods=126).mean()
    sd = r.rolling(252, min_periods=126).std()
    divergence = None
    vals = close.to_numpy(dtype=float)
    highs = _local_extrema_idx(vals, mode="max")
    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if vals[i2] > vals[i1] and float(r.iloc[i2]) < float(r.iloc[i1]):
            divergence = {"type": "BEARISH", "rsi_gap": float(r.iloc[i1] - r.iloc[i2])}
    if divergence is None:
        lows = _local_extrema_idx(vals, mode="min")
        if len(lows) >= 2:
            i1, i2 = lows[-2], lows[-1]
            if vals[i2] < vals[i1] and float(r.iloc[i2]) > float(r.iloc[i1]):
                divergence = {
                    "type": "BULLISH",
                    "rsi_gap": float(r.iloc[i2] - r.iloc[i1]),
                }
    return {
        "rsi14": _lastf(r),
        "rsi_z": _lastf((r - mu) / sd.replace(0.0, np.nan)),
        "rsi_slope5": _lastf(r.diff(5) / 5.0),
        "divergence": divergence,
    }


def macd_enhanced(df: pd.DataFrame) -> dict:
    """MACD(8/17/9) histogram normalized by ATR(14) + its 3d derivative.
    Cross-sectional watchlist percentile is a read-time report concern."""
    hist_atr = macd_hist(df["close"]) / atr14(df).replace(0.0, np.nan)
    return {
        "hist_atr": _lastf(hist_atr),
        "hist_atr_slope3": _lastf(hist_atr.diff(3) / 3.0),
    }


def relative_strength(df: pd.DataFrame, spy_df: pd.DataFrame) -> dict:
    """TICKER/SPY ratio + its 60/200d MAs. v1 benchmark = SPY only."""
    empty = {"ratio": None, "ma60": None, "ma200": None, "trend": None, "n": 0}
    if df.empty or spy_df.empty:
        return empty
    merged = df[["as_of", "close"]].merge(
        spy_df[["as_of", "close"]], on="as_of", suffixes=("", "_spy")
    )
    if len(merged) < 60:
        return {**empty, "n": int(len(merged))}
    ratio = merged["close"] / merged["close_spy"]
    out = {
        "ratio": _lastf(ratio),
        "ma60": _lastf(ratio.rolling(60).mean()),
        "ma200": _lastf(ratio.rolling(200).mean()),
        "trend": None,
        "n": int(len(merged)),
    }
    if out["ratio"] is not None and out["ma60"] is not None:
        out["trend"] = (
            "OUTPERFORMING" if out["ratio"] > out["ma60"] else "UNDERPERFORMING"
        )
    return out


def forward_return_table(
    close: pd.Series, z: pd.Series, horizons: tuple[int, ...] = (20, 40, 60)
) -> list[dict]:
    """⭐ Forward return conditioned on z-band. Look-ahead disciplined:
    the band at session t uses only data through t; the forward return uses
    only bars after t; sessions with no bar at t+h are excluded."""
    rows: list[dict] = []
    for h in horizons:
        fwd = close.shift(-h) / close - 1.0
        for lo, hi, label in Z_BANDS:
            mask = (z >= lo) & (z < hi)
            vals = fwd[mask].replace([np.inf, -np.inf], np.nan).dropna()
            if len(vals) == 0:
                continue
            rows.append(
                {
                    "band": label,
                    "horizon": int(h),
                    "count": int(len(vals)),
                    "mean": float(vals.mean()),
                    "median": float(vals.median()),
                    "win_rate": float((vals > 0).mean()),
                }
            )
    return rows


def composite_score(
    *,
    alignment: int | None,
    slope_tstat_200: float | None,
    macd_hist_atr: float | None,
    rsi_z: float | None,
) -> float | None:
    """Trend-quality composite: mean of bounded sub-scores, each in [-1, 1].
    Sub-scores stay visible upstream — never a black box."""
    parts: list[float] = []
    if alignment is not None:
        parts.append(alignment / 3.0)
    for v, scale in ((slope_tstat_200, 2.0), (macd_hist_atr, 1.0), (rsi_z, 2.0)):
        if v is not None and math.isfinite(v):
            parts.append(math.tanh(v / scale))
    return float(np.mean(parts)) if parts else None


def build_technical_series(
    bars: list[dict], spy_bars: list[dict] | None = None
) -> pd.DataFrame:
    """Per-day storable series (one row per session) for technical_daily."""
    df = bars_frame(bars)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "as_of",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "sma20",
                "sma50",
                "sma200",
                "z_vs_200dma",
                "z_band",
                "sma200_slope_ann",
                "slope_regime",
                "rsi14",
                "macd_hist_atr",
                *SERIES_METRIC_COLS,
                "rs_ratio",
            ]
        )
    close = df["close"]
    out = df[["as_of", "open", "high", "low", "close", "volume"]].copy()
    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["z_vs_200dma"] = z_vs_200dma(close)
    out["z_band"] = out["z_vs_200dma"].map(z_band_label)
    out["sma200_slope_ann"] = sma200_slope_ann(close)
    out["slope_regime"] = out["sma200_slope_ann"].map(slope_regime)
    out["rsi14"] = rsi14(close)
    out["macd_hist_atr"] = macd_hist(close) / atr14(df).replace(0.0, np.nan)

    _dm = dual_macd_series(df)
    for col in _dm.columns:
        out[col] = _dm[col]

    # Derived per-session metric history (mirrors the latest-only derivers so
    # each detail tile can sparkline its own past). All vectorized/cheap.
    rets = close.pct_change()
    rv20 = rets.rolling(20).std() * math.sqrt(252)
    out["rv20"] = rv20
    out["rv20_z"] = _rolling_z(rv20)
    out["vol_of_vol"] = rv20.diff().rolling(60).std()
    out["skew60"] = rets.rolling(60).skew()
    out["kurt60"] = rets.rolling(60).kurt()
    out["jerk20"] = rets.diff().rolling(20).std()
    out["rsi_z"] = _rolling_z(out["rsi14"])
    out["rsi_slope5"] = out["rsi14"].diff(5) / 5.0
    out["macd_slope3"] = out["macd_hist_atr"].diff(3) / 3.0
    atr = atr14(df).replace(0.0, np.nan)
    for n in (20, 50, 200):
        out[f"kin_slope{n}"] = _rolling_ols_slope(close.rolling(n).mean()) / atr
    out["alignment"] = (
        np.sign(close - out["sma20"]).fillna(0.0)
        + np.sign(out["sma20"] - out["sma50"]).fillna(0.0)
        + np.sign(out["sma50"] - out["sma200"]).fillna(0.0)
    )

    if spy_bars:
        spy = bars_frame(spy_bars)[["as_of", "close"]].rename(
            columns={"close": "close_spy"}
        )
        out = out.merge(spy, on="as_of", how="left")
        out["rs_ratio"] = out["close"] / out["close_spy"]
        out = out.drop(columns=["close_spy"])
    else:
        out["rs_ratio"] = np.nan
    return out


def build_technical_snapshot(
    bars: list[dict], spy_bars: list[dict] | None = None
) -> dict | None:
    """Latest-day rich snapshot. None when <210 bars (200 SMA + slack) —
    callers surface 'too thin' rather than a silently wrong z."""
    df = bars_frame(bars)
    if len(df) < 210:
        return None
    series = build_technical_series(bars, spy_bars)
    close = df["close"]
    kin = ma_kinematics(df)
    pivot = last_pivot_index(df)
    if len(df) - pivot < 30:
        pivot = max(0, len(df) - 126)
    sig = fit_sigmoid(close.to_numpy(dtype=float)[pivot:])
    rsi_d = rsi_enhanced(df)
    macd_d = macd_enhanced(df)
    dual = dual_macd_state(dual_macd_series(df).iloc[-1])
    rs = relative_strength(df, bars_frame(spy_bars)) if spy_bars else None
    last = series.iloc[-1]
    px, sma200 = _lastf(close), _lastf(series["sma200"])
    return {
        "as_of": last["as_of"],
        "bars_n": int(len(df)),
        "close": px,
        "sma20": _lastf(series["sma20"]),
        "sma50": _lastf(series["sma50"]),
        "sma200": sma200,
        "dist_pct": (px / sma200 - 1.0) if px and sma200 else None,
        "z": _lastf(series["z_vs_200dma"]),
        "z_band": last["z_band"] if pd.notna(last["z_band"]) else None,
        "slope_ann": _lastf(series["sma200_slope_ann"]),
        "slope_regime": last["slope_regime"]
        if pd.notna(last["slope_regime"])
        else None,
        "kinematics": kin,
        "sigmoid": sig,
        "distribution": return_distribution(close),
        "rsi": rsi_d,
        "macd": macd_d,
        "dual_macd": dual,
        "rs": rs,
        "composite": composite_score(
            alignment=kin.get("alignment"),
            slope_tstat_200=(kin.get("sma200") or {}).get("tstat"),
            macd_hist_atr=macd_d.get("hist_atr"),
            rsi_z=rsi_d.get("rsi_z"),
        ),
        "forward_returns": forward_return_table(close, series["z_vs_200dma"]),
    }


def live_technical_snapshot(
    df: pd.DataFrame, spot: float, *, as_of: date | None = None
) -> dict:
    """Splice `spot` as today's provisional daily close onto `df` (an OHLCV
    frame from bars_frame) and recompute only the fast-moving technicals.
    Sigmoid + forward-returns are deliberately excluded (static intraday);
    callers carry them from the nightly detail. Pure — no I/O."""
    prov = pd.DataFrame(
        [
            {
                "as_of": as_of,
                "open": spot,
                "high": spot,
                "low": spot,
                "close": spot,
                "volume": 0.0,
            }
        ]
    )
    d = pd.concat([df, prov], ignore_index=True)
    close = d["close"]
    z = _lastf(z_vs_200dma(close))
    rsi_d = rsi_enhanced(d)
    kin = ma_kinematics(d)
    dist = return_distribution(close)
    dual = dual_macd_state(dual_macd_series(d).iloc[-1])
    macd_atr = _lastf(macd_hist(close) / atr14(d).replace(0.0, np.nan))
    return {
        "z": z,
        "z_band": z_band_label(z),
        "rsi14": rsi_d.get("rsi14"),
        "rsi_z": rsi_d.get("rsi_z"),
        "dual_macd": dual,
        "rv20": dist.get("rv20"),
        "kinematics": kin,
        "composite": composite_score(
            alignment=kin.get("alignment"),
            slope_tstat_200=(kin.get("sma200") or {}).get("tstat"),
            macd_hist_atr=macd_atr,
            rsi_z=rsi_d.get("rsi_z"),
        ),
    }
