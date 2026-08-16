"""option_chain_per_strike can be replayed, but only with THAT session's spot.

The chain is filtered to strikes within ±60% of spot. Replaying with today's
spot would select a different strike band than the session actually had, so the
rows would be real numbers under a subtly wrong selection.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from uw_scan.worker.jobs import flow_data_refresh as F


def test_replay_uses_the_historical_close_not_todays_spot(monkeypatch):
    seen: dict = {}

    monkeypatch.setattr(F, "fetch_option_contracts", lambda *a, **k: (seen.setdefault("kw", k), [])[1])
    monkeypatch.setattr(
        F,
        "aggregate_chain_per_strike",
        lambda contracts, **kw: seen.setdefault("spot", kw["spot"]) or [],
    )
    repo = MagicMock()
    repo.insert_scan_run.return_value = 7
    repo.upsert_option_chain_per_strike.return_value = 3

    n = F.refresh_ticker_chain(
        repo=repo,
        client=MagicMock(),
        ticker="AAPL",
        spot=Decimal("231.50"),
        market_date=date(2026, 8, 12),
    )

    assert seen["spot"] == Decimal("231.50")
    assert seen["kw"]["market_date"] == date(2026, 8, 12)
    assert n == 3
    # the snapshot must be written under the replayed date
    assert repo.upsert_option_chain_per_strike.call_args[0][1] == date(2026, 8, 12)


def test_replay_never_writes_options_volume_daily(monkeypatch):
    """/options-volume ignores `date` (measured 2026-08-16), so the replay must
    not touch that table at all."""
    called = {}
    monkeypatch.setattr(
        F, "fetch_options_volume_daily", lambda *a, **k: called.setdefault("hit", True)
    )
    monkeypatch.setattr(F, "fetch_option_contracts", lambda *a, **k: [])
    monkeypatch.setattr(F, "aggregate_chain_per_strike", lambda contracts, **kw: [])
    repo = MagicMock()
    repo.insert_scan_run.return_value = 7
    repo.upsert_option_chain_per_strike.return_value = 0

    F.refresh_ticker_chain(
        repo=repo,
        client=MagicMock(),
        ticker="AAPL",
        spot=Decimal("231.50"),
        market_date=date(2026, 8, 12),
    )

    assert "hit" not in called
    repo.upsert_options_volume_daily.assert_not_called()


def test_historical_close_lookup_returns_none_when_absent():
    repo = MagicMock()
    cur = repo.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    assert F.historical_close(repo, "AAPL", date(2026, 8, 12)) is None
