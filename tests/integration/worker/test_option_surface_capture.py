# tests/integration/worker/test_option_surface_capture.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import uw_scan.worker.jobs.option_surface_capture as job

from uw_scan.models import GreeksRow


def _stub_sources(monkeypatch, *, raise_for: str | None = None):
    def fake_contracts(client, repo, run_id, ticker, limit):
        return [
            SimpleNamespace(option_symbol=f"{ticker:<6}260717C00250000"),
            SimpleNamespace(option_symbol=f"{ticker:<6}260821C00250000"),
        ]

    def fake_greeks(client, repo, run_id, ticker, expiry_iso):
        if raise_for is not None and ticker == raise_for:
            raise RuntimeError("boom")
        e = date.fromisoformat(expiry_iso)
        return [
            GreeksRow(
                date=date(2026, 6, 19),
                expiry=e,
                strike=Decimal("250"),
                call_volatility=Decimal("0.50"),
                put_volatility=Decimal("0.52"),
                call_delta=Decimal("0.5"),
                put_delta=Decimal("-0.5"),
            )
        ]

    monkeypatch.setattr(job, "fetch_option_contracts", fake_contracts)
    monkeypatch.setattr(job, "fetch_greeks", fake_greeks)


def test_capture_writes_full_chain_with_spot(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards  # has a TSLA watchlist card
    _stub_sources(monkeypatch)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")

    n = job.option_surface_capture(repo=repo, client=None, today=date(2026, 6, 19))

    assert n >= 2  # one strike x two expiries for TSLA (plus any other seeded cards)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(distinct expiry) "
            "FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'"
        )
        assert cur.fetchone() == (2, 2)
        cur.execute(
            "SELECT call_iv, underlying_spot FROM uw_scan.option_surface_grid_daily "
            "WHERE ticker='TSLA' AND expiry=%s",
            (date(2026, 7, 17),),
        )
        iv, spot = cur.fetchone()
        assert iv == Decimal("0.50")
        assert spot == card.spot  # stamped from the watchlist card


def test_capture_isolates_a_failing_ticker(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards
    _stub_sources(monkeypatch, raise_for="TSLA")  # TSLA explodes
    # Must not raise; TSLA simply contributes no rows.
    job.option_surface_capture(repo=repo, client=None, today=date(2026, 6, 19))
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'"
        )
        assert cur.fetchone()[0] == 0
