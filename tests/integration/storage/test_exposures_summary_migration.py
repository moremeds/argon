"""Smoke test for migration 051 — table + PK + index exist; re-running migrate.sh is a no-op."""

from __future__ import annotations

import os

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.storage.repository import Repository


def test_exposures_summary_table_created(seeded_db_empty_cards: Repository):
    """conftest's session migration already applied every migration; assert the table + columns exist."""
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute("SELECT to_regclass('uw_scan.exposures_summary')")
        assert cur.fetchone()[0] is not None

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'uw_scan' AND table_name = 'exposures_summary'
            """
        )
        cols = {row[0] for row in cur.fetchall()}
        for c in (
            "run_id",
            "ticker",
            "expiry",
            "market_date",
            "dte",
            "spot",
            "net_vanna",
            "top_vanna_strike",
            "top_vanna_value",
            "delta_shock_1pt_iv",
            "vanna_regime",
            "vanna_flip",
            "vanna_headline",
            "vanna_subtitle",
            "net_charm",
            "charm_pin_strike",
            "charm_above_sum",
            "charm_below_sum",
            "charm_imbalance_pct",
            "charm_signal_quality",
            "charm_flip",
            "charm_headline",
            "charm_subtitle",
            "computed_at",
        ):
            assert c in cols, f"missing column: {c}"


def test_migration_is_idempotent(seeded_db_empty_cards: Repository):
    """Re-applying every migration on the already-migrated DB must be a no-op."""
    repo = seeded_db_empty_cards
    settings = Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        apply_migrations(conn, log=lambda _msg: None)
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.exposures_summary")
        assert cur.fetchone()[0] == 0
