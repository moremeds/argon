"""5% Canary scoring — pure math, no IO.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §6.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Literal, Sequence

from uw_scan.cards.canary_calibration import SignalThresholds

ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


class NormalizationError(ValueError):
    """Raised when scorer inputs contain NaN or non-finite values."""


def _require_finite_number(value: float, *, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise NormalizationError(f"{name} must be finite, got {value!r}")
    return out


def _require_finite_sequence(values, *, name: str) -> list[float]:
    return [
        _require_finite_number(v, name=f"{name}[{i}]") for i, v in enumerate(values)
    ]


def _clip01(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x


def ramp(
    value: float,
    *,
    floor: float,
    ceiling: float,
    max_points: float,
    form: ScoreForm = "linear",
) -> float:
    """Map ``value`` in [floor, ceiling] to a score in [0, max_points] using
    one of four functional forms. Returns 0 below floor, max_points above ceiling.
    """
    value = _require_finite_number(value, name="value")
    floor = _require_finite_number(floor, name="floor")
    ceiling = _require_finite_number(ceiling, name="ceiling")
    max_points = _require_finite_number(max_points, name="max_points")
    if ceiling <= floor:
        raise ValueError(f"ceiling ({ceiling}) must exceed floor ({floor})")
    # v0.4 patch I1: clamp endpoints explicitly so EVERY form (including sigmoid)
    # honors the floor-returns-0 / ceiling-returns-max_points contract.
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return float(max_points)
    norm = (value - floor) / (ceiling - floor)
    if form == "linear":
        return max_points * norm
    if form == "convex":
        return max_points * (norm**1.5)
    if form == "concave":
        return max_points * (norm**0.5)
    if form == "sigmoid":
        # Centered at 0.5 in normalized space, k=10 for steep transition.
        # Endpoints already handled by the clamp above.
        return max_points / (1.0 + math.exp(-10.0 * (norm - 0.5)))
    raise ValueError(f"unknown form: {form}")


# ─── Smooth signal scorers ──────────────────────────────────────


@dataclass(frozen=True)
class SmoothSignalScore:
    score: float
    gate_active: bool
    diagnostics: dict[str, float]


def score_vix_spike_revert(
    vix_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Whaley-derived VIX spike-and-reversion."""
    vix_history = _require_finite_sequence(vix_history, name="vix_history")
    lookback = int(th.extras["peak_lookback_d"])
    spike_threshold = float(th.extras["spike_active_at_vix"])
    if len(vix_history) < lookback:
        return SmoothSignalScore(0.0, False, {"reason": float("nan")})
    vix_today = vix_history[-1]
    vix_peak = max(vix_history[-lookback:])
    spike_active = vix_peak >= spike_threshold
    pullback_pct = max(0.0, (vix_peak - vix_today) / vix_peak) if vix_peak > 0 else 0.0
    if not spike_active:
        return SmoothSignalScore(
            0.0, False, {"vix_peak": vix_peak, "pullback_pct": pullback_pct}
        )
    s = ramp(
        pullback_pct,
        floor=th.floor,
        ceiling=th.ceiling,
        max_points=th.max_points,
        form=form,
    )
    return SmoothSignalScore(
        s, True, {"vix_peak": vix_peak, "pullback_pct": pullback_pct}
    )


