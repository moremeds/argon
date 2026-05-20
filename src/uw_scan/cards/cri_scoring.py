"""Crash Risk Indicator (CRI) — orchestrator (run_analysis) on top of cri_scorers.

The pure component scorers, composite, CTA model, and crash trigger live in
`cri_scorers.py`. This module owns the orchestration that takes aligned
daily-close arrays and emits a snapshot payload. All names previously
exported from `cri_scoring` are re-exported below so existing imports keep
working.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from uw_scan.cards.cri_scorers import (  # noqa: F401 — re-export for back-compat
    COMPOSITE_VERSION,
    CRASH_COR1M_THRESHOLD,
    CRASH_REALIZED_VOL_THRESHOLD,
    CTA_AUM_BN,
    CTA_MAX_EXPOSURE,
    CTA_VOL_TARGET,
    MA_WINDOW,
    VOL_WINDOW,
    compute_cri,
    compute_realized_vol,
    cor1m_level_and_change,
    crash_trigger,
    cri_level,
    cta_exposure_model,
    score_correlation_component,
    score_momentum_component,
    score_vix_component,
    score_vvix_component,
)
from uw_scan.cards.mean_reversion import (
    compute_pullback_20d,
    compute_vix_delta_3d,
    compute_vrp,
    vix_vix3m_ratio,
    vix_zscore_30d,
)

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
    cor1m_values = aligned["COR1M"]

    # SPX is the right instrument for trend/RV math because the CBOE vol
    # indices (VIX/VVIX/COR1M) are computed against SPX. Fall back to SPY
    # for transition safety while the SPX backfill is rolling out.
    if "SPX" in aligned and len(aligned["SPX"]) > 0:
        spy = aligned["SPX"]
        spx_source = "SPX"
    else:
        spy = aligned["SPY"]
        spx_source = "SPY"

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

    vix3m_arr = aligned.get("VIX3M")
    vix3m_now = (
        float(vix3m_arr[-1])
        if vix3m_arr is not None and len(vix3m_arr) > 0
        else float("nan")
    )
    vrp = compute_vrp(vix=vix_now, realized_vol=realized_vol)
    vix_z = vix_zscore_30d(vix)
    vix_ts_ratio = vix_vix3m_ratio(vix=vix_now, vix3m=vix3m_now)

    # v3: tactical-pullback input for the trend-break component and the
    # VIX-velocity tile in the UI.
    pullback_20d_pct = compute_pullback_20d(spy)
    vix_delta_3d = compute_vix_delta_3d(vix)
    pullback_for_score = pullback_20d_pct if not math.isnan(pullback_20d_pct) else 0.0

    cri = compute_cri(
        vix=vix_now,
        vix_5d_roc=float(vix_5d_roc),
        vvix=vvix_now,
        vvix_vix_ratio=float(vvix_vix_ratio),
        vvix_5d_roc=float(vvix_5d_roc),
        corr=cor1m_now,
        corr_5d_change=cor1m_5d_change,
        spx_distance_pct=float(spx_distance_pct),
        pullback_20d_pct=float(pullback_for_score),
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
        # v3: pullback from 20d rolling high — feeds the UI prior-dot for the
        # tactical sub-score of Trend Break.
        if i >= 19:  # need at least 20 closes
            day_pullback = compute_pullback_20d(spy[: i + 1])
        else:
            day_pullback = float("nan")
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
                "pullback_20d_pct": round(float(day_pullback), 2)
                if not math.isnan(day_pullback)
                else None,
            }
        )

    return {
        "date": common_dates[-1],
        "vix": round(vix_now, 2),
        "vvix": round(vvix_now, 2),
        "spy": round(spy_now, 2),
        "spx_source": spx_source,
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
        "vix3m": round(vix3m_now, 2) if not math.isnan(vix3m_now) else None,
        "vrp": round(vrp, 2) if not math.isnan(vrp) else None,
        "vix_zscore_30d": round(vix_z, 2) if not math.isnan(vix_z) else None,
        "vix_vix3m_ratio": round(vix_ts_ratio, 3)
        if not math.isnan(vix_ts_ratio)
        else None,
        "pullback_20d_pct": round(pullback_20d_pct, 2)
        if not math.isnan(pullback_20d_pct)
        else None,
        "vix_delta_3d": round(vix_delta_3d, 2)
        if not math.isnan(vix_delta_3d)
        else None,
        "cri": cri,
        "cta": cta,
        "crash_trigger": trigger,
        "history": history,
        # Last 40 SPY daily closes so the UI/API can rebuild a trailing
        # 20-session realized-vol curve client-side if needed.
        "spy_closes": [round(float(p), 4) for p in spy[-(VOL_WINDOW * 2) :]],
    }
