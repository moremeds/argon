"""Watchlist lifecycle log: add/remove deltas are recorded append-only, current
status = latest event, and a remove->re-add cycle preserves the full history."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_healer import reconcile_watchlist_lifecycle


def test_lifecycle_logs_adds_removes_and_preserves_history(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)

    # first run: baseline -> the whole current watchlist logs as 'added'
    r1 = reconcile_watchlist_lifecycle(
        repo, gap, date(2026, 6, 1), active=["AAPL", "NVDA"]
    )
    assert r1 == {"added": ["AAPL", "NVDA"], "removed": []}

    # NVDA drops out, TSLA joins
    r2 = reconcile_watchlist_lifecycle(
        repo, gap, date(2026, 6, 2), active=["AAPL", "TSLA"]
    )
    assert r2 == {"added": ["TSLA"], "removed": ["NVDA"]}
    assert gap.current_ticker_status() == {
        "AAPL": "added",
        "NVDA": "removed",
        "TSLA": "added",
    }

    # idempotent: no change -> no new events
    r3 = reconcile_watchlist_lifecycle(
        repo, gap, date(2026, 6, 3), active=["AAPL", "TSLA"]
    )
    assert r3 == {"added": [], "removed": []}

    # re-add NVDA -> 'added' again; the prior removal is NOT erased
    r4 = reconcile_watchlist_lifecycle(
        repo, gap, date(2026, 6, 4), active=["AAPL", "TSLA", "NVDA"]
    )
    assert r4 == {"added": ["NVDA"], "removed": []}
    nvda = [e["event"] for e in gap.list_ticker_events(ticker="NVDA")]
    assert nvda == ["added", "removed", "added"]  # newest-first, full history
    assert gap.current_ticker_status()["NVDA"] == "added"
