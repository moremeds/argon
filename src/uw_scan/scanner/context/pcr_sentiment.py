"""PCR Sentiment context flag - count-based PCR from this run's FlowAlerts.

NOTE: Does NOT use cards/pcr.py - that file computes 30-day deltas on
OI/volume PCR history, a different metric. Per xenon parity (analysis/
ticker_data.py:424-432), this counts call vs put alerts in the current
flow snapshot. Suppressed when ANY alert reports earnings within the
window (PCR is noisy around earnings); unknown earnings does NOT
suppress (flag is informational per spec §3.5).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.models import ContextFlag


def flag(
    *,
    ticker: str,
    alerts: Iterable[FlowAlert],
    today: date,
    earnings_window_days: int,
) -> ContextFlag | None:
    alerts_list = list(alerts)

    # Suppress when any alert has earnings within the window. Unknown
    # earnings does NOT suppress - spec §3.5.
    for a in alerts_list:
        if (
            a.next_earnings_date is not None
            and (a.next_earnings_date - today).days <= earnings_window_days
        ):
            return None

    calls = sum(1 for a in alerts_list if (a.type or "").lower() == "call")
    puts = sum(1 for a in alerts_list if (a.type or "").lower() == "put")
    if calls == 0:
        return None

    pcr = Decimal(puts) / Decimal(calls)
    if pcr > Decimal("1.5"):
        label = "Extreme Fear"
    elif pcr > Decimal("1.2"):
        label = "Elevated Fear"
    elif pcr < Decimal("0.5"):
        label = "Complacent"
    else:
        return None

    return ContextFlag(
        ticker=ticker.upper(),
        layer="pcr_sentiment",
        label=label,
        value=pcr,
    )
