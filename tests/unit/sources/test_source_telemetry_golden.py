"""Characterization of every hand-rolled source client's request telemetry (I-56).

Each client drives its public fetch method through ``httpx.MockTransport`` in four
scenarios -- 200, 404, 500, transport error -- and records every
``ExternalApiRequestEvent`` it emits. The golden was frozen on main's code BEFORE
the shared ``sources/_http.py`` existed, so the refactor must reproduce it exactly:
same provider, endpoint_key, path, params, status, family, error text, request id.
Clock fields (``started_at``, ``finished_at``, ``latency_ms``) are dropped.

Regenerate ONLY on purpose: ``UPDATE_TELEMETRY_GOLDEN=1 uv run pytest <this file>``.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from uw_scan.sources.cftc_cot import CftcCotProvider
from uw_scan.sources.cftc_tff import CftcTffProvider
from uw_scan.sources.cleveland_fed import ClevelandFedInflationProvider
from uw_scan.sources.etf_holdings import EtfHoldingsProvider
from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesPathProvider
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.gpr import GprProvider
from uw_scan.sources.lbma import LbmaProvider
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.sources.treasury_supply import TreasurySupplyProvider
from uw_scan.sources.wgc_cb import WgcCbProvider
from uw_scan.sources.wgc_etf import WgcEtfProvider

GOLDEN = Path(__file__).parent / "fixtures" / "source_telemetry_golden.json"
_CLOCK_FIELDS = ("started_at", "finished_at", "latency_ms")
D = date(2026, 9, 1)


def _scenario_handler(kind: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "transport":
            raise httpx.ConnectError("connection refused", request=request)
        status = {"ok": 200, "not_found": 404, "server_error": 500}[kind]
        return httpx.Response(
            status, content=b"payload", headers={"x-request-id": "req-1"}
        )

    return handler


class _Recorder:
    """Stands in for ExternalApiRequestRecorder (ohlc) and the record_request hook."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event) -> bool:
        row = dataclasses.asdict(event)
        for field in _CLOCK_FIELDS:
            row.pop(field, None)
        self.events.append(json.loads(json.dumps(row, default=str)))
        return True

    def hook(self, _provider, event) -> None:
        self.record(event)


# name -> (construct(recorder), call(provider))
CLIENTS: dict[str, tuple[Callable, Callable]] = {
    "cftc_cot": (
        lambda r: CftcCotProvider(record_request=r.hook),
        lambda p: p.fetch_weekly(start=D),
    ),
    "cftc_tff": (
        lambda r: CftcTffProvider(record_request=r.hook),
        lambda p: p.fetch_treasury_payload(start=D),
    ),
    "cleveland_fed": (
        lambda r: ClevelandFedInflationProvider(record_request=r.hook),
        lambda p: p.fetch_model_rows(start=D),
    ),
    "etf_holdings_gld": (
        lambda r: EtfHoldingsProvider(record_request=r.hook, max_retries=2),
        lambda p: p.fetch_gld_payload(start=D),
    ),
    "fed_funds_futures_path": (
        lambda r: FedFundsFuturesPathProvider(record_request=r.hook),
        lambda p: p.fetch_bundle(
            retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc)
        ),
    ),
    "fred": (
        lambda r: FredProvider(api_key="k", record_request=r.hook),
        lambda p: p.fetch_series_payload("DGS10", start=D, end=D),
    ),
    "gpr": (
        lambda r: GprProvider(record_request=r.hook),
        lambda p: p.fetch_daily(start=D),
    ),
    "lbma": (
        lambda r: LbmaProvider(record_request=r.hook),
        lambda p: p.fetch_monthly(start=D),
    ),
    "ohlc": (
        lambda r: MassiveOhlcProvider(api_key="k", telemetry_recorder=r),
        lambda p: p.fetch_daily_payload("SPY", D, D),
    ),
    "treasury_supply_auctions": (
        lambda r: TreasurySupplyProvider(record_request=r.hook),
        lambda p: p.fetch_auctions_payload(security_type="Bill"),
    ),
    "treasury_supply_debt": (
        lambda r: TreasurySupplyProvider(record_request=r.hook),
        lambda p: p.fetch_latest_debt(),
    ),
    "wgc_cb": (
        lambda r: WgcCbProvider(cookie_header="c=1", record_request=r.hook),
        lambda p: p.fetch_quarterly_workbook(),
    ),
    "wgc_etf": (
        lambda r: WgcEtfProvider(cookie_header="c=1", record_request=r.hook),
        lambda p: p.fetch_workbook("https://www.gold.org/download/file/1/x.xlsx"),
    ),
}
SCENARIOS = ("ok", "not_found", "server_error", "transport")


def _capture(name: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    construct, call = CLIENTS[name]
    recorder = _Recorder()
    provider = construct(recorder)
    real = provider._client
    provider._client = httpx.Client(
        transport=httpx.MockTransport(_scenario_handler(kind)),
        headers=real.headers,
        base_url=real.base_url,
    )
    real.close()
    try:
        call(provider)
    except Exception:  # noqa: BLE001 - only the emitted telemetry is under test
        pass
    finally:
        provider.close()
    return recorder.events


def _capture_all(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, list[dict]]]:
    return {
        name: {kind: _capture(name, kind, monkeypatch) for kind in SCENARIOS}
        for name in CLIENTS
    }


def test_source_telemetry_matches_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _capture_all(monkeypatch)
    if os.environ.get("UPDATE_TELEMETRY_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
    golden = json.loads(GOLDEN.read_text())
    for name in CLIENTS:
        for kind in SCENARIOS:
            assert current[name][kind] == golden[name][kind], (name, kind)


def test_every_scenario_emitted_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The golden is only a proof if each client actually reached the network in
    every scenario; an empty event list would match an empty golden forever."""
    golden = json.loads(GOLDEN.read_text())
    empty = [(n, k) for n in CLIENTS for k in SCENARIOS if not golden[n][k]]
    assert not empty, empty
