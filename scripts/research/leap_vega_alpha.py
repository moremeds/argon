"""Pure library for the LEAP vega-alpha feasibility spike (read-only research).

realized_vol / atm_iv / entry_gap / stage1_metrics / cross_sectional_ic — no I/O,
unit-tested. Consumed by scripts/research/leap_convergence_probe.py (Stage 1) and
leap_pnl_probe.py (Stage 2). Reuses forward_from_delta from svi_fit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from scipy.stats import spearmanr


def realized_vol(
    closes: Sequence[float], window: int, ann: float = 252.0
) -> float | None:
    """Annualized sample stdev of daily log returns over the trailing ``window`` returns."""
    if closes is None or len(closes) < window + 1:
        return None
    tail = np.asarray(closes[-(window + 1) :], dtype=float)
    rets = np.diff(np.log(tail))
    return float(np.std(rets, ddof=1) * np.sqrt(ann))


def atm_iv(rows: list[dict], max_delta_dist: float = 0.10) -> float | None:
    """ATM IV linearly interpolated at call_delta==0.5 (matches forward_from_delta).

    Interpolation kills the strike-grid jitter that a nearest-strike pick suffers on
    coarse LEAP chains. Falls back to the nearest-0.5-delta strike only when no pair
    brackets 0.5, and returns None if that nearest delta is > max_delta_dist away.
    """
    pts = sorted(
        (float(r["call_delta"]), float(r["call_iv"]))
        for r in rows
        if r.get("call_delta") is not None and r.get("call_iv") is not None
    )
    if not pts:
        return None
    for (d0, iv0), (d1, iv1) in zip(pts, pts[1:]):  # bracket 0.5 -> interp in delta
        if (d0 - 0.5) * (d1 - 0.5) <= 0.0 and d0 != d1:
            return iv0 + (0.5 - d0) / (d1 - d0) * (iv1 - iv0)
    d_near, iv_near = min(pts, key=lambda p: abs(p[0] - 0.5))
    return iv_near if abs(d_near - 0.5) <= max_delta_dist else None


def entry_gap(
    hv20: float | None, hv60: float | None, atm: float | None
) -> float | None:
    """max(hv20, hv60) - atm_iv, all decimal. None if atm missing or both HVs missing."""
    if atm is None:
        return None
    hvs = [h for h in (hv20, hv60) if h is not None]
    if not hvs:
        return None
    return max(hvs) - atm


def stage1_metrics(gaps, d_ivs, threshold: float) -> dict:
    """Convergence metrics: rank-IC of gap vs forward ΔIV, plus flagged-subset stats.

    This is the CONFOUNDED POOLED secondary metric — regime drift inflates rank_ic /
    hit_rate. Reported for context; the gate keys on cross_sectional_ic (single-name).
    """
    g = np.asarray(gaps, dtype=float)
    d = np.asarray(d_ivs, dtype=float)
    n = int(g.size)
    rank_ic = (
        float(spearmanr(g, d).statistic)
        if n >= 2 and np.std(g) > 0 and np.std(d) > 0
        else float("nan")
    )
    flagged = g >= threshold
    fn = int(flagged.sum())
    return {
        "n": n,
        "rank_ic": rank_ic,
        "baseline_mean_div": float(d.mean()) if n else float("nan"),
        "flagged_n": fn,
        "flagged_mean_div": float(d[flagged].mean()) if fn else float("nan"),
        "hit_rate": float((d[flagged] > 0).mean()) if fn else float("nan"),
    }


def cross_sectional_ic(records, threshold: float) -> dict:
    """Fama-MacBeth primary metric: per-date cross-sectional IC + within-date
    differential harvest, averaged across dates. Cancels the regime-common IV move.

    ``records`` each have ``market_date``, ``gap``, ``d_iv`` (caller pre-filters to one
    horizon). ``ic_t_stat`` is the FM t; autocorrelation across overlapping dates still
    inflates it, so the non-overlapping run is the binding significance.
    """
    by_date: dict = defaultdict(list)
    for r in records:
        by_date[r["market_date"]].append(r)
    ics, diffs = [], []
    for recs in by_date.values():
        g = np.array([x["gap"] for x in recs], dtype=float)
        d = np.array([x["d_iv"] for x in recs], dtype=float)
        if g.size >= 2 and np.std(g) > 0 and np.std(d) > 0:
            ics.append(float(spearmanr(g, d).statistic))
        flagged = g >= threshold
        if flagged.any():
            diffs.append(float(d[flagged].mean() - d.mean()))  # demeaned within date
    ic = np.array(ics, dtype=float)
    df = np.array(diffs, dtype=float)
    t = (
        float(ic.mean() / (ic.std(ddof=1) / np.sqrt(ic.size)))
        if ic.size >= 2 and ic.std(ddof=1) > 0
        else float("nan")
    )
    return {
        "n_dates": int(ic.size),
        "mean_ic": float(ic.mean()) if ic.size else float("nan"),
        "ic_t_stat": t,
        "mean_diff_harvest": float(df.mean()) if df.size else float("nan"),
    }
