from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from uw_scan.config import Settings
from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository
from uw_scan.worker.jobs.chanlun_lifecycle import chanlun_lifecycle_scan

_GOLDEN = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "web/tests/lib/fixtures/chanlunGoldenAapl.json"
    ).read_text()
)


def _stub_fetch(ticker, timeframe, start, *, end=None, limit=0, **kw):
    if timeframe == "1d":
        # Real frozen AAPL daily bars (open synthesized as close so the split
        # guard has a value; guard only trips on >1.5x gaps, which these lack).
        return [
            {
                "time": b["time"],
                "open": b["close"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": 0,
                "vwap": None,
            }
            for b in _GOLDEN["bars"]
        ]
    return []  # no 30m -> no sublevel promotion, marks stay PENDING/NATIVE


def _seed_watchlist(repo, ticker="AAPL"):
    # Minimal watchlist row so list_watchlist_cards() yields the ticker. Reuse
    # whatever the harness's card-seed helper is; if list_watchlist_cards is
    # empty, pass ticker_filter=["AAPL"] instead (below uses ticker_filter).
    return ticker


def test_scan_derives_and_persists_marks(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)  # 03:10 ET
    summary = chanlun_lifecycle_scan(
        repo,
        Settings.from_env(),
        ticker_filter=["AAPL"],
        fetch_bars=_stub_fetch,
        now=now,
    )
    assert summary["ok"] == 1
    assert summary["failed"] == 0
    assert summary["transitions"] > 0  # non-vacuity: real bars produce marks
    states = ChanlunSignalRepository(repo.conn, schema=repo._schema).current_states(
        "AAPL"
    )
    assert len(states) > 0
    # Every persisted state is a legal value.
    assert all(
        s["state"]
        in {"pending", "confirmed_sublevel", "confirmed_native", "invalidated"}
        for s in states
    )
    # No sublevel promotions possible with empty 30m feed.
    assert all(s["state"] != "confirmed_sublevel" for s in states)


def test_scan_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)
    kw = dict(ticker_filter=["AAPL"], fetch_bars=_stub_fetch, now=now)
    first = chanlun_lifecycle_scan(repo, Settings.from_env(), **kw)
    second = chanlun_lifecycle_scan(repo, Settings.from_env(), **kw)
    assert first["transitions"] > 0
    assert second["transitions"] == 0  # re-run over same bars is a no-op


def test_scan_counts_apex_outage(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)
    summary = chanlun_lifecycle_scan(
        repo,
        Settings.from_env(),
        ticker_filter=["AAPL"],
        fetch_bars=lambda *a, **k: [],
        now=now,  # apex down -> [] for everything
    )
    assert summary["skipped_no_bars"] == 1
    assert summary["ok"] == 0
