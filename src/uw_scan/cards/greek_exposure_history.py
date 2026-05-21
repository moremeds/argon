"""Pure parser for UW /greek-exposure (history aggregate) payload.

Used by:
- ``scanners/gex.py``   — to compute net_dex from the daily tail.
- ``scanners/gex.py``   — to feed ``greek_exposure_daily`` for the regime
                          history chart (via GreekExposureDailyRepository).

No DB, no network. Pure dict → list[dict] transformation.

Note: UW returns ``call_gamma / put_gamma / call_delta / put_delta`` per
day (aggregated across all strikes; ``call_gamma`` is the call-side dollar
gamma exposure summed across strikes, same units as our ``call_gex``
column). It does NOT return historical gex_flip or historical price —
those have to come from other sources (our own ``gex_snapshots`` for
flip, ``daily_ohlc`` / ``vol_index_daily`` for spot).
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
            # UW history payload uses ``call_gamma`` / ``put_gamma`` keys
            # (dollar gamma exposure summed across strikes). Older
            # snapshots may use ``call_gex`` / ``put_gex``; coalesce both
            # so cached payloads round-trip. ``dict.get(key, default)``
            # returns the explicit ``None`` if the key exists with value
            # ``None`` — that short-circuits past the fallback key — so
            # we coalesce manually instead.
            call_gex = float(_coalesce(r, "call_gamma", "call_gex") or 0)
            put_gex = float(_coalesce(r, "put_gamma", "put_gex") or 0)
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


def _coalesce(row: dict, primary: str, fallback: str) -> Any:
    """Return the first non-None value across the two keys.

    Unlike ``row.get(primary, row.get(fallback, 0))`` which returns the
    explicit ``None`` when ``primary`` is present-but-null (and therefore
    never consults ``fallback``), this picks the fallback whenever
    ``primary`` is missing OR null.
    """
    v = row.get(primary)
    if v is None:
        v = row.get(fallback)
    return v


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
