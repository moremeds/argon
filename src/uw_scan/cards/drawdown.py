"""Non-overlapping drawdown event detector.

Per-definition: events emitted under one DrawdownDefinition must be
non-overlapping. Different definitions (Fast/Medium/Major) are detected
INDEPENDENTLY against the same close series — their event sets may overlap
across definitions. The comparator reports each definition separately.

Used by the research path's comparator (scripts/compare_vcg_lead_time.py)
to label benchmark drawdowns against which VCG lead time is measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class DrawdownDefinition:
    name: str  # "Fast", "Medium", "Major"
    threshold: float  # e.g. 0.05 = 5%
    window_days: int  # peak->trough must fit within this many trading days


@dataclass(frozen=True)
class DrawdownEvent:
    peak_date: date
    trough_date: date
    peak_price: float
    trough_price: float
    recovery_date: date | None  # None if recovery doesn't happen in series
    depth_pct: float
    definition: str


def detect_drawdown_events(
    closes: pd.Series,
    definition: DrawdownDefinition,
) -> list[DrawdownEvent]:
    """Walk closes left-to-right, emitting non-overlapping events for one
    drawdown definition. After each event, the next search starts at the
    later of trough_date+1 and recovery_date+1.

    Critical correctness rule: if the detector reaches the end of the series
    inside a drawdown without seeing recovery (continuous selloff — 2008-Q4,
    2022 bear), it must STOP. Otherwise a progressively-lower trough would
    spawn duplicate events and inflate hit-rate / lead-time denominators.
    """
    if closes.empty:
        return []
    if not closes.index.is_monotonic_increasing:
        raise ValueError("closes must have a monotonically increasing index")

    values = closes.values
    dates = list(closes.index.date)
    n = len(values)
    events: list[DrawdownEvent] = []

    i = 0
    while i < n:
        end_window = min(i + definition.window_days + 1, n)
        peak_idx = i
        peak_price = values[i]
        emitted = False
        for j in range(i, end_window):
            if values[j] > peak_price:
                peak_idx = j
                peak_price = values[j]
                continue
            depth = (peak_price - values[j]) / peak_price
            if depth >= definition.threshold:
                # Extend into the same dip: find the local trough
                trough_idx = j
                trough_price = values[j]
                for k in range(j + 1, min(peak_idx + definition.window_days + 1, n)):
                    if values[k] < trough_price:
                        trough_idx = k
                        trough_price = values[k]
                    elif values[k] >= peak_price:
                        break  # recovered
                # Recovery: first index after trough where close >= peak_price
                recovery_idx: int | None = None
                for r in range(trough_idx + 1, n):
                    if values[r] >= peak_price:
                        recovery_idx = r
                        break
                final_depth = (peak_price - trough_price) / peak_price
                events.append(
                    DrawdownEvent(
                        peak_date=dates[peak_idx],
                        trough_date=dates[trough_idx],
                        peak_price=float(peak_price),
                        trough_price=float(trough_price),
                        recovery_date=(
                            dates[recovery_idx] if recovery_idx is not None else None
                        ),
                        depth_pct=float(final_depth),
                        definition=definition.name,
                    )
                )
                # CRITICAL: if no recovery occurs within the series, STOP
                # searching for further events in this period. A continuous
                # selloff (e.g. 2008-Q4, 2022 bear) without prior-peak
                # recovery would otherwise spawn duplicate events from
                # progressively lower troughs — corrupting hit rate and
                # lead-time medians.
                if recovery_idx is None:
                    i = n  # exit the outer while-loop
                else:
                    i = max(recovery_idx + 1, peak_idx + 1)
                emitted = True
                break
        if not emitted:
            i += 1

    return events
