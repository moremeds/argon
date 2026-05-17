"""Lake reader: parquet → list[dict] for vol_index_daily upserts."""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet


def _write_fixture(root: Path, symbol: str, rows: list[dict]) -> None:
    d = root / f"symbol={symbol}"
    d.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, d / "1d.parquet")


def test_read_vol_index_parquet_returns_rows(tmp_path: Path) -> None:
    _write_fixture(
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
    rows = read_vol_index_parquet(tmp_path, "VIX")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "VIX"
    assert rows[0]["trade_date"] == date(2026, 5, 14)
    assert rows[1]["close"] == pytest.approx(18.43)


def test_read_vol_index_parquet_since(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 5, 1),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "adj_close": 1,
                "volume": 0,
            },
            {
                "trade_date": date(2026, 5, 15),
                "open": 2,
                "high": 2,
                "low": 2,
                "close": 2,
                "adj_close": 2,
                "volume": 0,
            },
        ],
    )
    rows = read_vol_index_parquet(tmp_path, "VIX", since=date(2026, 5, 10))
    assert len(rows) == 1
    assert rows[0]["trade_date"] == date(2026, 5, 15)


def test_list_vol_index_symbols(tmp_path: Path) -> None:
    for sym in ["VIX", "VVIX", "SPX"]:
        (tmp_path / f"symbol={sym}").mkdir(parents=True)
        (tmp_path / f"symbol={sym}" / "1d.parquet").touch()
    syms = list_vol_index_symbols(tmp_path)
    assert set(syms) == {"VIX", "VVIX", "SPX"}


def test_read_missing_symbol_returns_empty(tmp_path: Path) -> None:
    assert read_vol_index_parquet(tmp_path, "NONEXISTENT") == []
