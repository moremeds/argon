"""The backfill used `len(done) >= len(cards)` to decide a date was complete.
Equal counts with different members skipped the missing member forever."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from uw_scan.worker.jobs import option_surface_capture as mod


class _Cur:
    def __init__(self, done_tickers: list[str]):
        self._done = done_tickers

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return [(t,) for t in self._done]

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Repo:
    def __init__(self, done: list[str], cards: list[str]):
        self._done = done
        self._cards = cards
        self._schema = "uw_scan"
        self.conn = SimpleNamespace(
            cursor=lambda: _Cur(self._done), commit=lambda: None, rollback=lambda: None
        )

    def list_watchlist_cards(self):
        return [SimpleNamespace(ticker=t) for t in self._cards]

    def insert_scan_run(self, _ticker, notes=""):
        return 1

    def upsert_option_surface_grid(self, _ticker, _d, _spot, rows):
        return len(rows)

    def finish_scan_run(self, _run_id, status=""):
        return None


def _run(done: list[str], cards: list[str]) -> list[str]:
    """Return the tickers the backfill tried to capture for one weekday."""
    captured: list[str] = []

    def fake_rows(*, ticker, **_k):
        captured.append(ticker)
        return [{"row": 1}]

    client = SimpleNamespace(rate_limit=SimpleNamespace(daily_count=0))
    with patch.object(mod, "_build_ticker_rows", side_effect=fake_rows):
        mod.option_surface_backfill(
            repo=_Repo(done, cards),
            client=client,
            days_back=1,  # exactly one weekday ending yesterday
            end_date=date.today() - timedelta(days=1),
        )
    return captured


def test_same_count_different_members_captures_the_missing_one():
    assert _run(done=["AAPL", "MSFT"], cards=["AAPL", "NVDA"]) == ["NVDA"]


def test_superset_of_cards_is_fully_captured_and_skipped():
    assert _run(done=["AAPL", "MSFT", "OLD"], cards=["AAPL", "MSFT"]) == []


def test_exact_match_is_skipped():
    assert _run(done=["AAPL", "MSFT"], cards=["AAPL", "MSFT"]) == []
