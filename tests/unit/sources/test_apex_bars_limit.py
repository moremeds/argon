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
    # Must fetch the 1300-session display window PLUS the longest warmup
    # (z_vs_200dma needs ~324 bars) so every series is warm across the window.
    assert int(seen["params"]["limit"]) >= 1300 + 324
