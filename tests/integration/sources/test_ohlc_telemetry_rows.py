"""massive OHLC request rows land in external_api_requests exactly as before I-56.

``ohlc`` is the one source client whose provider ('massive') passes the
``external_api_requests.provider`` CHECK, so its telemetry is real rows, not a debug
line. Drive it through the REAL ``ExternalApiRequestRecorder`` into the test DB and
compare every stored column with the events frozen in
``tests/unit/sources/fixtures/source_telemetry_golden.json`` -- which were captured
on main's code before ``sources/_http.py`` existed.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder

pytestmark = pytest.mark.integration

GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "unit"
    / "sources"
    / "fixtures"
    / "source_telemetry_golden.json"
)
#: event field -> external_api_requests column (only params is renamed).
_COLUMN_FOR = {"params": "params_json"}
_COLUMNS = (
    "provider",
    "endpoint_key",
    "method",
    "path_template",
    "path",
    "ticker",
    "params",
    "status_code",
    "status_family",
    "attempt",
    "run_id",
    "job_name",
    "provider_request_id",
    "official_daily_count",
    "official_daily_limit",
    "official_minute_remaining",
    "official_minute_reset",
    "error_message",
)


def _handler(kind: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "transport":
            raise httpx.ConnectError("connection refused", request=request)
        status = {"ok": 200, "not_found": 404, "server_error": 500}[kind]
        return httpx.Response(
            status, content=b"payload", headers={"x-request-id": "req-1"}
        )

    return handler


@pytest.mark.parametrize("kind", ["ok", "not_found", "server_error", "transport"])
def test_ohlc_rows_match_the_pre_refactor_events(
    seeded_db_empty_cards, _migrated_settings, kind
):
    conn = seeded_db_empty_cards.conn
    conn.execute("TRUNCATE uw_scan.external_api_requests")
    conn.commit()

    with ExternalApiRequestRecorder(_migrated_settings.db_dsn()) as recorder:
        provider = MassiveOhlcProvider(api_key="k", telemetry_recorder=recorder)
        real = provider._client
        provider._client = httpx.Client(
            transport=httpx.MockTransport(_handler(kind)),
            headers=real.headers,
            base_url=real.base_url,
        )
        real.close()
        try:
            provider.fetch_daily_payload("SPY", date(2026, 9, 1), date(2026, 9, 1))
        except Exception:  # noqa: BLE001 - only the stored rows are under test
            pass
        finally:
            provider.close()

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_COLUMN_FOR.get(c, c) for c in _COLUMNS)} "
            "FROM uw_scan.external_api_requests ORDER BY request_id"
        )
        rows = [dict(zip(_COLUMNS, r, strict=True)) for r in cur.fetchall()]

    expected = [
        {c: e[c] for c in _COLUMNS}
        for e in json.loads(GOLDEN.read_text())["ohlc"][kind]
    ]
    assert rows == expected
