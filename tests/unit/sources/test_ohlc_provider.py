"""MassiveOhlcProvider fixture tests using httpx.MockTransport."""

from __future__ import annotations

from datetime import date, timezone
from decimal import Decimal

import httpx

from uw_scan.sources.ohlc import MassiveOhlcProvider


def _provider_with(handler) -> MassiveOhlcProvider:
    p = MassiveOhlcProvider(api_key="test", base_url="https://api.massive.com")
    p._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
        base_url="https://api.massive.com",
    )
    return p


def test_fetch_daily_returns_bars():
    def handler(req):
        assert req.url.path == "/v2/aggs/ticker/AAPL/range/1/day/2026-04-01/2026-05-01"
        return httpx.Response(
            200,
            json={
                "ticker": "AAPL",
                "results": [
                    {
                        "t": 1746057600000,
                        "o": 100.0,
                        "h": 102.0,
                        "l": 99.5,
                        "c": 101.25,
                        "v": 12345678,
                    },
                    {
                        "t": 1746144000000,
                        "o": 101.5,
                        "h": 103.0,
                        "l": 101.0,
                        "c": 102.50,
                        "v": 9876543,
                    },
                ],
            },
        )

    p = _provider_with(handler)
    bars = p.fetch_daily("AAPL", date(2026, 4, 1), date(2026, 5, 1))
    assert len(bars) == 2
    assert bars[0].close == Decimal("101.25")
    assert bars[1].volume == 9876543


def test_fetch_daily_empty():
    p = _provider_with(lambda req: httpx.Response(200, json={"results": []}))
    bars = p.fetch_daily("ZZZZ", date(2026, 4, 1), date(2026, 5, 1))
    assert bars == []


def test_fetch_intraday_quote_uses_latest_minute_bar():
    """Quotes endpoint is gated on our tier; use the most-recent minute
    aggregate close as a 15-min-delayed intraday price."""

    def handler(req):
        assert "/v2/aggs/ticker/TSLA/range/1/minute/" in req.url.path
        assert req.url.params.get("sort") == "desc"
        assert req.url.params.get("limit") == "1"
        return httpx.Response(
            200,
            json={
                "ticker": "TSLA",
                "status": "DELAYED",
                "results": [
                    {
                        "v": 16472,
                        "vw": 444.99,
                        "o": 444.50,
                        "c": 445.12,
                        "h": 445.50,
                        "l": 444.20,
                        "t": 1746210000000,
                        "n": 575,
                    }
                ],
            },
        )

    p = _provider_with(handler)
    q = p.fetch_intraday_quote("TSLA")
    assert q is not None
    assert q.price == Decimal("445.12")
    assert q.quoted_at.tzinfo is timezone.utc


def test_fetch_intraday_quote_empty_results():
    p = _provider_with(lambda req: httpx.Response(200, json={"results": []}))
    assert p.fetch_intraday_quote("ZZZZ") is None


def test_fetch_intraday_quote_404():
    p = _provider_with(lambda req: httpx.Response(404, json={}))
    assert p.fetch_intraday_quote("UNKNOWN") is None
