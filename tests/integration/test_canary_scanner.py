"""Integration tests for src/uw_scan/scanners/canary.py series loading."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.scanners import canary as canary_scanner
from uw_scan.storage.vol_index_repository import VolIndexRepository


def _seed_vol(
    vol_repo: VolIndexRepository,
    symbol: str,
    values: list[float],
    *,
    start: date,
) -> None:
    vol_repo.upsert_rows(
        [
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
            for i, v in enumerate(values)
        ]
    )


def test_load_honours_an_as_of_far_outside_the_recent_window(
    seeded_db_empty_cards,
) -> None:
    """`as_of` must be pushed into SQL, not applied after a recent-rows LIMIT.

    Regression: `_load` fetched the most-recent `days * 2` rows and only then
    filtered them to `<= as_of`. That anchors the fetch window to today while
    anchoring the filter to `as_of` — so any `as_of` further back than the
    window drops every row and yields an EMPTY series. The caller reads that as
    thin data and skips, so a deep historical backfill reports success while
    writing nothing. CRI carried the identical copy-pasted bug.
    """
    repo = seeded_db_empty_cards
    vol_repo = VolIndexRepository(repo.conn, schema=repo._schema)

    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0 + i * 0.01 for i in range(400)], start=start)

    # 200 bars back — comfortably outside the old `days * 2` fudge buffer.
    as_of = start + timedelta(days=200)
    series = canary_scanner._load(vol_repo, "VIX", 100, as_of=as_of)

    assert len(series) == 100, "empty/short series is the bug this guards"
    assert max(series) == as_of
    assert all(d <= as_of for d in series)

    # The uncapped path is unchanged: still the most-recent rows.
    latest = canary_scanner._load(vol_repo, "VIX", 100)
    assert max(latest) == start + timedelta(days=399)
