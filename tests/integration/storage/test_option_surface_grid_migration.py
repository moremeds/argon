"""Migration 077 — the durable grid must exist AND carry no cascading FK.

The whole point of this table is to outlive scan_runs: greeks_by_expiry_strike
stays ~30 days deep only because it cascade-deletes with its run. This test is the
regression guard against re-introducing that trap.
"""

from __future__ import annotations


def test_option_surface_grid_exists_with_no_foreign_key(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute("SELECT to_regclass('uw_scan.option_surface_grid_daily')")
        assert cur.fetchone()[0] is not None, "grid table missing"
        cur.execute(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE table_schema='uw_scan' "
            "  AND table_name='option_surface_grid_daily' "
            "  AND constraint_type='FOREIGN KEY'"
        )
        assert cur.fetchone()[0] == 0, (
            "grid table must have NO foreign key (no cascade trap)"
        )
