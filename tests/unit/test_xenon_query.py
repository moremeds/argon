from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from uw_scan.sources.source_errors import SourceUnavailable
from uw_scan.sources.xenon_query import fetch_ib_option_iv, fetch_ib_option_quote


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


def test_http_error_raises_source_unavailable():
    def handler(request):
        return httpx.Response(502, json={"detail": "could not qualify"})

    with pytest.raises(SourceUnavailable, match="502"):
        fetch_ib_option_iv(
            base_url="http://x:8421",
            api_key=None,
            symbol="ZZZ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )


def test_non_dict_body_raises_source_unavailable():
    def handler(request):
        return httpx.Response(200, json=[{"greeks": {"impliedVol": 0.4}}])

    with pytest.raises(SourceUnavailable, match="body is list"):
        fetch_ib_option_iv(
            base_url="http://x:8421",
            api_key=None,
            symbol="QQQ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )


def test_sends_api_key_header_when_present():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"greeks": {"impliedVol": 0.3}})

    fetch_ib_option_iv(
        base_url="http://x:8421",
        api_key="secret",
        symbol="QQQ",
        expiry="20260717",
        strike=600.0,
        right="C",
        client=_client(handler),
    )
    assert seen["key"] == "secret"


def test_missing_api_key_401_raises_rather_than_reading_as_no_greeks():
    """A 401 (key missing/wrong) used to collapse to None -- indistinguishable
    from "IB computed no greeks" -- so every leg silently fell back to UW."""

    def handler(request):
        return httpx.Response(401, json={"detail": "invalid api key"})

    with pytest.raises(SourceUnavailable, match="401"):
        fetch_ib_option_quote(
            base_url="http://x:8321",
            api_key=None,
            symbol="SPX",
            expiry="20260807",
            strike=5800.0,
            right="P",
            client=_client(handler),
        )


def test_quote_null_greeks_on_200_is_data_not_an_outage():
    def handler(request):
        return httpx.Response(200, json={"bid": 1.0, "ask": 1.2, "greeks": None})

    q = fetch_ib_option_quote(
        base_url="http://x:8321",
        api_key="k",
        symbol="SPX",
        expiry="20260807",
        strike=5800.0,
        right="P",
        client=_client(handler),
    )
    assert q["bid"] == 1.0 and q["iv"] is None and q["delta"] is None


def test_non_numeric_implied_vol_raises_source_unavailable():
    def handler(request):
        return httpx.Response(200, json={"greeks": {"impliedVol": "n/a"}})

    with pytest.raises(SourceUnavailable, match="not numeric"):
        fetch_ib_option_iv(
            base_url="http://x:8321",
            api_key="k",
            symbol="QQQ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )


def test_programming_error_propagates():
    """I-17: only transport/HTTP/decode/shape failures are caught."""

    def handler(request):
        raise TypeError("bad handler")

    with pytest.raises(TypeError, match="bad handler"):
        fetch_ib_option_iv(
            base_url="http://x:8321",
            api_key="k",
            symbol="QQQ",
            expiry="20260717",
            strike=600.0,
            right="C",
            client=_client(handler),
        )
