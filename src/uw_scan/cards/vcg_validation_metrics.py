"""Metric battery for VCG composite vs single-proxy comparator.

All metric functions are pure and operate on:
- ro_signal: pd.Series[bool] indexed by trading date — True iff RO fires
  (tier 1 or tier 2) at close on that date.
- events: list[DrawdownEvent] for one (benchmark, drawdown_def).
- trading_days: ordered list[date] of valid trading sessions in the slice.

Lead-time metrics report two flavors:
- close_to_trough_lead — assumes signal usable on day-of-close (upper bound).
- actionable_lead — signal at close t is actionable on t+1 (causality contract).
Promotion gate uses actionable_lead only.

FP metrics use event INTERVAL [peak, trough] semantics, not peak-only: an RO
that fires after the event peak but before the event trough is a VALID
mid-drawdown warning. Reducing events to a single forward date would discard
those warnings as false positives and corrupt the promotion gate.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from datetime import date

import pandas as pd

from uw_scan.cards.drawdown import DrawdownEvent


def next_trading_day(d: date, trading_days: Sequence[date]) -> date | None:
    """First trading day strictly after ``d``."""
    i = bisect.bisect_right(list(trading_days), d)
    if i >= len(trading_days):
        return None
    return trading_days[i]


def _bday_count(start: date, end: date, trading_days: Sequence[date]) -> int:
    """Number of trading days from start to end inclusive of end, exclusive
    of start."""
    tds = list(trading_days)
    i = bisect.bisect_left(tds, start)
    j = bisect.bisect_right(tds, end)
    return j - i - 1


def close_to_trough_lead_days(
    ro_date: date, trough_date: date, trading_days: Sequence[date]
) -> int:
    return _bday_count(ro_date, trough_date, trading_days)


def actionable_lead_days(
    ro_date: date, trough_date: date, trading_days: Sequence[date]
) -> int:
    """Trading days between (next session after ro_date) and trough_date.

    Negative when next_trading_day(ro_date) > trough_date, e.g. RO at trough's
    close — fails the actionable_lead >= 0 gate.
    """
    nt = next_trading_day(ro_date, trading_days)
    if nt is None or nt > trough_date:
        # nt past the trough = signal couldn't have been acted upon in time.
        # Returning negative signals "missed" so hit_rate (which requires
        # actionable_lead >= 0) correctly excludes this event.
        return -1
    return _bday_count(nt, trough_date, trading_days) + 1  # +1: nt itself counts


def _first_ro_in_window(
    ro_signal: pd.Series,
    peak_date: date,
    trough_date: date,
    peak_lookback: int,
    trading_days: Sequence[date],
) -> date | None:
    tds = list(trading_days)
    peak_idx = bisect.bisect_left(tds, peak_date)
    start_idx = max(0, peak_idx - peak_lookback)
    start_date = tds[start_idx]
    window = ro_signal.loc[
        (ro_signal.index >= start_date) & (ro_signal.index <= trough_date)
    ]
    fired = window[window].index
    if len(fired) == 0:
        return None
    first = fired[0]
    return first.date() if hasattr(first, "date") else first


def hit_rate(
    events: list[DrawdownEvent],
    *,
    ro_signal: pd.Series,
    trading_days: Sequence[date],
    peak_lookback: int = 30,
) -> float:
    """events_with_actionable_RO / total_events."""
    if not events:
        return float("nan")
    hits = 0
    for e in events:
        ro = _first_ro_in_window(
            ro_signal, e.peak_date, e.trough_date, peak_lookback, trading_days
        )
        if ro is None:
            continue
        if actionable_lead_days(ro, e.trough_date, trading_days) >= 0:
            hits += 1
    return hits / len(events)


def ro_episodes(ro_signal: pd.Series) -> list[tuple[date, date]]:
    """Maximal contiguous runs of True in ro_signal."""
    out: list[tuple[date, date]] = []
    in_run = False
    run_start: date | None = None
    last_date: date | None = None
    for d, v in ro_signal.items():
        d_real = d.date() if hasattr(d, "date") else d
        if v and not in_run:
            run_start = d_real
            in_run = True
        elif not v and in_run:
            assert run_start is not None and last_date is not None
            out.append((run_start, last_date))
            in_run = False
        last_date = d_real
    if in_run and run_start is not None and last_date is not None:
        out.append((run_start, last_date))
    return out


def alarm_day_ratio(ro_signal: pd.Series) -> float:
    if len(ro_signal) == 0:
        return float("nan")
    return float(ro_signal.sum()) / float(len(ro_signal))


def _event_interval_overlaps(
    event: DrawdownEvent, window_start: date, window_end: date
) -> bool:
    """An event's [peak, trough] interval overlaps [window_start, window_end]
    iff event.peak_date <= window_end AND event.trough_date >= window_start.

    Critical correctness rule (third-pass review): an RO that fires AFTER the
    event peak but BEFORE the event trough is a VALID warning of an in-progress
    drawdown. Reducing events to a single date (peak OR trough) and asking
    "is that date forward of the RO" would discard those warnings as false
    positives. Using the interval keeps mid-drawdown RO as a hit, not an FP.
    """
    return event.peak_date <= window_end and event.trough_date >= window_start


def fp_day_rate(
    ro_signal: pd.Series,
    *,
    events: list[DrawdownEvent],
    trading_days: Sequence[date],
    horizon_days: int,
) -> float:
    """Day-level FP: an RO day ``d`` is FP iff no event's interval
    ``[peak, trough]`` overlaps ``[d, d + horizon_days bdays]``.
    """
    on = ro_signal[ro_signal]
    if on.empty:
        return float("nan")
    tds = list(trading_days)
    fp = 0
    for d in on.index:
        d_real = d.date() if hasattr(d, "date") else d
        i = bisect.bisect_left(tds, d_real)
        horizon_end = (
            tds[min(i + horizon_days, len(tds) - 1)] if i < len(tds) else d_real
        )
        has_event = any(
            _event_interval_overlaps(e, d_real, horizon_end) for e in events
        )
        if not has_event:
            fp += 1
    return fp / len(on)


def fp_episode_rate(
    ro_signal: pd.Series,
    *,
    events: list[DrawdownEvent],
    trading_days: Sequence[date],
    horizon_days: int,
) -> float:
    """Episode-level FP (gate metric, spec §9): an RO episode is FP iff no
    event's interval ``[peak, trough]`` overlaps ``[episode_start,
    episode_start + horizon_days bdays]``.
    """
    eps = ro_episodes(ro_signal)
    if not eps:
        return float("nan")
    tds = list(trading_days)
    fp = 0
    for start, _end in eps:
        i = bisect.bisect_left(tds, start)
        horizon_end_idx = min(i + horizon_days, len(tds) - 1)
        horizon_end = tds[horizon_end_idx] if tds else start
        has_event = any(_event_interval_overlaps(e, start, horizon_end) for e in events)
        if not has_event:
            fp += 1
    return fp / len(eps)


def utility_score(
    *,
    median_lead: float,
    hit_rate_val: float,
    fp_episode_rate_val: float,
    k_fp: float = 5.0,
) -> float:
    """utility = median_lead * hit_rate - k_fp * fp_episode_rate.

    NaN-propagating: returns NaN if any input is NaN.
    """
    if any(math.isnan(x) for x in (median_lead, hit_rate_val, fp_episode_rate_val)):
        return float("nan")
    return median_lead * hit_rate_val - k_fp * fp_episode_rate_val
