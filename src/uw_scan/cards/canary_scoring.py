"""5% Canary scoring — pure math, no IO.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §6.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Literal, NamedTuple, Sequence

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


# ─── Primary event state machine (Task 6) ───────────────────────


@dataclass
class CanaryEvent:
    kind: str  # '5pct_canary' | 'buy_the_dip' | 'confirmed_canary'
    fire_date: _date


@dataclass
class CanaryEventState:
    """Mutable per-day state. Persisted in payload.speed.anchor for replay."""

    last_high_date: _date | None = None
    last_high_value: float = float("nan")
    canary_fired_for_high: bool = False
    btd_fired_for_high: bool = False
    open_canary_windows: list[dict] = field(default_factory=list)
    emitted: list[CanaryEvent] = field(default_factory=list)


HIGH_LOOKBACK_DAYS = 252
# v0.4 patch: T+0..T+42 inclusive = 43 observations. Aligns with Thrasher's
# published "42 days later" forward-return horizon (Table 2) which counts the
# fire day itself as T+0. When slicing by trading-day count, use
# trading_days_since_fire <= SPEED_ACTIVITY_WINDOW_DAYS — NOT a [-42:] slice.
SPEED_ACTIVITY_WINDOW_DAYS = 42
CANARY_FAST_THRESHOLD_DAYS = 15


def step_primary_events(
    state: CanaryEventState,
    *,
    today: _date,
    spx_close_today: float,
    spx_history: Sequence[tuple],  # ordered ascending, today inclusive: (date, close)
    sma_50_today: float,
    sma_200_today: float,
    trading_days_between,  # callable(a, b) -> int
) -> CanaryEventState:
    """Update anchor state and emit any new 5pct_canary / buy_the_dip event for ``today``."""
    # 1. Anchor update: did today print a new 252d closing high?
    if len(spx_history) >= HIGH_LOOKBACK_DAYS:
        window = [v for _, v in spx_history[-HIGH_LOOKBACK_DAYS:]]
        if spx_close_today >= max(window):
            state.last_high_date = today
            state.last_high_value = spx_close_today
            state.canary_fired_for_high = False
            state.btd_fired_for_high = False
            # v0.4: also invalidate any open confirmation windows. A new 252d
            # high means a prior bearish episode is over — its open Confirmed-
            # Canary window should NOT survive to fire a stale confirmation
            # after the recovery.
            state.open_canary_windows.clear()
            return state

    if state.last_high_date is None:
        return state

    days_since_high = trading_days_between(state.last_high_date, today)
    five_pct_breach = spx_close_today <= 0.95 * state.last_high_value

    if not five_pct_breach:
        return state

    # Anchor invariant: at most one primary event per 252d high anchor.
    primary_event_fired = state.canary_fired_for_high or state.btd_fired_for_high
    if primary_event_fired:
        return state

    if days_since_high <= CANARY_FAST_THRESHOLD_DAYS:
        state.emitted.append(CanaryEvent(kind="5pct_canary", fire_date=today))
        state.canary_fired_for_high = True
        state.open_canary_windows.append(
            {
                "canary_fire_date": today,
                "expires_after_td": SPEED_ACTIVITY_WINDOW_DAYS,
                "consec_below_sma200": 0,
                "td_elapsed": 0,
            }
        )
    elif days_since_high > CANARY_FAST_THRESHOLD_DAYS and sma_50_today > sma_200_today:
        state.emitted.append(CanaryEvent(kind="buy_the_dip", fire_date=today))
        state.btd_fired_for_high = True
    return state


# ─── Confirmed Canary state machine (Task 7) ────────────────────


def step_confirmed_canary(
    state: CanaryEventState,
    *,
    today: _date,
    spx_close_today: float,
    sma_200_today: float,
) -> CanaryEventState:
    """Advance each open Confirmed-Canary window by one trading day.

    Emits a 'confirmed_canary' event on the day the 2nd consecutive close
    below SMA-200 occurs inside any open window. Causal — no forward lookup.
    """
    if not state.open_canary_windows:
        return state

    below_sma200 = spx_close_today < sma_200_today
    kept_windows: list[dict] = []
    for win in state.open_canary_windows:
        # v0.4 patch: Fire day is T+0. The scanner may call this immediately
        # after opening the window on the same date, so do not advance
        # elapsed trading days until the first later trading date.
        if today == win["canary_fire_date"]:
            win["td_elapsed"] = 0
        else:
            win["td_elapsed"] += 1
        if win["td_elapsed"] > win["expires_after_td"]:
            continue  # expired — drop
        if below_sma200:
            win["consec_below_sma200"] += 1
        else:
            win["consec_below_sma200"] = 0
        if win["consec_below_sma200"] >= 2:
            state.emitted.append(CanaryEvent(kind="confirmed_canary", fire_date=today))
            # Window is consumed on confirmation.
            continue
        kept_windows.append(win)
    state.open_canary_windows = kept_windows
    return state


# ─── Speed score + cap rule + band map (Task 8) ─────────────────


class SpeedScore(NamedTuple):
    score: int
    state: str  # 'NEUTRAL' | 'CONFIRMED_CANARY_ACTIVE' | 'BUY_THE_DIP_ACTIVE' | 'BOTH_ACTIVE_AMBIGUOUS'
    confirmed_canary_active: bool
    buy_the_dip_active: bool


def derive_speed(
    *, confirmed_canary_active: bool, buy_the_dip_active: bool
) -> SpeedScore:
    if confirmed_canary_active and buy_the_dip_active:
        return SpeedScore(8, "BOTH_ACTIVE_AMBIGUOUS", True, True)
    if confirmed_canary_active:
        return SpeedScore(0, "CONFIRMED_CANARY_ACTIVE", True, False)
    if buy_the_dip_active:
        return SpeedScore(20, "BUY_THE_DIP_ACTIVE", False, True)
    return SpeedScore(8, "NEUTRAL", False, False)


class CapResult(NamedTuple):
    final_score: float
    warning_state: str
    cap_applied: bool


def apply_cap(
    *,
    raw_score: float,
    speed: SpeedScore,
    spx_above_sma200_2d: bool,
    vix_term_normalized: bool,
    higher_closing_low: bool,
) -> CapResult:
    cap_cleared_early = spx_above_sma200_2d or (
        vix_term_normalized and higher_closing_low
    )
    if speed.state == "CONFIRMED_CANARY_ACTIVE":
        if cap_cleared_early:
            return CapResult(raw_score, "NONE", False)
        capped = min(raw_score, 49.0)
        return CapResult(capped, "CONFIRMED_CANARY_ACTIVE", raw_score > 49.0)
    if speed.state == "BOTH_ACTIVE_AMBIGUOUS":
        capped = min(raw_score, 49.0)
        return CapResult(capped, "BOTH_ACTIVE_AMBIGUOUS", raw_score > 49.0)
    if speed.state == "BUY_THE_DIP_ACTIVE":
        return CapResult(raw_score, "BUY_THE_DIP_ACTIVE", False)
    return CapResult(raw_score, "NONE", False)


def compute_band(score: float) -> str:
    if score < 25.0:
        return "NONE"
    if score < 50.0:
        return "WATCH"
    if score < 75.0:
        return "BUY"
    return "STRONG_BUY"


def higher_closing_low_close_only(
    spx_close_history: Sequence[float],
    sma_200_today: float,
    spx_close_today: float,
) -> bool:
    """Close-only definition. Returns True iff:
    - min(last 5 closes) > min(prior 15 closes [-20:-5])
    - AND today close > sma_200 * 0.98
    """
    if len(spx_close_history) < 20:
        return False
    prior = min(spx_close_history[-20:-5])
    recent = min(spx_close_history[-5:])
    return recent > prior and spx_close_today > sma_200_today * 0.98


# ─── Top-level orchestrator (Task 10) ───────────────────────────


def run_analysis(
    *,
    today: _date,
    aligned: dict,  # {'VIX': np.ndarray, 'VVIX': ..., 'VIX3M': ..., 'COR1M': ..., 'SPX': ...}
    common_dates: list,  # iso dates corresponding to the aligned arrays
    sma_50_today: float,
    sma_200_today: float,
    spx_above_sma200_2d: bool,
    vix_term_normalized: bool,
    higher_closing_low: bool,
    confirmed_canary_active: bool,
    buy_the_dip_active: bool,
    calibration,  # Calibration
) -> dict:
    """Stitch the five smooth scorers + speed/cap into a single payload dict.

    Caller is responsible for running the event state machine
    (step_primary_events + step_confirmed_canary) over the full history and
    computing confirmed_canary_active / buy_the_dip_active before calling.
    """
    import numpy as np

    form = calibration.score_form
    vix = aligned["VIX"]
    vvix = aligned["VVIX"]
    vix3m = aligned["VIX3M"]
    cor = aligned["COR1M"]
    spx = aligned["SPX"]
    spx_arr = np.asarray(spx, dtype=float)
    log_returns = np.diff(np.log(spx_arr))[-20:].tolist()

    s_spike = score_vix_spike_revert(
        vix.tolist(), th=calibration.vix_spike_revert, form=form
    )
    s_back = score_vix_vix3m_back(
        vix.tolist(), vix3m.tolist(), th=calibration.vix_vix3m_back, form=form
    )
    s_vrp = score_vrp(float(vix[-1]), log_returns, th=calibration.vrp, form=form)
    s_cor = score_cor1m_decay(cor.tolist(), th=calibration.cor1m_decay, form=form)
    s_vvr = score_vvix_vix_recovery(
        vvix.tolist(), vix.tolist(), th=calibration.vvix_vix_recovery, form=form
    )

    tactical = s_spike.score + s_back.score
    structural = s_vrp.score + s_cor.score + s_vvr.score

    speed = derive_speed(
        confirmed_canary_active=confirmed_canary_active,
        buy_the_dip_active=buy_the_dip_active,
    )
    raw = tactical + structural + speed.score
    raw = max(0.0, min(100.0, raw))
    cap = apply_cap(
        raw_score=raw,
        speed=speed,
        spx_above_sma200_2d=spx_above_sma200_2d,
        vix_term_normalized=vix_term_normalized,
        higher_closing_low=higher_closing_low,
    )
    band = compute_band(cap.final_score)

    payload = {
        "date": today.isoformat(),
        "canary": {
            "score": round(cap.final_score, 2),
            "raw_score": round(raw, 2),
            "band": band,
            "warning_state": cap.warning_state,
            "composite_version": calibration.composite_version,
            "score_form": form,
            "cap_applied": cap.cap_applied,
            "cap_lift_conditions": {
                "spx_above_sma200_2d": spx_above_sma200_2d,
                "vix_term_normalized": vix_term_normalized,
                "higher_closing_low": higher_closing_low,
            },
        },
        "tactical_vol": {
            "score": round(tactical, 2),
            "vix_spike_revert": {
                "score": round(s_spike.score, 2),
                "gate_active": s_spike.gate_active,
                **s_spike.diagnostics,
            },
            "vix_vix3m_back": {
                "score": round(s_back.score, 2),
                "gate_active": s_back.gate_active,
                **s_back.diagnostics,
            },
        },
        "structural_vol": {
            "score": round(structural, 2),
            "vrp": {
                "score": round(s_vrp.score, 2),
                "gate_active": s_vrp.gate_active,
                **s_vrp.diagnostics,
            },
            "cor1m_decay": {
                "score": round(s_cor.score, 2),
                "gate_active": s_cor.gate_active,
                **s_cor.diagnostics,
            },
            "vvix_vix_recovery": {
                "score": round(s_vvr.score, 2),
                "gate_active": s_vvr.gate_active,
                **s_vvr.diagnostics,
            },
        },
        "speed": {
            "score": speed.score,
            "state": speed.state,
            "confirmed_canary_active": confirmed_canary_active,
            "buy_the_dip_active": buy_the_dip_active,
            "sma50_above_sma200": sma_50_today > sma_200_today,
        },
        "inputs": {
            "vix": float(vix[-1]),
            "vvix": float(vvix[-1]),
            "vix3m": float(vix3m[-1]) if not math.isnan(float(vix3m[-1])) else None,
            "cor1m": float(cor[-1]),
            "spx_close": float(spx[-1]),
            "sma_50": sma_50_today,
            "sma_200": sma_200_today,
        },
    }
    return payload
