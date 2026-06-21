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
