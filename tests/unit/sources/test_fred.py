"""FRED CSV client — parses fredgraph.csv and returns typed rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.fred import FredObservation, FredProvider

SAMPLE_CSV = """observation_date,DFII10
2026-05-12,1.95
2026-05-13,1.97
2026-05-14,.
2026-05-15,2.01
"""

SAMPLE_JSON = {
    "observations": [
        {
            "realtime_start": "2026-05-20",
            "realtime_end": "2026-05-20",
            "date": "2026-05-18",
            "value": "4.47",
        },
        {
            "realtime_start": "2026-05-20",
            "realtime_end": "2026-05-20",
            "date": "2026-05-19",
            "value": ".",
        },
        {
            "realtime_start": "2026-05-20",
            "realtime_end": "2026-05-20",
            "date": "2026-05-20",
            "value": "4.52",
        },
    ]
}


def _fake_response(status: int = 200, text: str = SAMPLE_CSV) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("GET", "https://fred.stlouisfed.org/graph/fredgraph.csv"),
    )


def test_fred_parses_csv_skips_missing():
    """CSV rows with '.' are missing observations and must be skipped."""
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 12))
    assert len(rows) == 3
    assert rows[0] == FredObservation(
        series_id="DFII10",
        obs_date=date(2026, 5, 12),
        value=Decimal("1.95"),
    )
    assert all(r.value is not None for r in rows)


def test_fred_filters_by_start_date():
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 14))
    assert all(r.obs_date >= date(2026, 5, 14) for r in rows)
    assert {r.obs_date for r in rows} == {date(2026, 5, 15)}


def test_fred_telemetry_records_request():
    captured = []

    def fake_record(_self, event):
        captured.append(event)

    with (
        patch.object(FredProvider, "_record_request", fake_record),
        patch("uw_scan.sources.fred.httpx.Client.get") as mock_get,
    ):
        mock_get.return_value = httpx.Response(
            200,
            text=SAMPLE_CSV,
            request=httpx.Request(
                "GET", "https://fred.stlouisfed.org/graph/fredgraph.csv"
            ),
        )
        with FredProvider() as p:
            p.fetch_series("DFII10", start=date(2026, 5, 12))

    assert len(captured) == 1
    event = captured[0]
    assert event.provider == "fred"
    assert event.endpoint_key == "fred_csv"
    assert event.path == "/graph/fredgraph.csv"
    assert event.status_code == 200
    assert event.status_family == "2xx"
    assert event.method == "GET"
    assert event.error_message is None
    assert event.latency_ms >= 0


def test_fred_json_observations_use_official_api_and_skip_missing_values():
    captured = []

    def fake_record(_self, event):
        captured.append(event)

    with (
        patch.object(FredProvider, "_record_request", fake_record),
        patch("uw_scan.sources.fred.httpx.Client.get") as mock_get,
    ):
        mock_get.return_value = httpx.Response(
            200,
            json=SAMPLE_JSON,
            request=httpx.Request(
                "GET",
                "https://api.stlouisfed.org/fred/series/observations",
            ),
        )
        with FredProvider(api_key="fred-secret") as p:
            rows = p.fetch_observations(
                "DGS10",
                start=date(2026, 5, 18),
                end=date(2026, 5, 20),
            )

    assert mock_get.call_count == 1
    url = str(mock_get.call_args.args[0])
    params = mock_get.call_args.kwargs["params"]
    assert url == "https://api.stlouisfed.org/fred/series/observations"
    assert params["series_id"] == "DGS10"
    assert params["observation_start"] == "2026-05-18"
    assert params["observation_end"] == "2026-05-20"
    assert params["file_type"] == "json"
    assert params["api_key"] == "fred-secret"
    assert rows == [
        FredObservation(
            series_id="DGS10",
            obs_date=date(2026, 5, 18),
            value=Decimal("4.47"),
            realtime_start=date(2026, 5, 20),
            realtime_end=date(2026, 5, 20),
        ),
        FredObservation(
            series_id="DGS10",
            obs_date=date(2026, 5, 20),
            value=Decimal("4.52"),
            realtime_start=date(2026, 5, 20),
            realtime_end=date(2026, 5, 20),
        ),
    ]

    assert len(captured) == 1
    event = captured[0]
    assert event.endpoint_key == "fred_series_observations"
    assert event.path == "/fred/series/observations"
    assert event.path_template == "/fred/series/observations"
    assert "api_key" not in event.params
    assert event.params["series_id"] == "DGS10"


def test_fred_json_http_errors_do_not_expose_api_key():
    with patch("uw_scan.sources.fred.httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(
            403,
            text="forbidden",
            request=httpx.Request(
                "GET",
                "https://api.stlouisfed.org/fred/series/observations"
                "?series_id=DGS10&api_key=fred-secret",
            ),
        )
        with FredProvider(api_key="fred-secret") as p:
            try:
                p.fetch_observations("DGS10", start=date(2026, 5, 18))
            except RuntimeError as exc:
                message = str(exc)
            else:
                raise AssertionError("FRED HTTP error should raise")

    assert "fred-secret" not in message
    assert "api_key" not in message
    assert "fred_series_observations" in message
    assert "403" in message


class TestVintageAwarePayloadFetch:
    """The evidence layer needs the exact bytes and a specific ALFRED vintage window.

    ``fetch_observations`` returns parsed rows for the CURRENT vintage only, which is
    fine for the legacy rates surface and useless for point-in-time replay.
    """

    def _capture(self, **kwargs):
        seen: dict[str, object] = {}

        def fake_get(_self, base_url, path, params, *, endpoint_key, path_template):
            seen["params"] = dict(params)
            return httpx.Response(
                200,
                content=b'{"observations": []}',
                request=httpx.Request("GET", f"{base_url}{path}"),
            )

        with patch.object(FredProvider, "_get_with_telemetry", fake_get):
            with FredProvider(api_key="secret-key-value") as provider:
                payload, url = provider.fetch_series_payload("CPIAUCSL", **kwargs)
        return payload, url, seen["params"]

    def test_vintage_window_reaches_the_request(self):
        _, _, params = self._capture(
            realtime_start=date(2024, 6, 1), realtime_end=date(2024, 6, 1)
        )
        assert params["realtime_start"] == "2024-06-01"
        assert params["realtime_end"] == "2024-06-01"

    def test_omitting_the_window_asks_for_the_current_vintage(self):
        _, _, params = self._capture()
        assert "realtime_start" not in params
        assert "realtime_end" not in params

    def test_raw_bytes_are_returned_unparsed(self):
        payload, _, _ = self._capture()
        assert payload == b'{"observations": []}'

    def test_the_audited_url_never_carries_the_api_key(self):
        # FRED takes the key as a query parameter, so a naively recorded request URL
        # would write the secret into the external-API audit table.
        _, url, params = self._capture(realtime_start=date(2024, 6, 1))
        assert "secret-key-value" not in url
        assert "api_key" not in url
        assert params["api_key"] == "secret-key-value"
