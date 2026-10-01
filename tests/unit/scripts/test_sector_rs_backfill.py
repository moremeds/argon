"""Resume/chunk helpers and the #157 pre-flight of scripts/backfill/sector_rs_backfill.py.

Loaded by file path because scripts/ is not a package (same as
test_chanlun_probe_smoke.py). The session dates are real NYSE sessions of
September 2026.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts/backfill/sector_rs_backfill.py"
_spec = importlib.util.spec_from_file_location("sector_rs_backfill", _PATH)
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf
_spec.loader.exec_module(bf)

SESSIONS = [date(2026, 9, d) for d in (14, 15, 16, 17, 18)]


def test_pending_skips_present_unless_forced():
    present = {date(2026, 9, 15), date(2026, 9, 17)}
    assert bf.pending_sessions(SESSIONS, present, force=False) == [
        date(2026, 9, 14),
        date(2026, 9, 16),
        date(2026, 9, 18),
    ]
    assert bf.pending_sessions(SESSIONS, present, force=True) == SESSIONS


def test_chunked_preserves_order_and_rejects_nonpositive():
    assert bf.chunked(SESSIONS, 2) == [SESSIONS[0:2], SESSIONS[2:4], SESSIONS[4:5]]
    assert bf.chunked([], 3) == []
    with pytest.raises(ValueError):
        bf.chunked(SESSIONS, 0)


# The bar below is the REAL XLK adjusted bar of 2026-09-10 (apex, revision 80).
# Only its presence matters to the pre-flight, not its date.
_XLK_BAR = {
    "time": "2026-09-10T00:00:00+00:00",
    "open": 185.02438884683545,
    "high": 186.3028989835443,
    "low": 184.35017451693037,
    "close": 185.00441212594936,
    "volume": 5571344,
}


def _client(bars_for):
    """bars_for: symbol -> bars; a symbol not in it gets [] (Silver has not published it)."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        sym = req.url.path.split("/")[3]
        bars = bars_for.get(sym, [])
        return httpx.Response(
            200, json={"symbol": sym, "bars": bars, "count": len(bars)}
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


_ALL_NINE = {s: [_XLK_BAR] for s in bf._FUNDS_1998}


def test_preflight_aborts_naming_the_funds_silver_has_not_published():
    published = dict(_ALL_NINE)
    for s in ("XLK", "XLY", "XLB", "XLU", "XLE"):  # the 2026-09-27 state
        del published[s]
    client, seen = _client(published)
    with pytest.raises(SystemExit, match="for XLB XLE XLK XLU XLY"):
        bf.preflight_etf_history(client=client)
    assert [r.url.path for r in seen] == [
        f"/v1/equity/{s}/bars" for s in bf._FUNDS_1998
    ]
    q = seen[0].url.params
    assert q["price_mode"] == "adjusted" and q["timeframe"] == "1d"
    assert q["start"] == "1999-01-04T00:00:00+00:00"
    assert q["end"] == "1999-01-08T23:59:59+00:00"


def test_preflight_passes_when_all_nine_have_bars():
    client, _ = _client(_ALL_NINE)
    assert bf.preflight_etf_history(client=client) is None
