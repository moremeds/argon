"""CRI scoring primitives — pure component scorers + composite + CTA + crash trigger.

Split out of `cri_scoring.py` (2026-05-20 alongside the v3 calibration) to
keep both modules well under the 500-line budget. `cri_scoring.py` retains
the orchestrator (`run_analysis`) and re-exports everything here so existing
`from uw_scan.cards.cri_scoring import ...` imports continue to work.

No DB, no network. Pure math.

Strategy reference: docs/research/regime/cri-methodology.md
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# ── constants ─────────────────────────────────────────────────────
MA_WINDOW = 100  # SPX moving average window
VOL_WINDOW = 20  # Realized vol window (annualized)

# Composite scoring contract version.
# v1: original calibration (VIX floor 15, RoC denom 60; VVIX floor 85; trend-break
#     0-25 single sub-score; saturates at -10% below 100d MA).
# v2: SPX-over-SPY preference + mean-reversion fields (no scorer math change).
# v3: VIX floor 13; VIX RoC denom 40; VVIX floor 80; Trend Break reshaped into
#     structural (0-15, vs 100d MA) + tactical (0-10, vs 20d high, sat at -4%).
COMPOSITE_VERSION = 3

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
    """Score VIX component (0-25). vix_5d_roc is in %.

    v3 calibration (2026-05-20): level floor lowered 15→13 so VIX in the
    14-18 band picks up signal; RoC denom 60→40 so a +30% week saturates the
    sub-score (a +40% week is the practical ceiling, +60% almost never).
    """
    if math.isnan(vix) or math.isnan(vix_5d_roc):
        return 0.0
    level_score = np.clip((vix - 13.0) / (40.0 - 13.0) * 15.0, 0.0, 15.0)
    roc_score = np.clip(max(vix_5d_roc, 0.0) / 40.0 * 10.0, 0.0, 10.0)
    return float(np.clip(level_score + roc_score, 0.0, 25.0))


def score_vvix_component(
    vvix: float, vvix_vix_ratio: float, vvix_5d_roc: float
) -> float:
    """Score VVIX component (0-25).

    Three sub-scores; see docs/research/regime/cri-methodology.md §3 for rationale.
      - level  (0-12): VVIX absolute level, clipped 80→130 (v3 floor 80)
      - ratio  (0-7):  VVIX/VIX ratio, clipped 5→8 (practitioner warning band)
      - roc    (0-6):  VVIX 5d rate-of-change, one-sided, clipped 0→25%

    NaN policy: missing VVIX or ratio collapses the whole score to 0
    (calibration assumes both are present). NaN RoC is treated as 0 — it's
    an enhancement, not a gate.
    """
    if math.isnan(vvix) or math.isnan(vvix_vix_ratio):
        return 0.0
    if math.isnan(vvix_5d_roc):
        vvix_5d_roc = 0.0
    # v3 calibration: level floor lowered 85→80 to match the same tactical
    # sensitivity the VIX scorer gained (VVIX rarely sits below 80; the prior
    # 85 floor meant the entire 80-94 band was a dead zone).
    level_score = np.clip((vvix - 80.0) / (130.0 - 80.0) * 12.0, 0.0, 12.0)
    ratio_score = np.clip((vvix_vix_ratio - 5.0) / (8.0 - 5.0) * 7.0, 0.0, 7.0)
    roc_score = np.clip(max(vvix_5d_roc, 0.0) / 25.0 * 6.0, 0.0, 6.0)
    return float(np.clip(level_score + ratio_score + roc_score, 0.0, 25.0))


def score_correlation_component(corr: float, corr_5d_change: float) -> float:
    """Score COR1M component (0-25). corr in % points."""
    if math.isnan(corr):
        return 0.0
    if math.isnan(corr_5d_change):
        corr_5d_change = 0.0
    level_score = np.clip((corr - 25.0) / (70.0 - 25.0) * 17.0, 0.0, 17.0)
    spike_score = np.clip(max(corr_5d_change, 0.0) / 20.0 * 8.0, 0.0, 8.0)
    return float(np.clip(level_score + spike_score, 0.0, 25.0))


def score_momentum_component(
    spx_distance_pct: float,
    pullback_20d_pct: float = 0.0,
) -> float:
    """Score Trend Break component (0-25) — structural + tactical (v3).

    Structural sub-score (0-15): rises linearly with |SPX/SPX_100d_MA − 1|
    when SPX is below the 100d MA, saturating at −10%. Captures regime
    breakdown.

    Tactical sub-score (0-10): rises linearly with the drawdown from the
    trailing-20-session high, saturating at −4%. Fires even when SPX is
    above the 100d MA — captures choppy multi-session sell-offs that
    wouldn't have shown up in v1/v2.

    Total = clip(structural + tactical, 0, 25). See
    docs/research/regime/cri-methodology.md §3 (v3).
    """
    if math.isnan(spx_distance_pct) or spx_distance_pct >= 0:
        structural = 0.0
    else:
        structural = float(np.clip(abs(spx_distance_pct) / 10.0 * 15.0, 0.0, 15.0))

    if (
        pullback_20d_pct is None
        or math.isnan(pullback_20d_pct)
        or pullback_20d_pct >= 0
    ):
        tactical = 0.0
    else:
        tactical = float(np.clip(abs(pullback_20d_pct) / 4.0 * 10.0, 0.0, 10.0))

    return float(np.clip(structural + tactical, 0.0, 25.0))


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
    vvix_5d_roc: float,
    corr: float,
    corr_5d_change: float,
    spx_distance_pct: float,
    pullback_20d_pct: float = 0.0,
) -> dict[str, Any]:
    """Composite 0-100 score from the four components.

    v3: the momentum component takes both structural (vs 100d MA) and
    tactical (vs 20d high) inputs. See ``score_momentum_component``.
    """
    vix_score = score_vix_component(vix, vix_5d_roc)
    vvix_score = score_vvix_component(vvix, vvix_vix_ratio, vvix_5d_roc)
    corr_score = score_correlation_component(corr, corr_5d_change)
    momentum_score = score_momentum_component(spx_distance_pct, pullback_20d_pct)
    total = float(
        np.clip(vix_score + vvix_score + corr_score + momentum_score, 0.0, 100.0)
    )
    return {
        "score": round(total, 1),
        "level": cri_level(total),
        "composite_version": COMPOSITE_VERSION,
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
