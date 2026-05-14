from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from uw_scan.api.client import UwClient, UwHTTPError
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository


class _ProviderStubHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def _json(
        self,
        status: int,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/stock/TSLA/iv-rank":
            self._json(200, {"ok": True}, _uw_headers(101))
        elif path == "/api/stock/AAPL/iv-rank":
            self._json(200, {"ok": True}, _uw_headers(102))
        elif path == "/api/stock/TSLA/greek-exposure/strike-expiry":
            self._json(429, {"error": "rate limited"}, _uw_headers(103))
        elif path == "/api/stock/NVDA/volatility/stats":
            self._json(503, {"error": "unavailable"}, _uw_headers(104))
        elif path == "/v2/aggs/ticker/TSLA/range/1/day/2026-05-01/2026-05-02":
            self._json(
                200,
                {
                    "request_id": "massive-ok-1",
                    "results": [{
                        "t": 1777593600000,
                        "o": 1,
                        "h": 2,
                        "l": 1,
                        "c": 1.5,
                        "v": 100,
                    }],
                },
            )
        elif path == "/v2/aggs/ticker/MSFT/range/1/day/2026-05-01/2026-05-02":
            self._json(503, {"request_id": "massive-fail-1", "error": "maintenance"})
        else:
            self._json(404, {"error": "not found", "path": path})


def _uw_headers(daily_count: int) -> dict[str, str]:
    return {
        "x-uw-daily-req-count": str(daily_count),
        "x-uw-token-req-limit": "1000",
        "x-uw-req-per-minute-remaining": "87",
        "x-uw-req-per-minute-reset": "60",
    }


@pytest.fixture
def provider_stub_base_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _settings_for_repo(repo: Repository) -> Settings:
    return Settings.from_env().model_copy(update={"db_name": repo.conn.info.dbname})


def test_clients_record_realistic_provider_request_rows(
    seeded_db_empty_cards: Repository,
    provider_stub_base_url: str,
) -> None:
    settings = _settings_for_repo(seeded_db_empty_cards)

    with ExternalApiRequestRecorder(
        settings.db_dsn(), schema=settings.db_schema
    ) as recorder:
        with UwClient(
            "dummy-key",
            base_url=provider_stub_base_url,
            max_retries=0,
            telemetry_recorder=recorder,
            job_name="client_instrumentation_test",
        ) as client:
            client.get(EndpointSlug.IV_RANK, ticker="TSLA")
            client.get(EndpointSlug.IV_RANK, ticker="AAPL")

        for slug, ticker, params in [
            (EndpointSlug.GREEK_EXPOSURE, "TSLA", {"expiry": "2026-06-19"}),
            (EndpointSlug.VOLATILITY_STATS, "NVDA", {}),
        ]:
            with UwClient(
                "dummy-key",
                base_url=provider_stub_base_url,
                max_retries=0,
                telemetry_recorder=recorder,
                job_name="client_instrumentation_test",
            ) as client:
                with pytest.raises(UwHTTPError):
                    client.get(slug, ticker=ticker, params=params)

        with MassiveOhlcProvider(
            "dummy-key",
            base_url=provider_stub_base_url,
            telemetry_recorder=recorder,
            job_name="client_instrumentation_test",
        ) as provider:
            provider.fetch_daily("TSLA", date(2026, 5, 1), date(2026, 5, 2))
            with pytest.raises(Exception):
                provider.fetch_daily("MSFT", date(2026, 5, 1), date(2026, 5, 2))

    rows = seeded_db_empty_cards.list_external_api_requests(
        provider="all",
        start=datetime.now(UTC) - timedelta(minutes=5),
        end=datetime.now(UTC) + timedelta(minutes=5),
        limit=10,
    )
    rows = [row for row in rows if row.job_name == "client_instrumentation_test"]

    assert len(rows) == 6
    recorded = sorted(
        (row.provider, row.endpoint_key, row.ticker, row.status_family)
        for row in rows
    )
    assert recorded == [
        ("massive", "daily_ohlc", "MSFT", "5xx"),
        ("massive", "daily_ohlc", "TSLA", "2xx"),
        ("uw", "greek_exposure", "TSLA", "4xx"),
        ("uw", "iv_rank", "AAPL", "2xx"),
        ("uw", "iv_rank", "TSLA", "2xx"),
        ("uw", "volatility_stats", "NVDA", "5xx"),
    ]
    assert max(row.official_daily_count or 0 for row in rows) == 104
    assert {row.provider_request_id for row in rows if row.provider == "massive"} == {
        "massive-ok-1",
        "massive-fail-1",
    }
