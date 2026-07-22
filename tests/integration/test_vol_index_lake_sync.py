from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync


def _seed(root: Path, symbol: str, rows: list[dict]) -> None:
    d = root / f"symbol={symbol}"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), d / "1d.parquet")


def test_run_sync_inserts_all_symbols(tmp_path: Path, seeded_db_empty_cards) -> None:
    pg_conn = seeded_db_empty_cards.conn
    _seed(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 5, 14),
                "open": 17.5,
                "high": 18.0,
                "low": 17.2,
                "close": 17.8,
                "adj_close": 17.8,
                "volume": 0,
            },
        ],
    )
    _seed(
        tmp_path,
        "SPX",
        [
            {
                "trade_date": date(2026, 5, 14),
                "open": 7400,
                "high": 7450,
                "low": 7390,
                "close": 7430,
                "adj_close": 7430,
                "volume": 0,
            },
        ],
    )
    summary = run_vol_index_lake_sync(pg_conn, root=tmp_path)
    assert summary["symbols"] == 2
    assert summary["rows"] == 2
    repo = VolIndexRepository(pg_conn, schema="uw_scan")
    assert len(repo.fetch_history("VIX", days=5)) == 1
    assert len(repo.fetch_history("SPX", days=5)) == 1


def test_run_sync_incremental_refreshes_tail(
    tmp_path: Path, seeded_db_empty_cards
) -> None:
    """Incremental mode: re-upsert the latest row (in case its close changed
    intra-session) AND pull any strictly newer rows.

    Two-row return is the desired behavior — re-upsert is idempotent."""
    pg_conn = seeded_db_empty_cards.conn
    _seed(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 5, 14),
                "open": 17.5,
                "high": 18.0,
                "low": 17.2,
                "close": 17.8,
                "adj_close": 17.8,
                "volume": 0,
            },
        ],
    )
    run_vol_index_lake_sync(pg_conn, root=tmp_path)
    # Append a newer row plus same-day refresh
    _seed(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 5, 14),
                "open": 17.5,
                "high": 18.0,
                "low": 17.2,
                "close": 17.9,
                "adj_close": 17.9,
                "volume": 0,
            },
            {
                "trade_date": date(2026, 5, 15),
                "open": 18.07,
                "high": 19.27,
                "low": 17.8,
                "close": 18.43,
                "adj_close": 18.43,
                "volume": 0,
            },
        ],
    )
    summary = run_vol_index_lake_sync(pg_conn, root=tmp_path)
    assert summary["rows"] == 2  # latest re-upsert + new row
    repo = VolIndexRepository(pg_conn, schema="uw_scan")
    rows = repo.fetch_history("VIX", days=5)
    assert len(rows) == 2
    # Refreshed close took effect
    assert rows[0]["close"] == pytest.approx(17.9)


def test_run_sync_empty_root_raises(tmp_path: Path, seeded_db_empty_cards) -> None:
    """A mounted-but-empty lake is a broken mount, not a legitimate no-op.

    Before 2026-07-20 this returned {symbols: 0, ...} and was recorded as a job
    success — the exact behaviour that let the 2026-07-08 lake freeze look
    healthy for 13 days. It now raises so the scheduler records a job failure.
    """
    with pytest.raises(RuntimeError, match="mounted but empty"):
        run_vol_index_lake_sync(
            seeded_db_empty_cards.conn,
            root=tmp_path,
        )


def test_run_sync_fills_middle_gap(tmp_path: Path, seeded_db_empty_cards) -> None:
    """Gap-aware sync: if the DB has [05-13, 05-15] but R2 has [05-13, 05-14,
    05-15], the next run MUST pull 05-14 (a middle gap) into vol_index_daily.

    Defends against drift accumulated by a previous since-based sync that
    only ever caught up the tail. Regression test for the "what about 5/16
    and 5/17" follow-up — by extension, any internal hole that R2 covers.
    """
    pg_conn = seeded_db_empty_cards.conn
    repo = VolIndexRepository(pg_conn, schema="uw_scan")
    # Pre-seed the DB with two non-contiguous days for VIX — a hole on 05-14.
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 13),
                "open": 17.0,
                "high": 17.5,
                "low": 16.8,
                "close": 17.2,
                "adj_close": 17.2,
                "volume": 0,
            },
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 18.0,
                "high": 18.5,
                "low": 17.9,
                "close": 18.2,
                "adj_close": 18.2,
                "volume": 0,
            },
        ]
    )
    # R2-side fixture: three contiguous days including the missing 05-14.
    _seed(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 5, 13),
                "open": 17.0,
                "high": 17.5,
                "low": 16.8,
                "close": 17.2,
                "adj_close": 17.2,
                "volume": 0,
            },
            {
                "trade_date": date(2026, 5, 14),
                "open": 17.3,
                "high": 17.8,
                "low": 17.1,
                "close": 17.6,
                "adj_close": 17.6,
                "volume": 0,
            },
            {
                "trade_date": date(2026, 5, 15),
                "open": 18.0,
                "high": 18.5,
                "low": 17.9,
                "close": 18.2,
                "adj_close": 18.2,
                "volume": 0,
            },
        ],
    )

    summary = run_vol_index_lake_sync(pg_conn, root=tmp_path)

    # Expect 1 gap filled (05-14) plus latest re-upsert (05-15) → 2 rows.
    assert summary["gaps_filled"] == 1
    assert summary["rows"] == 2
    # And 05-14 now sits between the two existing rows.
    history = repo.fetch_history("VIX", days=10)
    dates = [r["trade_date"] for r in history]
    assert date(2026, 5, 14) in dates, f"middle gap not filled; dates={dates}"
    assert dates == sorted(dates), "history must be ascending after gap fill"
