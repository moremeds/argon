"""Regression: _lake_spot must read the explicit 1d.parquet file, not the
whole symbol directory — a sibling .lock marker (or 30m/5m parquet) in that
directory breaks pyarrow's directory-dataset reader with a zero-byte-file
ArrowInvalid, which is exactly what silently starved QQQ/IWM's macro
short-vol signal for weeks (2026-07-22).
"""

from __future__ import annotations

from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from uw_scan.reports.vrp_macro_drawdown import _lake_spot


def test_lake_spot_ignores_lock_and_other_timeframe_files(tmp_path):
    symbol_dir = tmp_path / "bronze" / "asset_class=equity" / "symbol=QQQ"
    symbol_dir.mkdir(parents=True)

    table = pa.table(
        {
            "trade_date": [date(2026, 7, 20), date(2026, 7, 21)],
            "close": [500.0, 501.5],
        }
    )
    pq.write_table(table, symbol_dir / "1d.parquet")

    # Zero-byte lock marker + an unrelated-timeframe parquet, exactly like the
    # real lake layout — must not be picked up by the reader.
    (symbol_dir / "1d.parquet.lock").touch()
    pq.write_table(
        pa.table({"trade_date": [date(2026, 7, 21)], "close": [500.9]}),
        symbol_dir / "30m.parquet",
    )

    result = _lake_spot("QQQ", tmp_path, date(2026, 7, 1))

    assert result == {date(2026, 7, 20): 500.0, date(2026, 7, 21): 501.5}
