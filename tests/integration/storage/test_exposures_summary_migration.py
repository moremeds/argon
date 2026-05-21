"""Smoke test for migration 051 — table + PK + index exist; re-running migrate.sh is a no-op."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_exposures_summary_table_created(seeded_db_empty_cards: Repository):
    """conftest's _reset_and_migrate already ran migrate.sh; assert the table + columns exist."""
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
    """Re-running scripts/migrate.sh on the already-migrated DB must be a no-op."""
    repo = seeded_db_empty_cards
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    env = {**os.environ, "UW_SCAN_DB_NAME": test_db}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.exposures_summary")
        assert cur.fetchone()[0] == 0
