"""Pure parser for UW /greek-exposure (history aggregate) payload.

Used by:
- ``scanners/gex.py``   — to compute net_dex from the daily tail.
- ``scanners/gex.py``   — to feed ``greek_exposure_daily`` for the regime
                          history chart (via GreekExposureDailyRepository).

No DB, no network. Pure dict → list[dict] transformation.

Note: UW returns ``call_gex / put_gex / call_delta / put_delta`` per day
(aggregated across all strikes). It does NOT return historical gex_flip
or historical price — those have to come from other sources (our own
``gex_snapshots`` for flip, ``daily_ohlc`` / ``vol_index_daily`` for spot).
"""

from __future__ import annotations

from datetime import date
from typing import Any


def parse_greek_exposure_history(body: dict | None) -> list[dict]:
    """Body envelope → list of typed daily rows.

    Each output row carries:
        date, call_gex, put_gex, call_delta, put_delta,
        net_gex (call_gex + put_gex), net_dex (call_delta + put_delta).

    Malformed individual rows are dropped (logged downstream by caller),
    not raised — partial data is more useful than nothing for a history chart.
    """
    if not body or not isinstance(body, dict):
        return []
    raw = body.get("data") or []
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for r in raw:
        try:
            d = _coerce_date(r.get("date"))
            if d is None:
                continue
            call_gex = float(r.get("call_gex", 0) or 0)
            put_gex = float(r.get("put_gex", 0) or 0)
            call_delta = float(r.get("call_delta", 0) or 0)
            put_delta = float(r.get("put_delta", 0) or 0)
        except (TypeError, ValueError) as exc:
            _ = repr(exc)  # CI Guardrail 2: malformed row skipped
            continue
        out.append(
            {
                "date": d,
                "call_gex": call_gex,
                "put_gex": put_gex,
                "call_delta": call_delta,
                "put_delta": put_delta,
                "net_gex": call_gex + put_gex,
                "net_dex": call_delta + put_delta,
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def _coerce_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError as exc:
            _ = repr(exc)  # CI Guardrail 2: bad ISO string → None
            return None
    return None
