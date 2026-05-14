"""MassiveOhlcProvider fixture tests using httpx.MockTransport."""

from __future__ import annotations

from datetime import date, timezone
from decimal import Decimal

import httpx
import pytest

from uw_scan.sources.ohlc import MassiveOhlcProvider


class Recorder:
    def __init__(self) -> None:
        self.events = []

    def record(self, event):
        self.events.append(event)


def _provider_with(handler, recorder: Recorder | None = None) -> MassiveOhlcProvider:
    p = MassiveOhlcProvider(
        api_key="test",
        base_url="https://api.massive.com",
        telemetry_recorder=recorder,
        job_name="unit",
    )
    p._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
        base_url="https://api.massive.com",
    )
    return p


def test_fetch_daily_returns_bars():
    recorder = Recorder()

    def handler(req):
        assert req.url.path == "/v2/aggs/ticker/AAPL/range/1/day/2026-04-01/2026-05-01"
        return httpx.Response(
            200,
            json={
                "ticker": "AAPL",
                "request_id": "req-daily",
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

    p = _provider_with(handler, recorder)
    bars = p.fetch_daily("AAPL", date(2026, 4, 1), date(2026, 5, 1))
    assert len(bars) == 2
    assert bars[0].close == Decimal("101.25")
    assert bars[1].volume == 9876543
    assert len(recorder.events) == 1
    assert recorder.events[0].provider == "massive"
    assert recorder.events[0].endpoint_key == "daily_ohlc"
    assert recorder.events[0].ticker == "AAPL"
    assert recorder.events[0].status_code == 200
    assert recorder.events[0].status_family == "2xx"
    assert recorder.events[0].provider_request_id == "req-daily"


def test_fetch_daily_empty():
    p = _provider_with(lambda req: httpx.Response(200, json={"results": []}))
    bars = p.fetch_daily("ZZZZ", date(2026, 4, 1), date(2026, 5, 1))
    assert bars == []


def test_fetch_intraday_quote_uses_latest_minute_bar():
    """Quotes endpoint is gated on our tier; use the most-recent minute
    aggregate close as a 15-min-delayed intraday price."""

    recorder = Recorder()

    def handler(req):
        assert "/v2/aggs/ticker/TSLA/range/1/minute/" in req.url.path
        assert req.url.params.get("sort") == "desc"
        assert req.url.params.get("limit") == "1"
        return httpx.Response(
            200,
            json={
                "ticker": "TSLA",
                "status": "DELAYED",
                "request_id": "req-quote",
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

    p = _provider_with(handler, recorder)
    q = p.fetch_intraday_quote("TSLA")
    assert q is not None
    assert q.price == Decimal("445.12")
    assert q.quoted_at.tzinfo is timezone.utc
    assert len(recorder.events) == 1
    assert recorder.events[0].endpoint_key == "intraday_quote"
    assert recorder.events[0].status_family == "2xx"
    assert recorder.events[0].provider_request_id == "req-quote"


def test_fetch_intraday_quote_uses_supplied_market_date():
    def handler(req):
        assert req.url.path == "/v2/aggs/ticker/TSLA/range/1/minute/2026-05-13/2026-05-14"
        return httpx.Response(200, json={"results": []})

    p = _provider_with(handler)
    assert p.fetch_intraday_quote("TSLA", market_date=date(2026, 5, 13)) is None


def test_fetch_intraday_quote_empty_results():
    p = _provider_with(lambda req: httpx.Response(200, json={"results": []}))
    assert p.fetch_intraday_quote("ZZZZ") is None


def test_fetch_intraday_quote_404():
    recorder = Recorder()
    p = _provider_with(lambda req: httpx.Response(404, json={}), recorder)
    assert p.fetch_intraday_quote("UNKNOWN") is None
    assert len(recorder.events) == 1
    assert recorder.events[0].status_code == 404
    assert recorder.events[0].status_family == "4xx"


def test_fetch_daily_records_raised_http_error():
    recorder = Recorder()
    p = _provider_with(lambda req: httpx.Response(500, text="down"), recorder)

    with pytest.raises(httpx.HTTPStatusError):
        p.fetch_daily("AAPL", date(2026, 4, 1), date(2026, 5, 1))

    assert len(recorder.events) == 1
    assert recorder.events[0].status_code == 500
    assert recorder.events[0].status_family == "5xx"
    assert "down" in (recorder.events[0].error_message or "")
