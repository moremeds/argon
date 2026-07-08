"""technical_daily_refresh — real DB, apex fetch monkeypatched."""

from __future__ import annotations

import pandas as pd

from uw_scan.storage.technicals_repository import TechnicalsRepository
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh


def _fake_bars(n: int = 300, drift: float = 1.0008) -> list[dict]:
    out = []
    for i in range(n):
        ts = (pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(days=i)).isoformat()
        c = 100.0 * (drift**i)
        out.append(
            {
                "time": ts,
                "open": c,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "volume": 1000,
                "vwap": None,
            }
        )
    return out


def _settings():
    from tests.integration.conftest import _test_settings

    return _test_settings()


def test_refresh_writes_series_and_latest_detail(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    bars = _fake_bars(400)
    monkeypatch.setattr(
        "uw_scan.worker.jobs.technical_daily_refresh.fetch_daily_bars",
        lambda t, **kw: bars,
    )
    result = technical_daily_refresh(
        repo=repo, settings=_settings(), ticker_filter=["NVDA"]
    )
    assert result["ok"] == 2  # NVDA + SPY (benchmark always refreshed)
    trepo = TechnicalsRepository(repo.conn)
    latest = trepo.fetch_latest("NVDA")
    assert latest is not None
    assert latest["detail"] is not None
    assert latest["forward_returns"]
    assert len(trepo.fetch_series("NVDA")) == 400


def test_refresh_skips_thin_history_and_survives_fetch_failure(
    seeded_db_empty_cards, monkeypatch
):
    repo = seeded_db_empty_cards
    thin = _fake_bars(100)

    def fake_fetch(t, **kw):
        if t == "BOOM":
            raise RuntimeError("apex down")
        return thin

    monkeypatch.setattr(
        "uw_scan.worker.jobs.technical_daily_refresh.fetch_daily_bars", fake_fetch
    )
    result = technical_daily_refresh(
        repo=repo, settings=_settings(), ticker_filter=["NVDA", "BOOM"]
    )
    assert result["failed"] == 1  # BOOM logged, loop continued
    assert result["skipped_thin"] >= 1  # 100 bars < 210 floor
    assert TechnicalsRepository(repo.conn).fetch_latest("NVDA") is None
