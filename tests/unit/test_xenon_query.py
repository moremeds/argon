from __future__ import annotations

from decimal import Decimal

import httpx
from uw_scan.sources.xenon_query import fetch_ib_option_iv


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_implied_vol_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/options/greeks"
        assert request.url.params["symbol"] == "QQQ"
        return httpx.Response(
            200, json={"greeks": {"impliedVol": 0.4071, "delta": 0.95}}
        )

    iv = fetch_ib_option_iv(
        base_url="http://x:8421",
        api_key=None,
        symbol="QQQ",
        expiry="20260717",
        strike=600.0,
        right="C",
        client=_client(handler),
    )
    assert iv == Decimal("0.4071")


def test_returns_none_when_greeks_null():
    def handler(request):
        return httpx.Response(200, json={"greeks": None, "note": "no greeks returned"})

    assert (
        fetch_ib_option_iv(
            base_url="http://x:8421",
            api_key=None,
            symbol="QQQ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )
        is None
    )


def test_returns_none_on_http_error():
    def handler(request):
        return httpx.Response(502, json={"detail": "could not qualify"})

    assert (
        fetch_ib_option_iv(
            base_url="http://x:8421",
            api_key=None,
            symbol="ZZZ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )
        is None
    )
