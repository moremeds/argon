"""GET-with-telemetry behavior shared by the simple provider clients.

Asserts observable behavior — the recorded ExternalApiRequestEvent fields, the
returned/raised outcome of ``_get_with_telemetry`` — through each provider's
patchable seam, not the helper layout behind it.
"""

from __future__ import annotations

import pytest
import httpx

from uw_scan.sources.cftc_cot import CftcCotProvider
from uw_scan.sources.cftc_tff import CftcTffProvider
from uw_scan.sources.comex import ComexProvider
from uw_scan.sources.gpr import GprProvider
from uw_scan.sources.lbma import LbmaProvider

# (provider class, URL used for the GET, provider, endpoint_key, endpoint_path)
PROVIDERS = [
    (
        CftcCotProvider,
        CftcCotProvider.URL,
        "cftc_cot",
        "cftc_cot_disagg_csv",
        "/dea/newcot/f_disagg.txt",
    ),
    (
        CftcTffProvider,
        CftcTffProvider.URL,
        "cftc_tff",
        "cftc_tff_futures_only",
        "/resource/gpe5-46if.json",
    ),
    (
        ComexProvider,
        ComexProvider.URL,
        "comex",
        "comex_gold_stocks_html",
        "/markets/metals/precious/gold-stocks.html",
    ),
    (
        GprProvider,
        GprProvider.DEFAULT_URL,
        "gpr",
        "gpr_daily_xls",
        "/gpr_files/data_gpr_daily_recent.xls",
    ),
    (
        LbmaProvider,
        LbmaProvider.URL,
        "lbma",
        "lbma_vault_xlsx",
        "/prices-and-data/london-vault-data",
    ),
]


def _mock_client(provider, handler) -> None:
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("cls", "url", "provider", "endpoint_key", "endpoint_path"), PROVIDERS
)
def test_get_success_records_event(cls, url, provider, endpoint_key, endpoint_path):
    events = []
    p = cls(record_request=lambda _p, e: events.append(e))
    _mock_client(p, lambda request: httpx.Response(200, text="ok"))

    response = p._get_with_telemetry(url, {"api_key": "secret", "keep": "v"})

    assert response.status_code == 200
    assert len(events) == 1
    event = events[0]
    assert event.provider == provider
    assert event.endpoint_key == endpoint_key
    assert event.method == "GET"
    assert event.path == endpoint_path
    assert event.path_template == endpoint_path
    assert event.status_code == 200
    assert event.status_family == "2xx"
    assert event.error_message is None
    assert event.params == {"keep": "v"}  # sensitive key redacted
    assert event.latency_ms >= 0
    assert event.finished_at >= event.started_at


@pytest.mark.parametrize(
    ("cls", "url", "provider", "endpoint_key", "endpoint_path"), PROVIDERS
)
def test_get_http_error_records_event_and_returns(
    cls, url, provider, endpoint_key, endpoint_path
):
    """An HTTP error status is recorded with a body excerpt, then returned.

    ``_get_with_telemetry`` does not raise for status — the caller owns
    ``raise_for_status``.
    """
    events = []
    p = cls(record_request=lambda _p, e: events.append(e))
    _mock_client(p, lambda request: httpx.Response(500, text="upstream exploded"))

    response = p._get_with_telemetry(url, {})

    assert response.status_code == 500
    assert len(events) == 1
    event = events[0]
    assert event.provider == provider
    assert event.status_code == 500
    assert event.status_family == "5xx"
    assert event.error_message == "upstream exploded"


@pytest.mark.parametrize(
    ("cls", "url", "provider", "endpoint_key", "endpoint_path"), PROVIDERS
)
def test_get_transport_error_records_event_and_raises(
    cls, url, provider, endpoint_key, endpoint_path
):
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    p = cls(record_request=lambda _p, e: events.append(e))
    _mock_client(p, handler)

    with pytest.raises(httpx.ConnectError):
        p._get_with_telemetry(url, {})

    assert len(events) == 1
    event = events[0]
    assert event.provider == provider
    assert event.status_code is None
    assert event.status_family == "transport_error"
    assert "ConnectError" in event.error_message
    assert len(event.error_message) <= 1000


def test_record_hook_receives_provider_and_event():
    """The recorder hook signature is ``hook(provider, event)`` — scheduler.py
    wires it as ``lambda _provider, event: recorder.record(event)``."""
    seen = []
    p = GprProvider(record_request=lambda prov, e: seen.append((prov, e)))
    _mock_client(p, lambda request: httpx.Response(200, text="ok"))

    p._get_with_telemetry(GprProvider.DEFAULT_URL, {})

    assert len(seen) == 1
    assert seen[0][0] is p


def test_recorder_exception_propagates():
    """A raising record hook is not swallowed: it propagates out of the GET."""

    def bad_hook(_provider, _event):
        raise RuntimeError("recorder dead")

    p = GprProvider(record_request=bad_hook)
    _mock_client(p, lambda request: httpx.Response(200, text="ok"))

    with pytest.raises(RuntimeError, match="recorder dead"):
        p._get_with_telemetry(GprProvider.DEFAULT_URL, {})


def test_non_http_error_propagates_without_event():
    """Only httpx.HTTPError is recorded as a transport error; other exceptions
    propagate unrecorded."""
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise ValueError("not an http error")

    p = GprProvider(record_request=lambda _p, e: events.append(e))
    _mock_client(p, handler)

    with pytest.raises(ValueError, match="not an http error"):
        p._get_with_telemetry(GprProvider.DEFAULT_URL, {})
    assert events == []


def test_tff_job_name_flows_to_event():
    events = []
    p = CftcTffProvider(
        record_request=lambda _p, e: events.append(e),
        job_name="rates_cftc_tff_ingest",
    )
    _mock_client(p, lambda request: httpx.Response(200, text="ok"))

    p._get_with_telemetry(CftcTffProvider.URL, {})

    assert events[0].job_name == "rates_cftc_tff_ingest"


def test_default_job_name_is_none():
    events = []
    p = GprProvider(record_request=lambda _p, e: events.append(e))
    _mock_client(p, lambda request: httpx.Response(200, text="ok"))

    p._get_with_telemetry(GprProvider.DEFAULT_URL, {})

    assert events[0].job_name is None
