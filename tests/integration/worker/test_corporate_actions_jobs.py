from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once


class _FakeProvider:
    def fetch_splits(self, ticker, *, limit=12):
        return [
            {
                "execution_date": date(2024, 6, 10),
                "split_from": Decimal("1"),
                "split_to": Decimal("10"),
            }
        ]

    def fetch_dividends(self, ticker, *, limit=24):
        return [{"ex_dividend_date": date(2024, 9, 12), "cash_amount": Decimal("0.01")}]


def test_ingest_writes_events(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    monkeypatch.setattr(
        repo, "list_active_watchlist", lambda: [SimpleNamespace(ticker="NVDA")]
    )
    n = corporate_actions_refresh_once(repo, _FakeProvider())
    # Regression guard: the function MUST commit its own writes (the scheduler's
    # _repo closes the connection without committing). Roll back here — if the
    # ingest left work uncommitted, this discards it and the assert below fails.
    repo.conn.rollback()
    assert n == 1
    rows = repo.fetch_corporate_actions("NVDA")
    assert {r["event_type"] for r in rows} == {"split", "dividend"}
    split = next(r for r in rows if r["event_type"] == "split")
    assert split["split_ratio"] == Decimal("10")


def test_null_provider_noops(seeded_db_empty_cards):
    assert corporate_actions_refresh_once(seeded_db_empty_cards, None) == 0
