"""Integration test for src/uw_scan/scanners/vcg.py:run().

Seeds vol_index_daily (VIX / VVIX / HYG) with enough rows to clear
MIN_ALIGNED_BARS, runs the scanner, asserts a snapshot is persisted.
Also exercises the thin-data + zero-overlap early-return branches.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
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


def test_fetch_history_as_of_caps_the_window_not_just_the_tail(
    seeded_db_empty_cards,
) -> None:
    """`as_of` must be pushed into SQL, not applied after a recent-rows LIMIT.

    Regression: fetch_history took the most-recent `days` rows and vcg's
    _load_series filtered them to `<= as_of` afterwards. Any `as_of` further
    back than `days` bars then yielded an EMPTY series, so historical scans
    silently skipped with "thin data" and a deep backfill filled nothing.
    """
    repo = seeded_db_empty_cards
    vol_repo = VolIndexRepository(repo.conn, schema=repo._schema)

    start = date(2026, 1, 1)
    _seed(vol_repo, "VIX", [16.0 + i * 0.01 for i in range(300)], start=start)

    # Ask for a 50-bar window ending 200 bars back — far outside the most
    # recent 50 rows, which is exactly what the old code could not express.
    as_of = start + timedelta(days=100)
    rows = vol_repo.fetch_history("VIX", days=50, as_of=as_of)

    assert len(rows) == 50
    assert rows[-1]["trade_date"] == as_of
    assert all(r["trade_date"] <= as_of for r in rows)

    # …and the uncapped call is unchanged: still the most-recent rows.
    recent = vol_repo.fetch_history("VIX", days=50)
    assert recent[-1]["trade_date"] == start + timedelta(days=299)


def test_run_scores_a_historical_date_far_outside_the_recent_window(
    seeded_db_empty_cards,
) -> None:
    """A scan anchored well before the latest bar must still persist."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 800  # far more than the 300-bar LOOKBACK_DAYS the scanner requests
    start = date(2024, 1, 1)
    _seed(vol_repo, "VIX", [16.0 + 0.05 * (i % 7) for i in range(n)], start=start)
    _seed(vol_repo, "VVIX", [90.0 + 0.3 * (i % 11) for i in range(n)], start=start)
    _seed(
        vol_repo,
        "HYG",
        [80.0 - 0.002 * i + 0.05 * (i % 5) for i in range(n)],
        start=start,
    )

    # 150 bars in — clears MIN_ALIGNED_BARS (94) but sits ~650 bars before the
    # newest row, so the old recent-rows-then-filter path returned nothing.
    as_of = start + timedelta(days=150)
    row_id = vcg_scanner.run(conn, proxy="HYG", schema=repo._schema, as_of=as_of)

    assert row_id is not None
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data_date FROM {repo._schema}.vcg_snapshots WHERE id = %s",
            (row_id,),
        )
        assert cur.fetchone()[0] == as_of


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
