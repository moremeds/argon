"""Migrations 021 / 023 / 047 / 048: a replay must not touch runtime rows.

The API self-migrates on every boot (``migrate_runner`` re-runs EVERY file), so the
UPDATEs these files used to carry re-applied on every deploy:

- 021 failed every queued/running AI analysis not on the v2 prompt (live is v5.3);
- 023 recomputed every flow_alerts_daily_rollup row from flow_events (DO UPDATE);
- 047 / 048 invalidated gold-posture rows, changing what point-in-time reads return.

Each seeded row below matches one of those old predicates, so this test fails if
any of that DML comes back. Same replay mechanics as
test_watchlist_migration_replay.py.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from uw_scan.storage.migrate_runner import MIGRATIONS_DIR, apply_migrations

pytestmark = pytest.mark.integration

_DUMPS = {
    "trade_insight_ai_analyses": "analysis_id",
    "flow_alerts_daily_rollup": "ticker, trade_date",
    "gold_posture_daily": "obs_date, computed_at",
}


def _dump(conn: psycopg.Connection) -> dict[str, list[tuple]]:
    out = {}
    with conn.cursor() as cur:
        for table, order in _DUMPS.items():
            cur.execute(f"SELECT * FROM uw_scan.{table} ORDER BY {order}")
            out[table] = cur.fetchall()
    return out


def _replay(
    fixture_conn: psycopg.Connection, dsn: str, migrations_dir: Path = MIGRATIONS_DIR
) -> None:
    fixture_conn.rollback()
    with psycopg.connect(dsn, autocommit=True) as conn:
        apply_migrations(conn, migrations_dir=migrations_dir, log=lambda _msg: None)


def _seed_rows_the_old_dml_matched(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.scan_runs (ticker) VALUES ('AAPL') RETURNING run_id"
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO uw_scan.trade_insight_snapshots "
            "(run_id, ticker, assembler_version, input_hash, payload_jsonb) "
            "VALUES (%s, 'AAPL', 'v1', 'h', '{}') RETURNING snapshot_id",
            (run_id,),
        )
        snapshot_id = cur.fetchone()[0]
        # 021 (1): an in-flight analysis on the live prompt, not v2.
        # 021 (2): a v2 row whose input JSON lacks the prompt_version stamp.
        for status, prompt in (
            ("queued", "trade-insights-ai-v5.3"),
            ("succeeded", "trade-insights-ai-v2"),
        ):
            cur.execute(
                "INSERT INTO uw_scan.trade_insight_ai_analyses (snapshot_id, ticker, "
                "run_id, trade_insights_input_hash, analysis_input_hash, "
                "analysis_input_jsonb, model, prompt_version, status) "
                "VALUES (%s, 'AAPL', %s, 'h', 'h', '{}', 'm', %s, %s)",
                (snapshot_id, run_id, prompt, status),
            )
        # 023: a rollup the runtime writer owns, disagreeing with a recompute
        # from flow_events (1 event vs alert_count 42).
        cur.execute(
            "INSERT INTO uw_scan.flow_events (run_id, alert_id, ticker, created_at, "
            "option_type, total_premium) "
            "VALUES (%s, 'a1', 'AAPL', '2026-09-01 15:00-04', 'call', 100)",
            (run_id,),
        )
        cur.execute(
            "INSERT INTO uw_scan.flow_alerts_daily_rollup "
            "(ticker, trade_date, run_id, alert_count, total_premium) "
            "VALUES ('AAPL', '2026-09-01', %s, 42, 999)",
            (run_id,),
        )
        # 047: a posture row dated after the latest GLD close.
        # 048: an earlier same-day row without CB fields, then a later one with them.
        cur.execute(
            "INSERT INTO uw_scan.macro_series_daily "
            "(series_id, obs_date, value, as_of, source) "
            "VALUES ('GLD_CLOSE', '2026-09-01', 300, now(), 'MASSIVE')"
        )
        for obs_date, computed_at, cb in (
            ("2026-09-02", "2026-09-02 19:10-04", None),
            ("2026-09-01", "2026-09-01 19:10-04", None),
            ("2026-09-01", "2026-09-01 20:05-04", 5),
        ):
            cur.execute(
                "INSERT INTO uw_scan.gold_posture_daily (obs_date, computed_at, "
                "gauge_state, inputs_jsonb, cb_strategic_12m_sum_t) "
                "VALUES (%s, %s, 'neutral', '{}', %s)",
                (obs_date, computed_at, cb),
            )
    conn.commit()


def test_replay_leaves_runtime_rows_byte_identical(
    seeded_db_empty_cards, _migrated_settings
):
    conn = seeded_db_empty_cards.conn
    _seed_rows_the_old_dml_matched(conn)
    before = _dump(conn)
    assert len(before["trade_insight_ai_analyses"]) == 2
    assert len(before["gold_posture_daily"]) == 3

    _replay(conn, _migrated_settings.db_dsn())
    first = _dump(conn)
    _replay(conn, _migrated_settings.db_dsn())

    assert first == before
    assert _dump(conn) == before
