"""Regression: the analysis-input JSONB encoder must tolerate Decimal/date.

The M6 framework sections carry raw warm-store values (Decimal prices from
``list_daily_ohlc``, date snapshots from positioning/fundamentals). psycopg's
default JSONB encoder rejects ``Decimal`` — a live POST 500 ("Object of type
Decimal is not JSON serializable") that int-based unit fixtures never caught.
``_dumps_jsonb`` matches the ``default=str`` encoding the content-hash and
model-prompt consumers already use.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.storage.trade_insights_ai import _dumps_jsonb


def test_dumps_jsonb_handles_decimal_and_date() -> None:
    payload = {
        "tape": {
            "latest_close": Decimal("248.71"),
            "dma_50": Decimal("251.04"),
            "trend_3close": "up",
        },
        "positioning": {
            "snapshot_date": date(2026, 5, 20),
            "si_pct_float": Decimal("0.18"),
        },
        "generated_at": datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
        "rows": [{"close": Decimal("100.5"), "volume": 1_000_000}],
        "plain": "ok",
    }
    # Must not raise — this is exactly what Jsonb(..., dumps=_dumps_jsonb) calls.
    encoded = _dumps_jsonb(payload)
    restored = json.loads(encoded)
    # Decimals serialize as strings (matching default=str, the hash/prompt path).
    assert restored["tape"]["latest_close"] == "248.71"
    assert restored["positioning"]["snapshot_date"] == "2026-05-20"
    assert restored["rows"][0]["close"] == "100.5"
    assert restored["plain"] == "ok"


def test_dumps_jsonb_is_plain_json_for_native_types() -> None:
    payload = {"a": 1, "b": [1, 2, 3], "c": {"d": True, "e": None}}
    assert json.loads(_dumps_jsonb(payload)) == payload
