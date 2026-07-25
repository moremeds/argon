import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources import uw

FIX = Path("tests/fixtures/uw")


def _patch_fetch_json(monkeypatch, payload, captured):
    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kw):
        captured.update(slug=slug, ticker=ticker, params=params, run_id=run_id)
        return payload

    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)


def test_fetch_gex_levels_calls_path_and_normalizes(monkeypatch):
    payload = json.loads((FIX / "gex_levels_aapl.json").read_text())
    captured: dict = {}
    _patch_fetch_json(monkeypatch, payload, captured)
    row = uw.fetch_gex_levels(MagicMock(), MagicMock(), 7, "AAPL", date(2026, 6, 30))
    assert captured["slug"] == EndpointSlug.GEX_LEVELS
    assert captured["ticker"] == "AAPL"
    assert captured["params"] == {"date": "2026-06-30"}
    assert captured["run_id"] == 7
    assert row is not None and row.ticker == "AAPL"


def test_fetch_net_prem_ticks_passes_limit(monkeypatch):
    payload = json.loads((FIX / "net_prem_ticks_aapl.json").read_text())
    captured: dict = {}
    _patch_fetch_json(monkeypatch, payload, captured)
    rows = uw.fetch_net_prem_ticks(
        MagicMock(), MagicMock(), 1, "AAPL", date(2026, 6, 30)
    )
    assert captured["slug"] == EndpointSlug.NET_PREM_TICKS
    assert captured["params"] == {"date": "2026-06-30", "limit": 500}
    assert rows and rows[0].ts is not None


def test_fetch_darkpool_prints_is_distinct_from_ticker_fetcher(monkeypatch):
    payload = json.loads((FIX / "darkpool_aapl.json").read_text())
    captured: dict = {}
    _patch_fetch_json(monkeypatch, payload, captured)
    rows = uw.fetch_darkpool_prints(
        MagicMock(), MagicMock(), 1, "AAPL", date(2026, 6, 30)
    )
    assert captured["slug"] == EndpointSlug.DARKPOOL_TICKER
    assert captured["params"] == {"date": "2026-06-30", "limit": 500}
    assert rows and all(r.tracking_id for r in rows)


def test_fetch_ftds_no_date_param(monkeypatch):
    payload = json.loads((FIX / "ftds_aapl.json").read_text())
    captured: dict = {}
    _patch_fetch_json(monkeypatch, payload, captured)
    rows = uw.fetch_ftds(MagicMock(), MagicMock(), 1, "AAPL")
    assert captured["slug"] == EndpointSlug.FTDS
    assert captured["params"] is None  # full-history endpoint
    assert rows and rows[0].date is not None
