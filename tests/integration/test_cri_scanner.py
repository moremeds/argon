"""Integration test for src/uw_scan/scanners/cri.py:run().

Seeds vol_index_daily (VIX/VVIX/COR1M) + daily_ohlc (SPY) with enough rows
to clear MIN_ALIGNED_BARS, runs the scanner, asserts a snapshot is persisted.
Also exercises the thin-data early-return branch.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from uw_scan.scanners import cri as cri_scanner
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository


def _seed_vol(
    vol_repo: VolIndexRepository,
    symbol: str,
    values: list[float],
    *,
    start: date,
) -> None:
    rows = []
    for i, v in enumerate(values):
        rows.append(
            {
                "symbol": symbol,
                "trade_date": start + timedelta(days=i),
                "open": v,
                "high": v,
                "low": v,
                "close": v,
                "adj_close": v,
                "volume": 0,
            }
        )
    vol_repo.upsert_rows(rows)


def _seed_spy(repo, closes: list[float], *, start: date) -> None:
    for i, px in enumerate(closes):
        repo.upsert_daily_ohlc(
            ticker="SPY",
            date=start + timedelta(days=i),
            open=Decimal(str(px)),
            high=Decimal(str(px)),
            low=Decimal(str(px)),
            close=Decimal(str(px)),
            volume=0,
            source="massive.com",
        )


def test_run_persists_snapshot_when_data_is_sufficient(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140  # > MIN_ALIGNED_BARS (120)
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    spy_closes = [450.0 + i * (150.0 / n) for i in range(n)]  # trending up
    _seed_spy(repo, spy_closes, start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    assert row_id > 0

    snap_repo = CriSnapshotRepository(conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    assert latest is not None
    score = latest["cri"]["score"]
    assert math.isfinite(score)
    assert 0.0 <= score <= 100.0
    assert latest["cri"]["level"] in {"LOW", "ELEVATED", "HIGH", "CRITICAL"}
    # Calm market should land in LOW or ELEVATED
    assert latest["cri"]["level"] in {"LOW", "ELEVATED"}
    # Crash trigger is off on calm data
    assert latest["crash_trigger"]["fired"] is False
    assert math.isfinite(latest["vix"])
    assert latest["vix"] == 16.0


def test_run_returns_none_when_data_is_thin(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 30  # << MIN_ALIGNED_BARS (120)
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_spy(repo, [500.0 + i for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is None

    snap_repo = CriSnapshotRepository(conn, schema=repo._schema)
    assert snap_repo.fetch_latest() is None


def test_run_returns_none_when_no_overlap(seeded_db_empty_cards) -> None:
    """VIX dates and SPY dates don't intersect → 0 aligned bars."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    _seed_vol(vol_repo, "VIX", [16.0] * 140, start=date(2026, 1, 1))
    _seed_vol(vol_repo, "VVIX", [95.0] * 140, start=date(2026, 1, 1))
    _seed_vol(vol_repo, "COR1M", [20.0] * 140, start=date(2026, 1, 1))
    # SPY starts a year later — zero overlap with vol series
    _seed_spy(repo, [500.0 + i for i in range(140)], start=date(2027, 1, 1))

    assert cri_scanner.run(conn, schema=repo._schema) is None
