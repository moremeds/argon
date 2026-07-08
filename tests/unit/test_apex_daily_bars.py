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
    assert captured["url"].endswith("/bars/SPY")
    assert captured["params"] == {"timeframe": "1d"}


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
