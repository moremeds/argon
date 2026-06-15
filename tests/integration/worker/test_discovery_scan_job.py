"""End-to-end discovery_scan job with fake UW client + DP fixtures."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import DarkPoolPrint, FlowAlert
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository
from uw_scan.worker.jobs.discovery_scan import discovery_scan_once


class _FakeUw:
    """Stands in for UwClient — the job only passes it through to fetchers."""


def _alert(ticker, opt_type, premium, *, sweep=False, vol=2000, oi=500):
    return FlowAlert(
        id=f"{ticker}-{opt_type}-{premium}",
        ticker=ticker,
        type=opt_type,
        total_premium=Decimal(str(premium)),
        total_ask_side_prem=Decimal(str(premium)) * Decimal("0.9"),
        total_bid_side_prem=Decimal(str(premium)) * Decimal("0.1"),
        volume=vol,
        open_interest=oi,
        volume_oi_ratio=Decimal(str(vol)) / Decimal(str(oi)),
        has_sweep=sweep,
        underlying_price=Decimal("10.00"),
        next_earnings_date=date(2026, 12, 31),
        sector="Technology",
        created_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
    )


def test_discovery_scan_persists_snapshots_and_dp(seeded_db_empty_cards, monkeypatch):
    repo: Repository = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()

    # Synthetic tickers guaranteed absent from the seeded watchlist (CRWV/WULF
    # etc. may be seeded → they'd be excluded before scoring).
    alerts = [
        _alert("ZAAA", "call", 300000, sweep=True),
        _alert("ZAAA", "call", 250000, sweep=True),
        _alert("ZBBB", "put", 200000),
    ]

    def fake_market_alerts(client, r, run_id, limit=200):
        return alerts

    def fake_darkpool(client, r, run_id, ticker):
        # Buy-heavy prints (price above mid) → ACCUMULATION.
        return [
            DarkPoolPrint(
                ticker=ticker,
                tracking_id=abs(hash((ticker, i))) % 1_000_000,
                executed_at=datetime(2026, 6, 15, 13, i, tzinfo=timezone.utc),
                price=Decimal("10.00"),
                size=5000,
                premium=Decimal("50000"),
                nbbo_bid=Decimal("9.50"),
                nbbo_ask=Decimal("9.90"),
                canceled=False,
            )
            for i in range(3)
        ]

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_market_flow_alerts",
        fake_market_alerts,
    )
    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_darkpool_ticker", fake_darkpool
    )

    summary = discovery_scan_once(repo=repo, client=_FakeUw(), settings=settings)
    repo.conn.commit()

    assert summary["status"] == "ok"
    assert summary["candidates_found"] >= 1

    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    tickers = {c["ticker"] for c in snap["candidates"]}
    assert "ZAAA" in tickers
    # ZAAA should outrank ZBBB (sweeps + confluence).
    assert snap["candidates"][0]["ticker"] == "ZAAA"
    assert snap["candidates"][0]["score_model"] == "edge_quality_v1"
    assert snap["alerts_pulled"] == 3  # from scan_runs.aggregates run-meta

    # DP prints landed in the warm table for reuse.
    zaaa_dp = sigs.fetch_dark_pool_window("ZAAA", lookback_days=5)
    assert len(zaaa_dp) == 3


def test_discovery_scan_degrades_when_dp_fetch_fails(
    seeded_db_empty_cards, monkeypatch
):
    repo: Repository = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_market_flow_alerts",
        lambda c, r, run_id, limit=200: [_alert("ZAAA", "call", 300000, sweep=True)],
    )

    def boom(client, r, run_id, ticker):
        raise RuntimeError("UW darkpool 500")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_darkpool_ticker", boom
    )

    summary = discovery_scan_once(repo=repo, client=_FakeUw(), settings=settings)
    repo.conn.commit()
    assert summary["status"] == "ok"

    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    # Still scored on flow factors; DP marked degraded; DP factors zeroed.
    cand = next(c for c in snap["candidates"] if c["ticker"] == "ZAAA")
    assert cand["evidence"]["dp_status"] == "degraded"
    assert cand["evidence"]["dp_direction"] == "NO_DATA"


def test_discovery_scan_empty_feed(seeded_db_empty_cards, monkeypatch):
    repo: Repository = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()
    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_market_flow_alerts",
        lambda c, r, run_id, limit=200: [],
    )

    summary = discovery_scan_once(repo=repo, client=_FakeUw(), settings=settings)
    repo.conn.commit()
    assert summary["status"] == "ok"
    assert summary["candidates_found"] == 0

    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["candidates"] == []
