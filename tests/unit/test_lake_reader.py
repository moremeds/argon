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


def test_read_does_not_require_pandas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for issue #122: the nightly vol_index_lake_sync crashed with
    ModuleNotFoundError('pyarrow.pandas_compat') when pandas drifted out of
    the worker venv. The reader must stay pyarrow-native so a pandas-less
    environment can still sync the lake."""
    import builtins
    import sys

    _write_fixture(
        tmp_path,
        "VIX",
        [
            {
                "trade_date": date(2026, 6, 9),
                "open": 20.0,
                "high": 21.0,
                "low": 19.5,
                "close": 20.5,
                "adj_close": 20.5,
                "volume": 0,
            },
        ],
    )

    for mod in [m for m in sys.modules if m == "pandas" or m.startswith("pandas.")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.delitem(sys.modules, "pyarrow.pandas_compat", raising=False)

    real_import = builtins.__import__

    def _no_pandas(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise ModuleNotFoundError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pandas)

    rows = read_vol_index_parquet(tmp_path, "VIX")
    assert len(rows) == 1
    assert rows[0]["trade_date"] == date(2026, 6, 9)
    assert rows[0]["close"] == pytest.approx(20.5)


def test_missing_lake_root_raises(tmp_path: Path) -> None:
    """A configured-but-absent root is a misconfiguration, not 'no data'.

    Returning [] here is what turned the 2026-07-08 missing container mount
    into 13 days of silent staleness instead of a first-run crash.
    """
    absent = tmp_path / "not-mounted"
    with pytest.raises(FileNotFoundError, match="lake root does not exist"):
        read_vol_index_parquet(absent, "VIX")
    with pytest.raises(FileNotFoundError, match="lake root does not exist"):
        list_vol_index_symbols(absent)


def test_present_root_missing_symbol_still_returns_empty(tmp_path: Path) -> None:
    """A symbol may legitimately not exist under a healthy root."""
    assert read_vol_index_parquet(tmp_path, "NONEXISTENT") == []


def test_sync_raises_on_present_but_empty_lake(tmp_path: Path) -> None:
    """A mounted-but-empty lake is a broken mount, not 'no new rows'."""
    from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

    with pytest.raises(RuntimeError, match="mounted but empty"):
        run_vol_index_lake_sync(None, root=tmp_path)
