"""Crash Risk Indicator (CRI) — pure scoring functions.

Ported from xenon/src/xenon/scanners/cri.py (component scorers + composite
+ CTA exposure model + crash trigger + realized vol + COR1M helper).

No DB, no network. Pure math. Inputs are floats / numpy arrays; outputs
are floats / typed dicts.

Strategy reference: docs/research/regime/ (TBD).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# ── constants ─────────────────────────────────────────────────────
MA_WINDOW = 100  # SPX moving average window
VOL_WINDOW = 20  # Realized vol window (annualized)

# CTA model parameters
CTA_VOL_TARGET = 10.0  # 10% target volatility
CTA_MAX_EXPOSURE = 200.0  # Max 200% exposure (leverage)
CTA_AUM_BN = 350.0  # Estimated systematic-CTA AUM in $B

# Crash trigger thresholds
CRASH_REALIZED_VOL_THRESHOLD = 25.0  # 25% annualized
CRASH_COR1M_THRESHOLD = 60.0  # 60 percentage points


# ══════════════════════════════════════════════════════════════════
# Realized Volatility
# ══════════════════════════════════════════════════════════════════


def compute_realized_vol(prices: np.ndarray, window: int = VOL_WINDOW) -> float:
    """Annualized realized volatility from the trailing window, in % points.

    Returns NaN if fewer than ``window + 1`` prices are provided.
    """
    if len(prices) < window + 1:
        return float("nan")
    log_returns = np.log(prices[-window:] / prices[-window - 1 : -1])
    return float(np.std(log_returns, ddof=1) * np.sqrt(252) * 100)


# ══════════════════════════════════════════════════════════════════
# COR1M helper
# ══════════════════════════════════════════════════════════════════


def cor1m_level_and_change(cor1m_values: np.ndarray) -> tuple[float, float]:
    """Current COR1M level and 5-session change (both in % points).

    COR1M is already quoted as a percentage index (e.g. 31.1 means 31.1%
    implied average correlation), so no scaling.
    """
    if cor1m_values is None or len(cor1m_values) == 0:
        return float("nan"), float("nan")
    if np.all(np.isnan(cor1m_values)):
        return float("nan"), float("nan")
    current = float(cor1m_values[-1])
    if math.isnan(current):
        return float("nan"), float("nan")
    if len(cor1m_values) >= 6:
        prev = float(cor1m_values[-6])
        change = current - prev if not math.isnan(prev) else float("nan")
    else:
        change = float("nan")
    return current, change


# ══════════════════════════════════════════════════════════════════
# Component Scoring (each 0-25)
# ══════════════════════════════════════════════════════════════════


def score_vix_component(vix: float, vix_5d_roc: float) -> float:
    """Score VIX component (0-25). vix_5d_roc is in %."""
    if math.isnan(vix) or math.isnan(vix_5d_roc):
        return 0.0
    level_score = np.clip((vix - 15.0) / (40.0 - 15.0) * 15.0, 0.0, 15.0)
    roc_score = np.clip(max(vix_5d_roc, 0.0) / 60.0 * 10.0, 0.0, 10.0)
    return float(np.clip(level_score + roc_score, 0.0, 25.0))


def score_vvix_component(vvix: float, vvix_vix_ratio: float) -> float:
    """Score VVIX component (0-25)."""
    if math.isnan(vvix) or math.isnan(vvix_vix_ratio):
        return 0.0
    level_score = np.clip((vvix - 90.0) / (140.0 - 90.0) * 17.0, 0.0, 17.0)
    ratio_score = np.clip((vvix_vix_ratio - 5.0) / (8.0 - 5.0) * 8.0, 0.0, 8.0)
    return float(np.clip(level_score + ratio_score, 0.0, 25.0))


def score_correlation_component(corr: float, corr_5d_change: float) -> float:
    """Score COR1M component (0-25). corr in % points."""
    if math.isnan(corr):
        return 0.0
    if math.isnan(corr_5d_change):
        corr_5d_change = 0.0
    level_score = np.clip((corr - 25.0) / (70.0 - 25.0) * 17.0, 0.0, 17.0)
    spike_score = np.clip(max(corr_5d_change, 0.0) / 20.0 * 8.0, 0.0, 8.0)
    return float(np.clip(level_score + spike_score, 0.0, 25.0))


def score_momentum_component(spx_distance_pct: float) -> float:
    """Score momentum component (0-25). Rises as SPX falls below 100d MA."""
    if math.isnan(spx_distance_pct):
        return 0.0
    if spx_distance_pct >= 0:
        return 0.0
    return float(np.clip(abs(spx_distance_pct) / 10.0 * 25.0, 0.0, 25.0))


# ══════════════════════════════════════════════════════════════════
# Composite CRI
# ══════════════════════════════════════════════════════════════════


def cri_level(score: float) -> str:
    if score < 25:
        return "LOW"
    if score < 50:
        return "ELEVATED"
    if score < 75:
        return "HIGH"
    return "CRITICAL"


def compute_cri(
    vix: float,
    vix_5d_roc: float,
    vvix: float,
    vvix_vix_ratio: float,
    corr: float,
    corr_5d_change: float,
    spx_distance_pct: float,
) -> dict[str, Any]:
    """Composite 0-100 score from the four components."""
    vix_score = score_vix_component(vix, vix_5d_roc)
    vvix_score = score_vvix_component(vvix, vvix_vix_ratio)
    corr_score = score_correlation_component(corr, corr_5d_change)
    momentum_score = score_momentum_component(spx_distance_pct)
    total = float(
        np.clip(vix_score + vvix_score + corr_score + momentum_score, 0.0, 100.0)
    )
    return {
        "score": round(total, 1),
        "level": cri_level(total),
        "components": {
            "vix": round(vix_score, 1),
            "vvix": round(vvix_score, 1),
            "correlation": round(corr_score, 1),
            "momentum": round(momentum_score, 1),
        },
    }


# ══════════════════════════════════════════════════════════════════
# CTA exposure
# ══════════════════════════════════════════════════════════════════


def cta_exposure_model(
    realized_vol: float,
    vol_target: float = CTA_VOL_TARGET,
    aum_bn: float = CTA_AUM_BN,
) -> dict[str, Any]:
    """Estimate CTA exposure from vol-targeting.

    exposure_pct = min(vol_target / realized_vol * 100, CTA_MAX_EXPOSURE)
    forced_reduction = max(0, 1 - exposure / 100)
    """
    if math.isnan(realized_vol) or realized_vol <= 0:
        return {
            "realized_vol": realized_vol if not math.isnan(realized_vol) else 0.0,
            "exposure_pct": CTA_MAX_EXPOSURE,
            "forced_reduction_pct": 0.0,
            "forced_reduction": False,
            "est_selling_bn": 0.0,
            "selling_usd_b": 0.0,
        }
    exposure = min(vol_target / realized_vol * 100.0, CTA_MAX_EXPOSURE)
    reduction = max(0.0, 1.0 - exposure / 100.0)
    est_selling = reduction * aum_bn
    return {
        "realized_vol": round(realized_vol, 2),
        "exposure_pct": round(exposure, 1),
        "forced_reduction_pct": round(reduction * 100.0, 1),
        "forced_reduction": reduction > 0.0,
        "est_selling_bn": round(est_selling, 1),
        "selling_usd_b": round(est_selling, 1),
    }


# ══════════════════════════════════════════════════════════════════
# Crash trigger
# ══════════════════════════════════════════════════════════════════


def crash_trigger(
    spx_below_ma: bool,
    realized_vol: float,
    cor1m: float,
) -> dict[str, Any]:
    """Three-condition crash trigger.

    All three must fire:
      1. SPX < 100-day MA
      2. 20d realized vol > 25% annualized
      3. COR1M > 60 percentage points
    """
    vol_ok = (
        not math.isnan(realized_vol)
    ) and realized_vol > CRASH_REALIZED_VOL_THRESHOLD
    corr_ok = (not math.isnan(cor1m)) and cor1m > CRASH_COR1M_THRESHOLD
    triggered = spx_below_ma and vol_ok and corr_ok
    return {
        "triggered": triggered,
        "fired": triggered,
        "conditions": {
            "spx_below_100d_ma": spx_below_ma,
            "realized_vol_gt_25": vol_ok,
            "cor1m_gt_60": corr_ok,
        },
        "values": {
            "realized_vol": round(realized_vol, 2)
            if not math.isnan(realized_vol)
            else None,
            "cor1m": round(cor1m, 2) if not math.isnan(cor1m) else None,
        },
    }


# ══════════════════════════════════════════════════════════════════
# Full analysis orchestrator (pure — takes aligned arrays)
# ══════════════════════════════════════════════════════════════════


def run_analysis(
    aligned: dict[str, np.ndarray],
    common_dates: list[str],
) -> dict[str, Any]:
    """Compute the full CRI snapshot from aligned daily-close arrays.

    Required keys in ``aligned``: VIX, VVIX, SPY, COR1M.
    All arrays must be the same length and aligned to ``common_dates``.
    """
    vix = aligned["VIX"]
    vvix = aligned["VVIX"]
    spy = aligned["SPY"]
    cor1m_values = aligned["COR1M"]

    vix_now = float(vix[-1])
    vvix_now = float(vvix[-1])
    spy_now = float(spy[-1])

    # VIX 5-day RoC (%)
    if len(vix) >= 6 and vix[-6] > 0:
        vix_5d_roc = (vix[-1] / vix[-6] - 1) * 100
    else:
        vix_5d_roc = 0.0

    # VVIX 5-day RoC (%) — leading indicator of tail-hedging demand.
    # See docs/research/regime/cri-methodology.md §3 (VVIX).
    if len(vvix) >= 6 and vvix[-6] > 0:
        vvix_5d_roc = (vvix[-1] / vvix[-6] - 1) * 100
    else:
        vvix_5d_roc = 0.0

    vvix_vix_ratio = vvix_now / vix_now if vix_now > 0 else float("nan")

    # SPX vs 100d MA (using SPY as the SPX proxy — UW/lake don't give us a
    # tradeable SPX, and SPY tracks SPX 1:10).
    if len(spy) >= MA_WINDOW:
        ma_100 = float(np.mean(spy[-MA_WINDOW:]))
        spx_distance_pct = (spy_now / ma_100 - 1) * 100
        spx_below_ma = spy_now < ma_100
    else:
        ma_100 = float("nan")
        spx_distance_pct = 0.0
        spx_below_ma = False

    cor1m_now, cor1m_5d_change = cor1m_level_and_change(cor1m_values)
    cor1m_previous_close = (
        float(cor1m_values[-1]) if len(cor1m_values) > 0 else float("nan")
    )

    realized_vol = compute_realized_vol(spy, VOL_WINDOW)

    cri = compute_cri(
        vix=vix_now,
        vix_5d_roc=float(vix_5d_roc),
        vvix=vvix_now,
        vvix_vix_ratio=float(vvix_vix_ratio),
        corr=cor1m_now,
        corr_5d_change=cor1m_5d_change,
        spx_distance_pct=float(spx_distance_pct),
    )
    cta = cta_exposure_model(realized_vol)
    trigger = crash_trigger(
        spx_below_ma=spx_below_ma, realized_vol=realized_vol, cor1m=cor1m_now
    )

    # 20-session rolling history for the mini-chart
    history: list[dict[str, Any]] = []
    n = len(vix)
    for i in range(max(0, n - 20), n):
        v = float(vix[i])
        vv = float(vvix[i])
        s = float(spy[i])
        if i >= MA_WINDOW - 1:
            day_ma = float(np.mean(spy[i - MA_WINDOW + 1 : i + 1]))
            day_dist = (s / day_ma - 1) * 100
        else:
            day_ma = float("nan")
            day_dist = 0.0
        if i >= 5 and vix[i - 5] > 0:
            day_vix_roc = (vix[i] / vix[i - 5] - 1) * 100
        else:
            day_vix_roc = 0.0
        if i >= 5 and vvix[i - 5] > 0:
            day_vvix_roc = (vvix[i] / vvix[i - 5] - 1) * 100
        else:
            day_vvix_roc = 0.0
        if i >= 5 and not math.isnan(float(cor1m_values[i - 5])):
            day_cor1m_5d_chg = float(cor1m_values[i]) - float(cor1m_values[i - 5])
        else:
            day_cor1m_5d_chg = 0.0
        if i >= VOL_WINDOW:
            day_rvol = compute_realized_vol(spy[: i + 1], VOL_WINDOW)
        else:
            day_rvol = float("nan")
        history.append(
            {
                "date": common_dates[i],
                "vix": round(v, 2),
                "vvix": round(vv, 2),
                "spy": round(s, 2),
                "cor1m": round(float(cor1m_values[i]), 2),
                "realized_vol": round(day_rvol, 2)
                if not math.isnan(day_rvol)
                else None,
                "spx_vs_ma_pct": round(float(day_dist), 2),
                "vix_5d_roc": round(float(day_vix_roc), 1),
                "vvix_5d_roc": round(float(day_vvix_roc), 1),
                "cor1m_5d_change": round(float(day_cor1m_5d_chg), 2),
            }
        )

    return {
        "date": common_dates[-1],
        "vix": round(vix_now, 2),
        "vvix": round(vvix_now, 2),
        "spy": round(spy_now, 2),
        "vix_5d_roc": round(float(vix_5d_roc), 1),
        "vvix_5d_roc": round(float(vvix_5d_roc), 1),
        "vvix_vix_ratio": round(float(vvix_vix_ratio), 2)
        if not math.isnan(vvix_vix_ratio)
        else None,
        "spx_100d_ma": round(ma_100, 2) if not math.isnan(ma_100) else None,
        "spx_distance_pct": round(float(spx_distance_pct), 2),
        "cor1m": round(cor1m_now, 2) if not math.isnan(cor1m_now) else None,
        "cor1m_previous_close": round(cor1m_previous_close, 2)
        if not math.isnan(cor1m_previous_close)
        else None,
        "cor1m_5d_change": round(cor1m_5d_change, 2)
        if not math.isnan(cor1m_5d_change)
        else None,
        "realized_vol": round(realized_vol, 2)
        if not math.isnan(realized_vol)
        else None,
        "cri": cri,
        "cta": cta,
        "crash_trigger": trigger,
        "history": history,
        # Last 40 SPY daily closes so the UI/API can rebuild a trailing
        # 20-session realized-vol curve client-side if needed.
        "spy_closes": [round(float(p), 4) for p in spy[-(VOL_WINDOW * 2) :]],
    }
