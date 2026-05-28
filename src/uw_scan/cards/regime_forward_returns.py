"""Pure helpers for projecting realized forward SPX returns onto VCG
stress-history entries, and aggregating the result by interpretation.

No DB access. The handler at api/routers/regime_validation.py loads the
SPX series and the daily entries; this module enriches and summarizes.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable

log = logging.getLogger(__name__)

# Default horizons match the UI columns (+5d, +20d, +60d).
DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)


def attach_forward_returns(
    entries: list[dict[str, Any]],
    spx_series: list[tuple[date, float]],
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict[str, Any]]:
    """Return a new list of entry dicts, each with `fwd_{H}d_pct` keys.

    spx_series must be sorted ascending by trade_date. Each entry's date
    is matched against the series; the close N trading days later is
    looked up by index. Missing dates or tail-overhangs produce None.

    Returns a shallow-copied list of dicts so the input is not mutated.

    Raises ValueError if spx_series is not sorted ascending — defensive
    check against a future SQL refactor dropping the ORDER BY in
    VolIndexRepository.fetch_multi_history. Silent wrong fwd returns
    are worse than a loud crash.
    """
    for i in range(len(spx_series) - 1):
        if spx_series[i][0] > spx_series[i + 1][0]:
            raise ValueError(
                f"spx_series must be sorted ascending by date; "
                f"index {i} ({spx_series[i][0]}) > index {i + 1} ({spx_series[i + 1][0]})"
            )
    date_to_index = {d: i for i, (d, _) in enumerate(spx_series)}
    closes = [c for _, c in spx_series]
    horizons = tuple(horizons)

    out: list[dict[str, Any]] = []
    for entry in entries:
        enriched = dict(entry)  # shallow copy; do not mutate input
        entry_date = _parse_date(entry.get("date"))
        idx = date_to_index.get(entry_date) if entry_date else None
        for h in horizons:
            key = f"fwd_{h}d_pct"
            if idx is None:
                enriched[key] = None
                continue
            future_idx = idx + h
            if future_idx >= len(closes):
                enriched[key] = None
                continue
            base = closes[idx]
            future = closes[future_idx]
            if base is None or future is None or base == 0:
                enriched[key] = None
                continue
            enriched[key] = (future - base) / base * 100.0
        out.append(enriched)
    return out


def summarize_stress_returns(
    enriched_entries: list[dict[str, Any]],
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict[str, Any]]:
    """Group entries by `interpretation`; for each group return
    {interpretation, n, mean_fwd_{H}d_pct, winrate_{H}d_pct} for
    H in horizons.

    `n` is the total entry count (including those with None fwd values).
    `mean_*` and `winrate_*` skip None values; if every value for a
    horizon is None, the aggregate is None (not 0, not NaN).
    """
    horizons = tuple(horizons)
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in enriched_entries:
        interp = entry.get("interpretation")
        if not interp:
            continue
        groups.setdefault(interp, []).append(entry)

    out: list[dict[str, Any]] = []
    for interp in sorted(groups):
        rows = groups[interp]
        row: dict[str, Any] = {"interpretation": interp, "n": len(rows)}
        for h in horizons:
            key = f"fwd_{h}d_pct"
            values = [r[key] for r in rows if r.get(key) is not None]
            row[f"mean_{key}"] = sum(values) / len(values) if values else None
            if values:
                wins = sum(1 for v in values if v > 0)
                row[f"winrate_{h}d_pct"] = wins / len(values) * 100.0
            else:
                row[f"winrate_{h}d_pct"] = None
        out.append(row)
    return out


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            log.debug("date.fromisoformat failed: %s", repr(exc))
            return None
    return None
