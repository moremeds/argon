"""Integration test for src/uw_scan/scanners/vcg.py:run().

Seeds vol_index_daily (VIX / VVIX / HYG) with enough rows to clear
MIN_ALIGNED_BARS, runs the scanner, asserts a snapshot is persisted.
Also exercises the thin-data + zero-overlap early-return branches.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository

from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.vol_index_repository import VolIndexRepository


def _seed(
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


def test_run_persists_snapshot_when_data_is_sufficient(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 120  # > MIN_ALIGNED_BARS (94)
    start = date(2026, 1, 1)
    # Slightly drifting VIX/VVIX so log-returns are non-trivial; HYG ticks
    # down so credit returns are non-zero and the OLS regression converges.
    _seed(vol_repo, "VIX", [16.0 + 0.05 * (i % 7) for i in range(n)], start=start)
    _seed(vol_repo, "VVIX", [90.0 + 0.3 * (i % 11) for i in range(n)], start=start)
    _seed(
        vol_repo,
        "HYG",
        [80.0 - 0.02 * i + 0.05 * (i % 5) for i in range(n)],
        start=start,
    )

    row_id = vcg_scanner.run(conn, proxy="HYG", schema=repo._schema)
    assert row_id is not None
    assert row_id > 0

    snap_repo = VcgSnapshotRepository(conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    assert latest is not None
    sig = latest["signal"]
    # vcg may be NaN at the very edge; assert structural keys
    assert latest["credit_proxy"] == "HYG"
    assert "vcg" in sig
    assert "interpretation" in sig
    assert sig["interpretation"] in {
        "INSUFFICIENT_DATA",
        "NORMAL",
        "WATCH",
        "RISK_OFF",
        "EDR",
        "BOUNCE",
        "SUPPRESSED",
        "PANIC",
    }
    assert sig["ro"] in (0, 1)
    assert sig["edr"] in (0, 1)
    assert sig["bounce"] in (0, 1)
    # Quiet seeded vol → no RO / EDR / Bounce
    assert sig["ro"] == 0
    assert sig["edr"] == 0
    assert sig["bounce"] == 0
    # 20-session rolling history
    assert isinstance(latest["history"], list)
    assert len(latest["history"]) == 20
    last = latest["history"][-1]
    assert {"date", "vcg", "vcg_adj", "vix", "vvix", "credit"} <= set(last)
    if last["vcg"] is not None:
        assert math.isfinite(last["vcg"])


def test_run_returns_none_when_data_is_thin(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 50  # << MIN_ALIGNED_BARS (94)
    start = date(2026, 1, 1)
    _seed(vol_repo, "VIX", [16.0] * n, start=start)
    _seed(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed(vol_repo, "HYG", [80.0] * n, start=start)

    assert vcg_scanner.run(conn, proxy="HYG", schema=repo._schema) is None

    snap_repo = VcgSnapshotRepository(conn, schema=repo._schema)
    assert snap_repo.fetch_latest() is None


def test_run_returns_none_when_no_overlap(seeded_db_empty_cards) -> None:
    """VIX dates and HYG dates don't intersect → 0 aligned bars."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    _seed(vol_repo, "VIX", [16.0] * 120, start=date(2026, 1, 1))
    _seed(vol_repo, "VVIX", [95.0] * 120, start=date(2026, 1, 1))
    # HYG starts a year later → zero overlap with vol series
    _seed(vol_repo, "HYG", [80.0] * 120, start=date(2027, 1, 1))

    assert vcg_scanner.run(conn, proxy="HYG", schema=repo._schema) is None
