from __future__ import annotations

import httpx
import pytest

from uw_scan.api.client import LiveDataUnavailable, UwClient, UwHTTPError
from uw_scan.api.endpoints import EndpointSlug


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def record(self, event):
        if self.fail:
            raise RuntimeError("recorder failed")
        self.events.append(event)


def _client(transport: httpx.MockTransport, recorder: Recorder) -> UwClient:
    client = UwClient(
        api_key="uw-test",
        base_url="https://uw.test",
        max_retries=0,
        telemetry_recorder=recorder,
        job_name="unit",
    )
    client._client = httpx.Client(transport=transport)
    return client


def test_uw_client_records_success_with_headers_and_context():
    recorder = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True},
            headers={
                "x-uw-daily-req-count": "12",
                "x-uw-token-req-limit": "1000",
                "x-uw-req-per-minute-remaining": "99",
                "x-uw-req-per-minute-reset": "17",
            },
        )

    with _client(httpx.MockTransport(handler), recorder) as client:
        client.get(EndpointSlug.IV_RANK, ticker="TSLA", run_id=123)

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.provider == "uw"
    assert event.endpoint_key == "iv_rank"
    assert event.path_template == "/api/stock/{ticker}/iv-rank"
    assert event.path == "/api/stock/TSLA/iv-rank"
    assert event.ticker == "TSLA"
    assert event.status_code == 200
    assert event.status_family == "2xx"
    assert event.run_id == 123
    assert event.job_name == "unit"
    assert event.official_daily_count == 12
    assert event.official_daily_limit == 1000
    assert event.official_minute_remaining == 99
    assert event.official_minute_reset == "17"
    assert event.latency_ms >= 0


def test_uw_client_records_4xx_before_raising():
    recorder = Recorder()

    with _client(
        httpx.MockTransport(lambda _request: httpx.Response(404, text="missing")),
        recorder,
    ) as client:
        with pytest.raises(UwHTTPError):
            client.get(EndpointSlug.IV_RANK, ticker="TSLA")

    assert len(recorder.events) == 1
    assert recorder.events[0].status_code == 404
    assert recorder.events[0].status_family == "4xx"


def test_uw_client_records_every_5xx_retry_attempt(monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="try later")

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    client = UwClient(
        api_key="uw-test",
        base_url="https://uw.test",
        max_retries=2,
        telemetry_recorder=recorder,
    )
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    with client:
        with pytest.raises(UwHTTPError):
            client.get(EndpointSlug.IV_RANK, ticker="TSLA")

    assert calls == 3
    assert [event.attempt for event in recorder.events] == [0, 1, 2]
    assert [event.status_family for event in recorder.events] == ["5xx", "5xx", "5xx"]


def test_uw_client_records_transport_errors(monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    with _client(httpx.MockTransport(handler), recorder) as client:
        with pytest.raises(LiveDataUnavailable):
            client.get(EndpointSlug.IV_RANK, ticker="TSLA")

    assert len(recorder.events) == 1
    assert recorder.events[0].status_code is None
    assert recorder.events[0].status_family == "transport_error"
    assert "offline" in (recorder.events[0].error_message or "")


def test_uw_client_ignores_recorder_failures():
    recorder = Recorder(fail=True)

    with _client(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True})),
        recorder,
    ) as client:
        response, _headers = client.get(EndpointSlug.IV_RANK, ticker="TSLA")

    assert response.status_code == 200
