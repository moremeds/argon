from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.worker.jobs.greek_exposure_daily_refresh import (
    greek_exposure_daily_refresh,
)


def test_daily_refresh_writes_single_names(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    # Fake UW aggregate /greek-exposure history rows (the shape gex.run upserts).
    fake = [
        {
            "date": date(2026, 6, 23),
            "call_gex": 5.0,
            "put_gex": -2.0,
            "call_delta": 1.0,
            "put_delta": -1.0,
        },
        {
            "date": date(2026, 6, 24),
            "call_gex": 6.0,
            "put_gex": -2.5,
            "call_delta": 1.1,
            "put_delta": -1.1,
        },
    ]

    def _fake_agg(client, r, run_id, ticker):
        return fake if ticker == "NVDA" else []

    monkeypatch.setattr(
        "uw_scan.worker.jobs.greek_exposure_daily_refresh.fetch_aggregate_gex",
        _fake_agg,
    )

    settings = SimpleNamespace(
        db_schema=repo._schema, gex_scan_tickers=["SPX", "SPY", "TLT"]
    )
    summary = greek_exposure_daily_refresh(
        repo=repo,
        client=object(),  # ignored — fetch_aggregate_gex is monkeypatched
        settings=settings,
        ticker_filter=lambda t: t == "NVDA",
    )
    assert summary["rows"] == 2
    assert summary["tickers"] == 1

    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    hist = g.fetch_history("NVDA", days=10)
    assert hist and hist[-1]["net_gex"] == pytest.approx(3.5)  # 6 + (-2.5)


def test_daily_refresh_skips_index_tickers(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    calls: list[str] = []

    def _fake_agg(client, r, run_id, ticker):
        calls.append(ticker)
        return []

    monkeypatch.setattr(
        "uw_scan.worker.jobs.greek_exposure_daily_refresh.fetch_aggregate_gex",
        _fake_agg,
    )
    settings = SimpleNamespace(
        db_schema=repo._schema, gex_scan_tickers=["SPX", "SPY", "TLT"]
    )
    summary = greek_exposure_daily_refresh(
        repo=repo,
        client=object(),
        settings=settings,
        ticker_filter=lambda t: t == "SPY",
    )
    # SPY is an index ticker — already refreshed by the regime GEX scan, so it
    # is skipped here and never fetched.
    assert "SPY" not in calls
    assert summary["skipped_index"] >= 1
