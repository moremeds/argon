from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

from uw_scan.storage.vol_index_repository import VolIndexRepository


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


def test_run_sync_empty_root_is_noop(tmp_path: Path, seeded_db_empty_cards) -> None:
    summary = run_vol_index_lake_sync(
        seeded_db_empty_cards.conn,
        root=tmp_path,
    )
    assert summary == {"symbols": 0, "rows": 0}
