"""apply_record_health_thresholds — pure watchlist-coverage math."""

from __future__ import annotations

from datetime import UTC, datetime

from uw_scan.storage.health import apply_record_health_thresholds
from uw_scan.storage.rows import RecordHealthRawRow

_WINDOW = datetime(2026, 9, 24, 13, 0, tzinfo=UTC)


def _raw(table: str, rows: int, tickers: int) -> RecordHealthRawRow:
    return RecordHealthRawRow(
        table=table,
        window_start=_WINDOW,
        actual_rows=rows,
        actual_tickers=tickers,
        latest_at=None,
    )


def test_threshold_is_ceil_of_watchlist_times_coverage() -> None:
    [row] = apply_record_health_thresholds(
        [_raw("greeks_by_expiry_strike", rows=5000, tickers=169)],
        expected_tickers=187,
        min_coverage=0.9,
    )
    assert row.expected_min_tickers == 169  # ceil(187 * 0.9) = ceil(168.3)
    assert row.expected_min_rows == 169
    assert row.ok is True


def test_one_ticker_short_fails() -> None:
    [row] = apply_record_health_thresholds(
        [_raw("greeks_by_expiry_strike", rows=5000, tickers=168)],
        expected_tickers=187,
        min_coverage=0.9,
    )
    assert row.ok is False


def test_rows_below_one_per_required_ticker_fails() -> None:
    [row] = apply_record_health_thresholds(
        [_raw("watchlist_card", rows=10, tickers=20)],
        expected_tickers=20,
        min_coverage=1.0,
    )
    assert row.ok is False


def test_empty_watchlist_or_zero_coverage_passes_everything() -> None:
    for expected, coverage in ((0, 0.9), (187, 0.0)):
        [row] = apply_record_health_thresholds(
            [_raw("t", rows=0, tickers=0)],
            expected_tickers=expected,
            min_coverage=coverage,
        )
        assert row.expected_min_tickers == 0
        assert row.ok is True


def test_raw_fields_carried_through() -> None:
    raw = _raw("oi_by_strike", rows=7, tickers=3)
    [row] = apply_record_health_thresholds([raw], expected_tickers=3, min_coverage=1)
    assert (row.table, row.window_start, row.actual_rows, row.actual_tickers) == (
        "oi_by_strike",
        _WINDOW,
        7,
        3,
    )
    assert row.expected_tickers == 3
