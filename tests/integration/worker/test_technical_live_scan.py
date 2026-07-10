from __future__ import annotations

import datetime as dt
from decimal import Decimal

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import build_technical_series
from uw_scan.config import Settings
from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
from uw_scan.storage.technicals_repository import (
    TechnicalsRepository,
    series_records,
)
from uw_scan.worker.jobs.technical_live import technical_live_scan


def _seed_daily(repo, ticker: str, n: int = 420) -> float:
    """Seed n sessions of technical_daily for `ticker`; return the last close."""
    close = 100.0 + np.cumsum(np.random.default_rng(11).normal(0.05, 1.0, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    bars = [
        {
            "time": t.isoformat(),
            "open": float(c),
            "high": float(c) + 1,
            "low": float(c) - 1,
            "close": float(c),
            "volume": 1_000.0,
        }
        for t, c in zip(idx, close)
    ]
    df = build_technical_series(bars)
    TechnicalsRepository(repo.conn, schema=repo._schema).upsert_series(
        ticker, series_records(df)
    )
    return float(close[-1])


def test_scan_writes_cache_row(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    last_close = _seed_daily(repo, "NVDA")
    now = dt.datetime(2026, 7, 9, 19, 0, tzinfo=dt.timezone.utc)
    repo.upsert_intraday_quote(
        "NVDA",
        Decimal(str(round(last_close + 3.0, 2))),
        now - dt.timedelta(seconds=30),
        source="xenon_ws",
    )
    summary = technical_live_scan(
        repo, Settings.from_env(), ticker_filter=["NVDA"], now=now
    )
    assert summary["ok"] == 1
    got = TechnicalLiveRepository(repo.conn, schema=repo._schema).fetch("NVDA")
    assert got is not None
    assert got["spot_source"] == "xenon_ws"
    assert "dual_macd" in got["payload"]


def test_stale_quote_skipped(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    last_close = _seed_daily(repo, "NVDA")
    now = dt.datetime(2026, 7, 9, 19, 0, tzinfo=dt.timezone.utc)
    repo.upsert_intraday_quote(
        "NVDA",
        Decimal(str(round(last_close, 2))),
        now - dt.timedelta(seconds=3600),
        source="xenon_ws",  # 1h old > 900s
    )
    summary = technical_live_scan(
        repo, Settings.from_env(), ticker_filter=["NVDA"], now=now
    )
    assert summary["skipped_stale"] == 1 and summary["ok"] == 0


def _seed_dates_closes(repo, ticker, dates, closes):
    bars = [
        {
            "time": pd.Timestamp(d, tz="UTC").isoformat(),
            "open": float(c),
            "high": float(c) + 1,
            "low": float(c) - 1,
            "close": float(c),
            "volume": 1_000.0,
        }
        for d, c in zip(dates, closes)
    ]
    df = build_technical_series(bars)
    TechnicalsRepository(repo.conn, schema=repo._schema).upsert_series(
        ticker, series_records(df)
    )


def test_live_splice_replaces_today_bar_not_appends(seeded_db_empty_cards):
    # When technical_daily already holds today's EOD close (e.g. after the 18:40
    # nightly refresh), the live splice must REPLACE it with the live spot, not
    # stack a second today bar. Invariant: the live reading is identical whether
    # or not today's EOD row is already present in history.
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    now = dt.datetime(2026, 7, 9, 21, 0, tzinfo=dt.timezone.utc)  # ET date 2026-07-09
    spot = 150.0
    n = 421
    dates = pd.bdate_range(end="2026-07-09", periods=n)  # last == today (ET)
    rng = np.random.default_rng(7)
    closes = 100.0 + np.cumsum(rng.normal(0.05, 1.0, n))
    closes[-1] = spot  # today's EOD close == the live spot we will splice

    # A: history ends YESTERDAY (drop today's row) → splice appends spot.
    _seed_dates_closes(repo, "AAA", dates[:-1], closes[:-1])
    # B: history ends TODAY (row present) → splice must replace it.
    _seed_dates_closes(repo, "BBB", dates, closes)
    for t in ("AAA", "BBB"):
        repo.upsert_intraday_quote(
            t, Decimal("150.00"), now - dt.timedelta(seconds=30), source="xenon_ws"
        )
    technical_live_scan(repo, settings, ticker_filter=["AAA", "BBB"], now=now)

    live = TechnicalLiveRepository(repo.conn, schema=repo._schema)
    a = live.fetch("AAA")["payload"]
    b = live.fetch("BBB")["payload"]
    assert a["z"] == b["z"]
    assert a["dual_macd"] == b["dual_macd"]
