"""fetch_daily_bars — apex daily bar fetch and its status contract (httpx
monkeypatched): [] only for a 2xx with no bars, SourceUnavailable when apex
cannot answer, and a programming error propagates."""

from __future__ import annotations

import httpx
import pytest

from uw_scan.sources import apex
from uw_scan.sources.source_errors import SourceUnavailable

URL = "http://apex"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def test_fetch_daily_bars_happy_path(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None, trust_env=True):
        captured["url"] = url
        captured["params"] = params
        return _Resp(
            {
                "symbol": "SPY",
                "bars": [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}],
            }
        )

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    bars = apex.fetch_daily_bars("spy", base_url=URL)
    assert bars == [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}]
    assert captured["url"].endswith("/v1/equity/SPY/bars")
    assert captured["params"] == {
        "timeframe": "1d",
        "limit": 1650,
        "price_mode": "adjusted",
    }


def test_fetch_daily_bars_transport_error_raises_source_unavailable(monkeypatch):
    def fake_get(url, params=None, timeout=None, trust_env=True):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    with pytest.raises(SourceUnavailable) as info:
        apex.fetch_daily_bars("SPY", base_url=URL)
    assert info.value.source == "apex"


@pytest.mark.parametrize("payload", [{"bars": "not-a-list"}, ["not", "a", "dict"]])
def test_fetch_daily_bars_malformed_payload_raises(monkeypatch, payload):
    monkeypatch.setattr(apex.httpx, "get", lambda *a, **k: _Resp(payload))
    with pytest.raises(SourceUnavailable):
        apex.fetch_daily_bars("SPY", base_url=URL)


def test_fetch_daily_bars_empty_2xx_is_no_data(monkeypatch):
    monkeypatch.setattr(apex.httpx, "get", lambda *a, **k: _Resp({"bars": []}))
    assert apex.fetch_daily_bars("SPY", base_url=URL) == []


def test_fetch_daily_bars_programming_error_propagates(monkeypatch):
    """I-17: a TypeError is a bug, not an outage -- it must not be swallowed."""

    def fake_get(url, params=None, timeout=None, trust_env=True):
        raise TypeError("bad call")

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    with pytest.raises(TypeError, match="bad call"):
        apex.fetch_daily_bars("SPY", base_url=URL)


def test_fetch_daily_bars_uses_v1_equity_route_and_requests_adjusted(monkeypatch):
    """The flat /bars route is deprecated (Sunset 2026-12-31) AND hardcoded to
    asset_class=equity. Adjusted must be REQUESTED, not inherited from apex's
    server-side effective_price_mode — otherwise a server config flip silently
    changes argon's price basis mid-series."""
    captured = {}

    def fake_get(url, params=None, timeout=None, trust_env=True):
        captured["url"] = url
        captured["params"] = params
        return _Resp({"symbol": "SPY", "bars": []})

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("spy", base_url=URL)
    assert captured["url"].endswith("/v1/equity/SPY/bars")
    assert captured["params"]["price_mode"] == "adjusted"


def test_fetch_daily_bars_volatility_class_omits_price_mode(monkeypatch):
    """SPX/VIX live under asset_class=volatility, which has no Silver tree —
    sending price_mode=adjusted there is a 400 adjusted_not_supported."""
    captured = {}

    def fake_get(url, params=None, timeout=None, trust_env=True):
        captured["url"] = url
        captured["params"] = params
        return _Resp({"symbol": "SPX", "bars": []})

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("SPX", base_url=URL, asset_class="volatility")
    assert captured["url"].endswith("/v1/volatility/SPX/bars")
    assert "price_mode" not in captured["params"]


def test_fetch_daily_bars_carries_apex_error_code(monkeypatch):
    """A 503 adjusted_unavailable and a 404 unknown_symbol both raise; the typed
    code is what tells them apart, so it must reach the exception detail."""

    def fake_get(url, params=None, timeout=None, trust_env=True):
        request = httpx.Request("GET", url)
        response = httpx.Response(
            503,
            json={
                "error": {
                    "code": "adjusted_unavailable",
                    "message": "Silver daily artifact is missing for MSTR",
                    "symbol": "MSTR",
                }
            },
            request=request,
        )
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    with pytest.raises(SourceUnavailable, match="adjusted_unavailable"):
        apex.fetch_daily_bars("MSTR", base_url=URL)
