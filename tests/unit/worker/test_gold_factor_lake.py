"""gold_factor lake read: completed bars only, stale-leg detection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from uw_scan.worker.jobs.gold_factor import expected_bar, read_lake_legs, stale_legs

# Real livewire lake closes (IB 1-day MIDPOINT), read on the mini 2026-10-15 from
# bronze/asset_class={cmdty,fx_ib}/symbol=<LEG>/1d.parquet.
DATES = [date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)]
CLOSES = {
    "XAUUSD": [4193.87, 4171.88, 4161.51, 4105.57],
    "EURUSD": [1.12, 1.11555, 1.11985, 1.11565],
    "USDJPY": [158.3135, 158.608, 158.332, 158.3245],
    "GBPUSD": [1.3238, 1.3208, 1.3255, 1.31935],
    "USDCAD": [1.42575, 1.42815, 1.4216, 1.42385],
    "USDSEK": [9.99625, 10.04025, 9.9647, 10.0245],
    "USDCHF": [0.83015, 0.8347, 0.8326, 0.83495],
}


def _lake(root: Path, upto: int = 4, drop: str | None = None) -> Path:
    for leg, closes in CLOSES.items():
        if leg == drop:
            continue
        ac = "cmdty" if leg == "XAUUSD" else "fx_ib"
        d = root / "bronze" / f"asset_class={ac}" / f"symbol={leg}"
        d.mkdir(parents=True, exist_ok=True)
        t = pa.table(
            {"trade_date": pa.array(DATES[:upto], pa.date32()), "close": closes[:upto]}
        )
        pq.write_table(t, d / "1d.parquet")
    return root


# 2026-10-14 is a Wednesday; EDT, so 17:00 New York = 21:00Z.
BEFORE_CLOSE = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)  # 16:30 New York
AFTER_CLOSE = datetime(
    2026, 10, 14, 21, 50, tzinfo=UTC
)  # 17:50 New York, the job's slot


def test_bar_still_forming_is_dropped(tmp_path: Path) -> None:
    legs = read_lake_legs(_lake(tmp_path), BEFORE_CLOSE)
    assert legs.index[-1].date() == date(2026, 10, 13)
    assert legs.loc["2026-10-13", "XAUUSD"] == 4161.51
    assert read_lake_legs(tmp_path, AFTER_CLOSE).loc["2026-10-14", "XAUUSD"] == 4105.57


def test_expected_bar_walks_back_over_weekend() -> None:
    assert expected_bar(AFTER_CLOSE) == date(2026, 10, 14)
    assert expected_bar(BEFORE_CLOSE) == date(2026, 10, 13)
    sunday_evening = datetime(2026, 10, 18, 21, 50, tzinfo=UTC)
    assert expected_bar(sunday_evening) == date(2026, 10, 16)


def test_stale_and_missing_legs_are_named(tmp_path: Path) -> None:
    assert stale_legs(read_lake_legs(_lake(tmp_path), AFTER_CLOSE), AFTER_CLOSE) == []
    old = read_lake_legs(_lake(tmp_path / "old", upto=3, drop="USDSEK"), AFTER_CLOSE)
    stale = stale_legs(old, AFTER_CLOSE)
    assert len(stale) == 7
    assert stale[-2] == "USDSEK: last lake bar None, expected 2026-10-14"
    assert stale[0] == "XAUUSD: last lake bar 2026-10-13, expected 2026-10-14"
