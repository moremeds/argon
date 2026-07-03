from __future__ import annotations

from datetime import date

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources import uw


def test_fetch_oi_change_passes_historical_date(monkeypatch):
    calls: list[dict] = []

    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kwargs):
        calls.append(
            {
                "slug": slug,
                "ticker": ticker,
                "params": params,
            }
        )
        return {"data": []}

    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(uw.normalize, "normalize_oi_change", lambda body: [])

    rows = uw.fetch_oi_change(
        client=object(),
        repo=object(),
        run_id=123,
        ticker="AAPL",
        market_date=date(2025, 7, 3),
    )

    assert rows == []
    assert calls == [
        {
            "slug": EndpointSlug.OI_CHANGE,
            "ticker": "AAPL",
            "params": {"date": "2025-07-03"},
        }
    ]

