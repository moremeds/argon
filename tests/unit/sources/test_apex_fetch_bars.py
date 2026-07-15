from __future__ import annotations

from datetime import date

import httpx

from uw_scan.sources.apex import fetch_bars

# Frozen REAL AAPL 30m bars, as-of 2026-07-10 (phaseb_apex_bars_contract.md §3).
_AAPL_30M_PAYLOAD = {
    "symbol": "AAPL",
    "timeframe": "30m",
    "bars": [
        {
            "time": "2021-06-11T08:00:00+00:00",
            "open": 126.33,
            "high": 126.59,
            "low": 126.33,
            "close": 126.4,
            "volume": 10996,
            "vwap": None,
        },
        {
            "time": "2021-06-11T08:30:00+00:00",
            "open": 126.34,
            "high": 126.59,
            "low": 126.34,
            "close": 126.56,
            "volume": 2430,
            "vwap": None,
        },
        {
            "time": "2021-06-11T09:00:00+00:00",
            "open": 126.54,
            "high": 126.58,
            "low": 126.43,
            "close": 126.44,
            "volume": 4754,
            "vwap": None,
        },
    ],
    "count": 3,
    "generated_at": "2026-07-14T13:54:26+00:00",
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_bars_parses_real_payload_and_passes_explicit_start():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_AAPL_30M_PAYLOAD)

    bars = fetch_bars("aapl", "30m", date(2021, 6, 11), client=_client(handler))
    assert len(bars) == 3  # non-vacuity
    assert bars[0]["close"] == 126.4
    assert bars[0]["time"] == "2021-06-11T08:00:00+00:00"
    # The client MUST send an explicit start (default-window gotcha).
    assert seen["params"]["start"] == "2021-06-11"
    assert seen["params"]["timeframe"] == "30m"


def test_fetch_bars_unknown_ticker_empty_is_no_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "symbol": "ZZZ",
                "timeframe": "30m",
                "bars": [],
                "count": 0,
                "generated_at": "x",
            },
        )

    assert fetch_bars("ZZZ", "30m", date(2021, 6, 11), client=_client(handler)) == []


def test_fetch_bars_400_unsupported_timeframe_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "detail": "unsupported timeframe: 2h (have ['1d', '1h', '1m', '30m', '5m'])"
            },
        )

    assert fetch_bars("AAPL", "2h", date(2021, 6, 11), client=_client(handler)) == []
