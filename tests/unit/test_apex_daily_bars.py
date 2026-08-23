"""fetch_daily_bars — never-raise apex daily bar fetch (httpx monkeypatched)."""

from __future__ import annotations

import httpx

from uw_scan.sources import apex


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

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(
            {
                "symbol": "SPY",
                "bars": [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}],
            }
        )

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    bars = apex.fetch_daily_bars("spy")
    assert bars == [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}]
    assert captured["url"].endswith("/v1/equity/SPY/bars")
    assert captured["params"] == {
        "timeframe": "1d",
        "limit": 1650,
        "price_mode": "adjusted",
    }


def test_fetch_daily_bars_never_raises(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    assert apex.fetch_daily_bars("SPY") == []


def test_fetch_daily_bars_malformed_payload(monkeypatch):
    monkeypatch.setattr(
        apex.httpx, "get", lambda *a, **k: _Resp({"bars": "not-a-list"})
    )
    assert apex.fetch_daily_bars("SPY") == []


def test_fetch_daily_bars_uses_v1_equity_route_and_requests_adjusted(monkeypatch):
    """The flat /bars route is deprecated (Sunset 2026-12-31) AND hardcoded to
    asset_class=equity. Adjusted must be REQUESTED, not inherited from apex's
    server-side effective_price_mode — otherwise a server config flip silently
    changes argon's price basis mid-series."""
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp({"symbol": "SPY", "bars": []})

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("spy")
    assert captured["url"].endswith("/v1/equity/SPY/bars")
    assert captured["params"]["price_mode"] == "adjusted"


def test_fetch_daily_bars_volatility_class_omits_price_mode(monkeypatch):
    """SPX/VIX live under asset_class=volatility, which has no Silver tree —
    sending price_mode=adjusted there is a 400 adjusted_not_supported."""
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp({"symbol": "SPX", "bars": []})

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("SPX", asset_class="volatility")
    assert captured["url"].endswith("/v1/volatility/SPX/bars")
    assert "price_mode" not in captured["params"]


def test_fetch_daily_bars_logs_apex_error_code(monkeypatch, caplog):
    """A 503 adjusted_unavailable and a 404 unknown_symbol both collapse to []
    at this boundary; the typed code is the only thing that tells them apart,
    so it must reach the log."""

    def fake_get(url, params=None, timeout=None):
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
    with caplog.at_level("WARNING"):
        assert apex.fetch_daily_bars("MSTR") == []
    assert "adjusted_unavailable" in caplog.text
