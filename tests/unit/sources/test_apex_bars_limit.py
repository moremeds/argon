import httpx

from uw_scan.sources import apex


def test_fetch_daily_bars_requests_deep_history(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["params"] = params
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"bars": []}, request=req)

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("NVDA")
    assert int(seen["params"]["limit"]) >= 1300
