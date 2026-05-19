"""fetch_option_contract_intraday — per-minute UW bars for one option contract.

Verifies the audit-first contract, the option_symbol path substitution,
and the date param wiring. Mirrors tests/unit/sources/test_market_flow_alerts.py
so the project's fetcher test pattern stays consistent.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.uw import fetch_option_contract_intraday


class _FakeUwClient:
    """Records (slug, ticker, params, option_symbol) and returns canned JSON."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[
            tuple[EndpointSlug, str | None, dict[str, Any] | None, str | None]
        ] = []
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
        self.calls.append((slug, ticker, params, option_symbol))
        resp = httpx.Response(
            200,
            json=self._payload,
            request=httpx.Request("GET", "https://example/test"),
        )
        return resp, {}


class _RecordingRepo:
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
        return len(self.audits)

    def insert_raw_payload(self, audit_id: int, payload: dict[str, Any]) -> None:
        self.payloads.append({"audit_id": audit_id, "payload": payload})


def _intraday_payload(n: int = 3) -> dict[str, Any]:
    """Minimal valid intraday payload mirroring the UW field set.

    Field set per docs/uw-samples/uw_api_capability_audit.json
    /api/option-contract/{id}/intraday entry.
    """
    return {
        "data": [
            {
                "start_time": f"2026-05-14T13:3{i}:00Z",
                "open": "1.20",
                "high": "1.35",
                "low": "1.18",
                "close": "1.30",
                "avg_price": "1.27",
                "iv_high": "0.42",
                "iv_low": "0.39",
                "volume_ask_side": 100 + i,
                "volume_bid_side": 40 + i,
                "volume_mid_side": 5,
                "volume_multi": 0,
                "premium_ask_side": "12700.00",
                "premium_bid_side": "5080.00",
                "premium_mid_side": "635.00",
                "premium_no_side": "0.00",
            }
            for i in range(n)
        ]
    }


def test_substitutes_option_symbol_into_path_and_passes_date_param():
    client = _FakeUwClient(_intraday_payload(n=2))
    repo = _RecordingRepo()
    out = fetch_option_contract_intraday(
        client,
        repo,
        run_id=42,
        option_symbol="TSLA260515C00450000",
        date="2026-05-14",
    )
    assert len(out) == 2
    assert len(client.calls) == 1
    slug, ticker, params, option_symbol = client.calls[0]
    assert slug == EndpointSlug.OPTION_CONTRACT_INTRADAY
    assert ticker is None  # path uses {option_symbol}, not {ticker}
    assert option_symbol == "TSLA260515C00450000"
    assert params == {"date": "2026-05-14"}


def test_writes_audit_row_and_raw_payload_per_audit_first_rule():
    """sources/CLAUDE.md audit-first contract: audit row + raw payload must
    be persisted BEFORE the fetcher returns its typed models."""
    client = _FakeUwClient(_intraday_payload(n=1))
    repo = _RecordingRepo()
    fetch_option_contract_intraday(
        client,
        repo,
        run_id=7,
        option_symbol="AAPL260619P00180000",
        date="2026-05-14",
    )
    assert len(repo.audits) == 1
    assert repo.audits[0]["run_id"] == 7
    assert repo.audits[0]["slug"] == EndpointSlug.OPTION_CONTRACT_INTRADAY.value
    # Path includes the substituted option_symbol — confirms build_path wiring.
    assert "AAPL260619P00180000" in repo.audits[0]["path"]
    assert repo.audits[0]["status_code"] == 200
    assert len(repo.payloads) == 1
    assert "start_time" in repo.payloads[0]["payload"]["data"][0]


def test_normalizes_decimal_and_int_fields():
    """Pydantic v2 coerces the JSON string decimals back to Decimal and
    integers stay integers — verifies the model contract."""
    from decimal import Decimal

    client = _FakeUwClient(_intraday_payload(n=1))
    repo = _RecordingRepo()
    [bucket] = fetch_option_contract_intraday(
        client,
        repo,
        run_id=1,
        option_symbol="NVDA260619C00200000",
        date="2026-05-14",
    )
    assert bucket.open == Decimal("1.20")
    assert bucket.close == Decimal("1.30")
    assert bucket.volume_ask_side == 100
    assert bucket.premium_ask_side == Decimal("12700.00")
