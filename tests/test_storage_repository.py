from uw_scan.fixtures import demo_dashboard
from datetime import datetime, timezone

from uw_scan.storage.repository import (
    apply_migrations,
    list_migration_files,
    list_snapshot_summaries,
    load_dashboard_snapshot,
    save_dashboard_snapshot,
)


class _FakeCursor:
    def __init__(self, calls, rows=None):
        self.calls = calls
        self.rows = rows or []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, rows=None):
        self.calls = []
        self.commits = 0
        self.rows = rows or []

    def cursor(self):
        return _FakeCursor(self.calls, self.rows)

    def commit(self):
        self.commits += 1


def test_list_migration_files_returns_ordered_sql_files():
    names = [path.name for path in list_migration_files()]

    assert names[:2] == ["001_create_uw_scan_schema.sql", "002_expand_v1_tables.sql"]


def test_apply_migrations_executes_all_migration_files():
    conn = _FakeConnection()

    apply_migrations(conn)

    executed = "\n".join(sql for sql, _ in conn.calls)
    assert "CREATE SCHEMA IF NOT EXISTS uw_scan" in executed
    assert "CREATE TABLE IF NOT EXISTS uw_scan.flow_events" in executed
    assert conn.commits == 1


def test_save_dashboard_snapshot_persists_core_rows():
    conn = _FakeConnection()
    dashboard = demo_dashboard()

    save_dashboard_snapshot(conn, dashboard, mode="fixture")

    executed = "\n".join(sql for sql, _ in conn.calls)
    assert "INSERT INTO uw_scan.scan_runs" in executed
    assert "DELETE FROM uw_scan.flow_events" in executed
    assert "DELETE FROM uw_scan.opportunity_scores" in executed
    assert "INSERT INTO uw_scan.flow_events" in executed
    assert "INSERT INTO uw_scan.opportunity_scores" in executed
    assert conn.commits == 1


def test_list_snapshot_summaries_loads_scan_runs():
    conn = _FakeConnection(
        rows=[
            {
                "run_id": "fixture-1",
                "mode": "fixture",
                "started_at_utc": datetime(2026, 5, 11, tzinfo=timezone.utc),
                "source_count": 2,
                "opportunity_count": 6,
            }
        ]
    )

    snapshots = list_snapshot_summaries(conn)

    assert snapshots[0].run_id == "fixture-1"
    assert snapshots[0].opportunity_count == 6
    assert "FROM uw_scan.scan_runs" in conn.calls[0][0]


def test_load_dashboard_snapshot_reconstructs_flow_and_opportunities():
    conn = _FakeConnection(
        rows=[
            {
                "row_kind": "scan",
                "run_id": "fixture-1",
                "mode": "snapshot",
                "started_at_utc": datetime(2026, 5, 11, tzinfo=timezone.utc),
                "request_budget": 12,
            },
            {
                "row_kind": "flow",
                "ticker": "TSLA",
                "option_symbol": "TSLA260417C00385000",
                "expiry": datetime(2026, 4, 17, tzinfo=timezone.utc).date(),
                "strike": "385",
                "option_type": "call",
                "premium": "524300000",
                "volume": 136564,
                "open_interest": 56586,
                "side": "ask",
                "dte": 24,
            },
            {
                "row_kind": "opportunity",
                "ticker": "TSLA",
                "option_symbol": "TSLA 2026-04-17 385C",
                "score": 5,
                "direction": "bullish",
                "setup_types": "Deep Conviction Directional",
                "confirmations": "Volume > OI|Ask-side aggression",
                "warnings": "",
            },
        ]
    )

    dashboard = load_dashboard_snapshot(conn, "fixture-1")

    assert dashboard.snapshots[0].run_id == "fixture-1"
    assert dashboard.flow_rows[0].ticker == "TSLA"
    assert dashboard.opportunities[0].direction.value == "bullish"
