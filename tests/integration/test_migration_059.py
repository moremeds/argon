"""Migration 059 — research scope columns for regime_backtest_runs.

Verifies the migration is safe for existing rows: a row inserted with the
v1 schema and historical research metadata in summary['extras'] must end up
correctly labeled run_scope='research', not 'production'. Verifies idempotency
by running the migration script twice.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

MIGRATION = Path(
    "src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql"
)


def _apply(conn: psycopg.Connection, sql_path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(sql_path.read_text())
    conn.commit()


def test_migration_promotes_columns_and_backfills_research_rows(
    seeded_db_empty_cards,
) -> None:
    conn = seeded_db_empty_cards.conn

    # First, drop the columns added by an earlier migration application
    # so this test exercises the backfill path. The fixture has already
    # run scripts/migrate.sh which includes 059, so columns exist with
    # defaults applied. Recreate the "pre-059" state.
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE uw_scan.regime_backtest_runs
              DROP COLUMN IF EXISTS run_scope,
              DROP COLUMN IF EXISTS composite_method,
              DROP COLUMN IF EXISTS credit_proxy
            """
        )
        cur.execute(
            "ALTER TABLE uw_scan.regime_backtest_runs "
            "DROP CONSTRAINT IF EXISTS regime_backtest_runs_scope_check"
        )
        cur.execute(
            "ALTER TABLE uw_scan.regime_backtest_runs "
            "DROP CONSTRAINT IF EXISTS regime_backtest_runs_composite_method_check"
        )
        cur.execute(
            "ALTER TABLE uw_scan.regime_backtest_runs "
            "DROP CONSTRAINT IF EXISTS regime_backtest_runs_vcg_credit_proxy_check"
        )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
                (indicator, composite_version, start_date, end_date, window_days,
                 n_days, params, summary, note, completed_at)
            VALUES ('vcg', '1', '2024-01-01', '2024-12-31', 21, 252, %s, %s, NULL, NOW())
            """,
            (Jsonb({}), Jsonb({"extras": {"credit_proxy": "HYG"}})),
        )
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
                (indicator, composite_version, start_date, end_date, window_days,
                 n_days, params, summary, note, completed_at)
            VALUES ('vcg', '2-candidate-rp3', '2024-01-01', '2024-12-31', 21, 252, %s, %s, NULL, NOW())
            """,
            (
                Jsonb({}),
                Jsonb(
                    {
                        "extras": {
                            "credit_proxy": "COMPOSITE_RP3",
                            "composite_method": "risk_parity_3",
                        }
                    }
                ),
            ),
        )
    conn.commit()

    _apply(conn, MIGRATION)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT credit_proxy, run_scope, composite_method "
            "FROM uw_scan.regime_backtest_runs WHERE composite_version = '1'"
        )
        prod_row = cur.fetchone()
        cur.execute(
            "SELECT credit_proxy, run_scope, composite_method "
            "FROM uw_scan.regime_backtest_runs WHERE composite_version = '2-candidate-rp3'"
        )
        research_row = cur.fetchone()

    assert prod_row == ("HYG", "production", "single_proxy")
    assert research_row == ("COMPOSITE_RP3", "research", "risk_parity_3")


def test_migration_is_idempotent(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn
    # Fixture already applied 059 once. A second apply must not raise.
    _apply(conn, MIGRATION)
    _apply(conn, MIGRATION)


def test_migration_enforces_vcg_credit_proxy_check(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn
    # Fixture already applied 059. Insert a VCG row with NULL credit_proxy
    # and expect the check constraint to reject it.
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.regime_backtest_runs
                    (indicator, composite_version, start_date, end_date,
                     window_days, n_days, params, summary, run_scope,
                     composite_method, credit_proxy)
                VALUES ('vcg', '1', '2025-01-01', '2025-12-31', 21, 252,
                        %s, %s, 'production', 'single_proxy', NULL)
                """,
                (Jsonb({}), Jsonb({})),
            )
        conn.commit()
