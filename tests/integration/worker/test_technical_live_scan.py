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
