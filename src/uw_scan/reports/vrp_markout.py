"""VRP harvest markout (Spec B) — does selling rich vol earn a reliable premium?

Read-only over vrp_daily (+ flow_events earnings reconstruction); writes
vrp_harvest_verdicts. Mirrors the skew markout's OOS discipline (walk-forward
holdout + per-quarter catastrophic gate) but tests the ABSOLUTE harvest level,
not a cross-sectionally demeaned reversion.

Deliberately does NOT import skew_markout's private helpers: no cross-module
consumer of those underscore-prefixed functions exists in this repo, and the
spec forbids modifying skew_markout.py. The one shared primitive — the
trading-day forward read — is reimplemented here (small, pure, self-contained).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as _date

# (Tasks 3 and 4 append more imports — defaultdict, logging, typing.Any, and the
# asset-class/Repository imports — each in the task that first uses them, so every
# task's commit stays lint-clean.)

# --- Signal thresholds (spec §Signal) -------------------------------------
RICH_Z = 1.0
CHEAP_Z = -1.0

# Forward horizon for the harvest read (spec §Forward target): trailing-21d RV
# read 20 trading days forward ≈ realized vol over [t, t+20]. The earnings
# exclusion window uses the ACTUAL forward trading date (the 20th forward row),
# not a calendar offset — so no separate window-days constant is needed.
HORIZON = 20


def _deviation_class(vrp_z: float | None) -> str | None:
    """RICH/NORMAL/CHEAP from the 20d VRP z-score; None when the signal is null."""
    if vrp_z is None:
        return None
    if vrp_z >= RICH_Z:
        return "RICH"
    if vrp_z <= CHEAP_Z:
        return "CHEAP"
    return "NORMAL"


def _earnings_in_window(t: _date, end: _date, earnings: set[_date]) -> bool:
    """True if any earnings date falls in (t, end] — the forward markout window
    straddles a known earnings event (the short-vol trap we exclude)."""
    return any(t < e <= end for e in earnings)


def _harvest_obs(rows: list[dict], *, earnings: set[_date]) -> list[dict]:
    """Build realized-VRP observations for one ticker.

    rows: vrp_daily rows [{market_date, iv, rv, vrp_z_20}], any order. There is
    one row per trading day, so the EXACT 20th trading day forward is the row at
    position i + HORIZON in the date-sorted list (positional — NOT a non-null-RV
    skip; an interior null RV must not shift the target).
    realized_VRP(t) = iv(t) - rv(t+20). Drops an anchor when: its signal or iv is
    null, there is no i+HORIZON row yet (recent tail), the exact t+20 row's rv is
    null, or an earnings date falls in (t, t+20]. Values may be Decimal — coerced
    to float."""
    ordered = sorted(rows, key=lambda r: r["market_date"])
    n = len(ordered)
    obs: list[dict] = []
    for i, r in enumerate(ordered):
        t = r["market_date"]
        # vrp_z_20 is NULL (never NaN) when undefined — the first ~19 rows per
        # ticker, before the 20d rolling z-score is defined. persist_vrp_daily's
        # _dec converts NaN→None (volatility_series.py), so None is the only
        # "missing" sentinel here and _deviation_class(None) → None → skipped.
        dev = _deviation_class(None if r["vrp_z_20"] is None else float(r["vrp_z_20"]))
        if dev is None or r["iv"] is None:
            continue
        j = i + HORIZON
        if j >= n:
            continue  # no forward target yet
        fwd = ordered[j]
        if fwd["rv"] is None:
            continue  # exact t+20 RV missing → cannot score this anchor
        if _earnings_in_window(t, fwd["market_date"], earnings):
            continue
        obs.append(
            {
                "market_date": t,
                "deviation_class": dev,
                "realized_vrp": float(r["iv"]) - float(fwd["rv"]),
            }
        )
    return obs


# --- OOS hygiene (spec §Out-of-sample hygiene) ----------------------------
MIN_N = 20
HOLDOUT_FRAC = 0.40
HARVEST_THRESHOLD = 0.02  # full-sample floor: 2 vol points; decimal vols (iv/rv ~0.20).
HOLDOUT_THRESHOLD = (
    0.01  # relaxed holdout floor (~half), mirrors skew's 0.003/0.005 ratio.
)


def _survives_quarter_gate(obs: list[dict], overall_mean: float) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule:
    feedback_per_regime_catastrophic_gate; mirrors skew_markout's window gate).
    Fail if ANY quarter's mean realized_VRP reverses the aggregate sign with
    LARGER magnitude — the aggregate is hiding a sub-window blowup. A near-zero
    aggregate auto-fails (no stable edge to defend)."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o["realized_vrp"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _walkforward_harvest(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float = HARVEST_THRESHOLD,
    holdout_threshold: float = HOLDOUT_THRESHOLD,
) -> dict:
    """Walk-forward holdout on the ABSOLUTE harvest mean. The harvest claim is
    that mean realized_VRP is POSITIVE (selling rich vol earns premium).

    Descriptive means (mean_realized_vrp, mean_holdout) are ALWAYS computed when
    n >= 1 so a sub-min_n bucket still exposes conditioning evidence (AC3); only
    the gate booleans depend on min_n. survives_walkforward requires: n >= min_n,
    full mean >= threshold, holdout mean >= holdout_threshold, AND full and
    holdout means both positive (spec §OOS 'agree in sign and clear a magnitude
    floor'). survives_window_gate is the per-quarter gate on the full sample.
    Holdout = latest HOLDOUT_FRAC of obs by market_date (time-ordered, no leak).
    obs: [{'realized_vrp': float, 'market_date': date}]."""
    n = len(obs)
    if n == 0:
        return {
            "mean_realized_vrp": None,
            "mean_holdout": None,
            "n": 0,
            "n_holdout": 0,
            "survives_walkforward": False,
            "survives_window_gate": False,
        }
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o["realized_vrp"] for o in ordered) / n
    mean_hold = (
        sum(o["realized_vrp"] for o in holdout) / len(holdout) if holdout else None
    )
    if n < min_n:
        survives_wf = False
        survives_window = False
    else:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (
            mean_hold is not None and mean_hold >= holdout_threshold
        )
        survives_wf = bool(sign_ok and mag_ok)
        survives_window = _survives_quarter_gate(ordered, mean_full)
    return {
        "mean_realized_vrp": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }
