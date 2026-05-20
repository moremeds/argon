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


def test_cri_scanner_emits_new_payload_fields(seeded_db_empty_cards) -> None:
    """vvix_5d_roc + cor1m_5d_change must appear in the persisted snapshot so
    the UI can compute prior-day component dots without falling back to 0."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_spy(repo, [450.0 + i * (150.0 / n) for i in range(n)], start=start)

    cri_scanner.run(conn, schema=repo._schema)
    snap_repo = CriSnapshotRepository(conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    assert latest is not None

    assert "vvix_5d_roc" in latest, "top-level vvix_5d_roc missing"
    assert latest["history"], "history is empty — fixture broke"
    last_row = latest["history"][-1]
    assert "vvix_5d_roc" in last_row, "per-row vvix_5d_roc missing"
    assert "cor1m_5d_change" in last_row, "per-row cor1m_5d_change missing"


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


def test_run_uses_spx_when_available(seeded_db_empty_cards) -> None:
    """Scanner should load SPX from vol_index_daily when present."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # Seed SPX (NOT SPY) — the scanner must find it
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None

    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPX"
    # spy field carries SPX-scale value
    assert snap["spy"] > 4000


def test_run_falls_back_to_spy_when_spx_missing(seeded_db_empty_cards) -> None:
    """Scanner should still work with SPY-only seed (back-compat)."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # No SPX seeded; SPY is the only price source
    _seed_spy(repo, [450.0 + i * (150.0 / n) for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None

    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPY"


def test_run_persists_snapshot_when_vix3m_is_completely_missing(
    seeded_db_empty_cards,
) -> None:
    """No VIX3M at all → snapshot still writes; vix3m/ratio fields are null."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)
    # Deliberately no VIX3M seed.
    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["vix3m"] is None
    assert snap["vix_vix3m_ratio"] is None
    # VRP doesn't depend on VIX3M, so it should still be populated.
    assert snap["vrp"] is not None


def test_run_persists_snapshot_when_vix3m_is_stale(seeded_db_empty_cards) -> None:
    """VIX3M ends well before CRI snapshot date → vix3m=None, scan still succeeds."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)
    # VIX3M only for the first 100 days — stale by the time we scan.
    _seed_vol(vol_repo, "VIX3M", [21.0] * 100, start=start)
    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    # The "today" date is day 140 — VIX3M has no entry there.
    assert snap["vix3m"] is None


def test_run_persists_mean_reversion_fields(seeded_db_empty_cards) -> None:
    """Full VIX3M coverage → vix3m, vrp, vix_vix3m_ratio all populated."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [18.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "VIX3M", [21.0] * n, start=start)
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)

    cri_scanner.run(conn, schema=repo._schema)
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["vix3m"] == 21.0
    assert snap["vrp"] is not None
    assert snap["vix_vix3m_ratio"] is not None
    assert snap["vix_vix3m_ratio"] < 1.0  # 18/21 = 0.857 → contango


def test_run_falls_back_to_spy_when_spx_alignment_too_thin(
    seeded_db_empty_cards,
) -> None:
    """SPX present but only 5 overlapping bars — must retry SPY before skipping."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # SPX has only 5 days at the END of the range — overlap is 5 bars,
    # well below MIN_ALIGNED_BARS.
    _seed_vol(vol_repo, "SPX", [4500.0] * 5, start=date(2026, 5, 16))
    # SPY has the full range — fallback should succeed.
    _seed_spy(repo, [450.0 + i * 0.1 for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPY"
