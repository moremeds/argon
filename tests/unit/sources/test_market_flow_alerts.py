"""fetch_market_flow_alerts — the market-wide (no-ticker) flow-alerts fetcher
used by /api/scanner/discover. Verifies the audit-first contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.uw import fetch_market_flow_alerts


class _FakeUwClient:
    """Records (slug, ticker, params) and returns the canned payload.

    Carries the same ``rate_limit`` shape the real UwClient does, so
    ``_persist_audit`` can read the telemetry fields without exploding.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[tuple[EndpointSlug, str | None, dict[str, Any] | None]] = []
        self.rate_limit = SimpleNamespace(
            daily_count=0, minute_remaining=110, minute_reset=None
        )

    def get(
        self,
        slug: EndpointSlug,
        ticker: str | None = None,
        params: dict[str, Any] | None = None,
        run_id: int | None = None,
        *,
        option_symbol: str | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        self.calls.append((slug, ticker, params))
        resp = httpx.Response(
            200,
            json=self._payload,
            request=httpx.Request("GET", "https://example/test"),
        )
        return resp, {}


class _RecordingRepo:
    """Captures the Repository methods _persist_audit calls — no DB."""

    def __init__(self) -> None:
        self.audits: list[dict[str, Any]] = []
        self.payloads: list[dict[str, Any]] = []

    def insert_audit_row(
        self,
        *,
        run_id: int,
        endpoint_slug: str,
        endpoint_path: str,
        params: dict[str, Any],
        status_code: int,
        started_at: Any,
        finished_at: Any,
        daily_req_count: int | None = None,
        minute_req_remaining: int | None = None,
        minute_req_reset: Any = None,
        error_message: str | None = None,
    ) -> int:
        self.audits.append(
            {
                "run_id": run_id,
                "slug": endpoint_slug,
                "path": endpoint_path,
                "params": params,
                "status_code": status_code,
            }
        )
        return len(self.audits)  # synthetic audit_id

    def insert_raw_payload(self, audit_id: int, payload: dict[str, Any]) -> None:
        self.payloads.append({"audit_id": audit_id, "payload": payload})


def _flow_alert_payload(n: int = 2) -> dict[str, Any]:
    """Minimal valid market-wide flow-alerts payload (UW returns under "data")."""
    return {
        "data": [
            {
                "id": f"alert-{i}",
                "ticker": "GFS" if i % 2 == 0 else "NVDA",
                "type": "call",
                "strike": "120",
                "underlying_price": "118",
                "total_premium": "1500000",
                "total_ask_side_prem": "1200000",
                "total_bid_side_prem": "300000",
                "volume": 1500,
                "open_interest": 800,
                "has_multileg": False,
                "expiry": "2026-09-18",
                "next_earnings_date": "2026-08-04",
            }
            for i in range(n)
        ],
        "newer_than": None,
        "older_than": None,
    }


def test_fetches_with_no_ticker_filter_and_passes_limit():
    client = _FakeUwClient(_flow_alert_payload())
    repo = _RecordingRepo()
    out = fetch_market_flow_alerts(client, repo, run_id=42, limit=123)
    assert len(out) == 2
    assert len(client.calls) == 1
    slug, ticker, params = client.calls[0]
    assert slug == EndpointSlug.FLOW_ALERTS
    assert ticker is None  # market-wide — NOT scoped to a single ticker
    assert params == {"limit": 123}


def test_writes_audit_row_and_raw_payload_per_audit_first_rule():
    """The audit-first contract (sources/CLAUDE.md) — fetcher MUST persist
    both an audit row and the raw payload, in that order, before returning."""
    client = _FakeUwClient(_flow_alert_payload())
    repo = _RecordingRepo()
    fetch_market_flow_alerts(client, repo, run_id=7)
    assert len(repo.audits) == 1, "audit row not written"
    assert repo.audits[0]["run_id"] == 7
    assert repo.audits[0]["slug"] == EndpointSlug.FLOW_ALERTS.value
    assert repo.audits[0]["status_code"] == 200
    assert len(repo.payloads) == 1, "raw payload not persisted"
    assert repo.payloads[0]["payload"]["data"][0]["ticker"] == "GFS"


def test_default_limit_is_200():
    client = _FakeUwClient(_flow_alert_payload(n=0))
    repo = _RecordingRepo()
    fetch_market_flow_alerts(client, repo, run_id=1)
    _, _, params = client.calls[0]
    assert params == {"limit": 200}
