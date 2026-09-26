"""/api/health record-health read path over the persisted snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from uw_scan.api.routers.health import _snapshot_record_health
from uw_scan.storage.rows import RecordHealthRawRow

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


class _Repo:
    def __init__(self, rows: list[RecordHealthRawRow]) -> None:
        self._rows = rows
        self.requested: list[list[str] | None] = []

    def list_record_health_snapshot(self, tables=None):
        self.requested.append(tables)
        if tables is None:
            return list(self._rows)
        return [row for row in self._rows if row.table in tables]


def _row(table: str, tickers: int, computed_ago: timedelta) -> RecordHealthRawRow:
    return RecordHealthRawRow(
        table=table,
        window_start=NOW - timedelta(hours=8),
        actual_rows=tickers * 10,
        actual_tickers=tickers,
        latest_at=NOW - timedelta(minutes=3),
        computed_at=NOW - computed_ago,
    )


def _call(repo, *, tables=None, coverage=0.9, watchlist=100):
    return _snapshot_record_health(
        repo,
        now_utc=NOW,
        watchlist_size=watchlist,
        selected_tables=tables,
        min_coverage=coverage,
    )


def test_missing_snapshot_reads_unknown_not_pass() -> None:
    fields, reason, note = _call(_Repo([]))
    assert fields["record_health_ok"] is None
    assert fields["record_health"] == []
    assert fields["record_health_computed_at"] is None
    assert reason is None
    assert note == "record health snapshot stale/missing"


def test_stale_snapshot_reads_unknown_even_when_counts_would_pass() -> None:
    fields, reason, note = _call(
        _Repo([_row("watchlist_card", 100, timedelta(minutes=46))])
    )
    assert fields["record_health_ok"] is None
    assert fields["record_health"] == []
    assert fields["record_health_computed_at"] == NOW - timedelta(minutes=46)
    assert reason is None
    assert note == "record health snapshot stale/missing"


def test_fresh_snapshot_applies_request_coverage_and_watchlist_size() -> None:
    repo = _Repo(
        [
            _row("greeks_by_expiry_strike", 95, timedelta(minutes=10)),
            _row("watchlist_card", 80, timedelta(minutes=2)),
        ]
    )
    fields, reason, note = _call(repo, coverage=0.9)
    assert fields["record_health_ok"] is False
    assert reason == "record coverage below expected: watchlist_card"
    assert note is None
    assert fields["record_health_computed_at"] == NOW - timedelta(minutes=10)
    by_table = {check.table: check for check in fields["record_health"]}
    assert by_table["greeks_by_expiry_strike"].ok is True
    assert by_table["watchlist_card"].expected_min_tickers == 90

    # Same snapshot, looser request threshold: thresholds are read-time.
    fields, reason, _ = _call(repo, coverage=0.8)
    assert fields["record_health_ok"] is True
    assert reason is None


def test_selected_tables_are_passed_through_and_unknown_is_400() -> None:
    repo = _Repo([_row("watchlist_card", 100, timedelta(minutes=1))])
    fields, _, _ = _call(repo, tables=["watchlist_card"])
    assert repo.requested[-1] == ["watchlist_card"]
    assert [check.table for check in fields["record_health"]] == ["watchlist_card"]

    with pytest.raises(HTTPException) as exc:
        _call(repo, tables=["watchlist_card", "no_such_table"])
    assert exc.value.status_code == 400
    assert "no_such_table" in exc.value.detail
