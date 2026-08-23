from __future__ import annotations

from datetime import date, datetime

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
    # The client MUST send an explicit start (default-window gotcha), and it
    # MUST carry a UTC offset — see test_start_is_offset_aware_iso below.
    assert seen["params"]["start"] == "2021-06-11T00:00:00+00:00"
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


def test_fetch_bars_connect_error_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    assert fetch_bars("AAPL", "30m", date(2021, 6, 11), client=_client(handler)) == []


def test_fetch_bars_malformed_body_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json="nonsense")

    assert fetch_bars("AAPL", "30m", date(2021, 6, 11), client=_client(handler)) == []


def test_fetch_bars_uses_v1_route_and_defaults_to_equity_adjusted():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_AAPL_30M_PAYLOAD)

    fetch_bars("aapl", "30m", date(2021, 6, 11), client=_client(handler))
    assert seen["path"] == "/v1/equity/AAPL/bars"
    assert seen["params"]["price_mode"] == "adjusted"


def test_fetch_bars_volatility_class_reaches_spx_without_price_mode():
    """The flat route is equity-only — GET /bars/SPX is a 404 unknown_symbol.
    Only /v1/volatility/SPX/bars serves the vol complex."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "symbol": "SPX",
                "asset_class": "volatility",
                "timeframe": "1d",
                "price_mode": "raw",
                "bars": [
                    {
                        "time": "2026-08-21T00:00:00+00:00",
                        "open": 7665.68,
                        "high": 7697.11,
                        "low": 7660.06,
                        "close": 7674.37,
                        "volume": 0,
                    }
                ],
                "count": 1,
                "generated_at": "2026-08-23T08:16:02+00:00",
            },
        )

    bars = fetch_bars(
        "spx", "1d", date(2026, 8, 21), asset_class="volatility", client=_client(handler)
    )
    assert seen["path"] == "/v1/volatility/SPX/bars"
    assert "price_mode" not in seen["params"]
    assert bars[0]["close"] == 7674.37


def test_fetch_bars_503_adjusted_unavailable_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": "adjusted_unavailable",
                    "message": "Silver daily artifact is missing for CCJ",
                    "symbol": "CCJ",
                }
            },
        )

    assert fetch_bars("CCJ", "1d", date(2026, 8, 21), client=_client(handler)) == []


def test_start_is_offset_aware_iso_datetime():
    """apex /v1 returns 500 internal_error for a bare YYYY-MM-DD start AND for
    a naive ISO datetime — only an explicit UTC offset parses (measured against
    apex 0.1.4 on 2026-08-23, equity and volatility alike). The flat alias used
    to accept the bare date, so this is a real contract change, not cosmetics.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_AAPL_30M_PAYLOAD)

    fetch_bars(
        "AAPL",
        "1d",
        date(2021, 6, 11),
        end=date(2021, 6, 30),
        client=_client(handler),
    )
    for key in ("start", "end"):
        assert seen["params"][key].endswith("+00:00"), (
            f"{key}={seen['params'][key]!r} has no UTC offset — apex /v1 500s on it"
        )


def test_naive_datetime_start_gains_utc_offset():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_AAPL_30M_PAYLOAD)

    fetch_bars(
        "AAPL", "30m", datetime(2021, 6, 11, 13, 30), client=_client(handler)
    )
    assert seen["params"]["start"] == "2021-06-11T13:30:00+00:00"