def score_vix_vix3m_back(
    vix_history: Sequence[float],
    vix3m_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Backwardation-normalizing — v0.3 reframe of raw backwardation.

    Score fires when the VIX/VIX3M ratio peaks above ``backwardation_extreme_at_ratio``
    in the lookback window AND has subsequently normalized; the magnitude of
    normalization is what feeds the ramp.
    """
    vix_history = _require_finite_sequence(vix_history, name="vix_history")
    vix3m_history = _require_finite_sequence(vix3m_history, name="vix3m_history")
    lookback = int(th.extras["peak_lookback_d"])
    extreme_th = float(th.extras["backwardation_extreme_at_ratio"])
    if (
        len(vix_history) < lookback
        or len(vix3m_history) < lookback
        or vix3m_history[-1] == 0
    ):
        return SmoothSignalScore(0.0, False, {})
    ratios = [
        v / m for v, m in zip(vix_history[-lookback:], vix3m_history[-lookback:]) if m
    ]
    if not ratios:
        return SmoothSignalScore(0.0, False, {})
    ratio_today = vix_history[-1] / vix3m_history[-1]
    ratio_peak = max(ratios)
    extreme = ratio_peak >= extreme_th
    norm_pct = (
        max(0.0, (ratio_peak - ratio_today) / ratio_peak) if ratio_peak > 0 else 0.0
    )
    if not extreme:
        return SmoothSignalScore(
            0.0,
            False,
            {
                "ratio_peak": ratio_peak,
                "ratio_today": ratio_today,
                "norm_pct": norm_pct,
            },
        )
    s = ramp(
        norm_pct,
        floor=th.floor,
        ceiling=th.ceiling,
        max_points=th.max_points,
        form=form,
    )
    return SmoothSignalScore(
        s,
        True,
        {"ratio_peak": ratio_peak, "ratio_today": ratio_today, "norm_pct": norm_pct},
    )


def score_vrp(
    vix_today: float,
    spx_log_returns: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Bollerslev/Tauchen/Zhou VRP."""
    vix_today = _require_finite_number(vix_today, name="vix_today")
    spx_log_returns = _require_finite_sequence(spx_log_returns, name="spx_log_returns")
    rv_window = int(th.extras["rv_window_d"])
    if len(spx_log_returns) < rv_window or vix_today <= 0:
        return SmoothSignalScore(0.0, False, {})
    sample = list(spx_log_returns[-rv_window:])
    rv_annual_pct = statistics.pstdev(sample) * math.sqrt(252) * 100.0
    vrp = (vix_today**2) - (rv_annual_pct**2)
    s = ramp(
        vrp, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form
    )
    return SmoothSignalScore(
        s,
        True,
        {"vix2": vix_today**2, "rv2_20d": rv_annual_pct**2, "vrp": vrp},
    )


def score_cor1m_decay(
    cor1m_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Correlation peak-and-decay (Driessen/Maenhout/Vilkov framing)."""
    cor1m_history = _require_finite_sequence(cor1m_history, name="cor1m_history")
    lookback = int(th.extras["peak_lookback_d"])
    elevated_th = float(th.extras["peak_elevated_at"])
    if len(cor1m_history) < lookback:
        return SmoothSignalScore(0.0, False, {})
    today = cor1m_history[-1]
    peak = max(cor1m_history[-lookback:])
    elevated = peak >= elevated_th
    decay_pct = max(0.0, (peak - today) / peak) if peak > 0 else 0.0
    if not elevated:
        return SmoothSignalScore(
            0.0,
            False,
            {"peak_60d": peak, "current": today, "decay_pct": decay_pct},
        )
    s = ramp(
        decay_pct,
        floor=th.floor,
        ceiling=th.ceiling,
        max_points=th.max_points,
        form=form,
    )
    return SmoothSignalScore(
        s,
        True,
        {"peak_60d": peak, "current": today, "decay_pct": decay_pct},
    )


def score_vvix_vix_recovery(
    vvix_history: Sequence[float],
    vix_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """VVIX/VIX ratio recovery from compressed regime."""
    vvix_history = _require_finite_sequence(vvix_history, name="vvix_history")
    vix_history = _require_finite_sequence(vix_history, name="vix_history")
    lookback = int(th.extras["compress_lookback_d"])
    compressed_th = float(th.extras["compressed_below_ratio"])
    if (
        len(vvix_history) < lookback
        or len(vix_history) < lookback
        or vix_history[-1] == 0
    ):
        return SmoothSignalScore(0.0, False, {})
    ratios = [
        v / x for v, x in zip(vvix_history[-lookback:], vix_history[-lookback:]) if x
    ]
    if not ratios:
        return SmoothSignalScore(0.0, False, {})
    ratio_today = vvix_history[-1] / vix_history[-1]
    ratio_min = min(ratios)
    compressed = ratio_min <= compressed_th
    if not compressed:
        return SmoothSignalScore(
            0.0, False, {"current": ratio_today, "min_60d": ratio_min}
        )
    s = ramp(
        ratio_today,
        floor=th.floor,
        ceiling=th.ceiling,
        max_points=th.max_points,
        form=form,
    )
    return SmoothSignalScore(s, True, {"current": ratio_today, "min_60d": ratio_min})
