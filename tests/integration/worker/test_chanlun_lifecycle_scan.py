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


def test_scan_sweeps_superseded_mark_to_invalidated(seeded_db_empty_cards):
    """A non-terminal mark present in the DB but absent from a fresh recompute
    must be swept to invalidated/reason='superseded' (chanlun_lifecycle.py
    ~169-192), so `current_states` never carries a stale pending/
    confirmed_sublevel row for a mark that dropped out of the daily
    structure."""
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)
    cs_repo = ChanlunSignalRepository(repo.conn, schema=repo._schema)

    # Baseline scan derives the real marks from the golden AAPL fixture.
    first = chanlun_lifecycle_scan(
        repo,
        Settings.from_env(),
        ticker_filter=["AAPL"],
        fetch_bars=_stub_fetch,
        now=now,
    )
    assert first["ok"] == 1

    # Seed a `pending` row for a mark key the fixture's recompute never
    # derives (2020-01-01 predates the fixture's bar window, which starts
    # 2024-07-12 -- see _GOLDEN["bars"][0]). Real category/kind ("vertex"/
    # "top") so the sweep's downstream plumbing (is_promotable etc.) sees
    # ordinary values; only the key is fake.
    fake_extreme_date = dt.date(2020, 1, 1)
    fake_extreme_price = 999.99
    cs_repo.upsert_transition(
        ticker="AAPL",
        category="vertex",
        kind="top",
        extreme_date=fake_extreme_date,
        extreme_price=fake_extreme_price,
        state="pending",
        reason=None,
        as_of=dt.date(2026, 7, 12),
        details={},
    )

    def _fake_row(states):
        return next(
            (
                s
                for s in states
                if s["category"] == "vertex"
                and s["kind"] == "top"
                and s["extreme_date"] == fake_extreme_date
                and s["extreme_price"] == fake_extreme_price
            ),
            None,
        )

    # Non-vacuity: the seed took effect as `pending` before the sweep runs.
    seeded = _fake_row(cs_repo.current_states("AAPL"))
    assert seeded is not None
    assert seeded["state"] == "pending"

    # Re-run: the fake key is absent from derived_keys on the fresh
    # recompute, so the sweep must invalidate it with reason='superseded'.
    second = chanlun_lifecycle_scan(
        repo,
        Settings.from_env(),
        ticker_filter=["AAPL"],
        fetch_bars=_stub_fetch,
        now=now,
    )
    assert second["ok"] == 1

    swept = _fake_row(cs_repo.current_states("AAPL"))
    assert swept is not None
    assert swept["state"] == "invalidated"
    assert swept["reason"] == "superseded"
