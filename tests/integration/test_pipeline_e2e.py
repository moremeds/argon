"""End-to-end pipeline test against the live UW API.

Gated on `UW_SCAN_API_KEY` being set — skipped on CI. The S1 exit gate is
encoded here as concrete row-count assertions on every populated table after
one TSLA run.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock
from uw_scan.storage.repository import Repository

LIVE_MARK = pytest.mark.live
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "uw_scan"
    / "storage"
    / "migrations"
    / "001_s1_core_tables.sql"
)


def _has_live_key() -> bool:
    settings_env = os.environ.get("UW_SCAN_API_KEY", "")
    return bool(settings_env.strip())


pytestmark = pytest.mark.skipif(
    not _has_live_key(), reason="UW_SCAN_API_KEY not set; live pipeline test is skipped"
)


@LIVE_MARK
def test_pipeline_e2e_tsla_exit_gate(tmp_path_factory):
    """Run the S1 pipeline against TSLA and assert the exit-gate row counts.

    Uses the local `option_wizard` DB but a fresh schema (`uw_scan_e2e`) so this
    test does not collide with developer state.
    """
    settings = Settings.from_env()

    # Use an isolated schema so this test never interferes with hand-driven dev state.
    schema = "uw_scan_e2e"
    conn = psycopg.connect(settings.db_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute(f"CREATE SCHEMA {schema}")
            # Re-target migration to the test schema by substituting the literal.
            migration = MIGRATION_PATH.read_text().replace("uw_scan.", f"{schema}.")
            migration = migration.replace(
                f"CREATE SCHEMA IF NOT EXISTS {schema}",
                f"-- schema {schema} created above",
            )
            cur.execute(migration)
        conn.commit()

        repo = Repository(conn, schema=schema)
        with UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        ) as client:
            report = run_single_stock("TSLA", client, repo)

        assert report is not None
        assert report.ticker == "TSLA"

        # Exit gate row counts (S1 plan §Exit Gate item 3).
        gate = {
            "scan_runs": (1, None),
            "raw_payloads": (16, None),
            "api_request_audit": (16, None),
            "flow_events": (1, None),
            "iv_rank_history": (1, None),
            "volatility_stats_history": (1, None),
            "realized_volatility_history": (1, None),
            "iv_term_snapshots": (1, None),
            "interpolated_iv_snapshots": (1, None),
            "risk_reversal_skew_history": (1, None),
            "greeks_by_expiry_strike": (1, None),
            "exposures_by_expiry_strike": (1, None),
            "oi_by_strike": (1, None),
            "oi_change_events": (1, None),
            "max_pain_by_expiry": (1, None),
            "option_contract_snapshots": (1, None),
            "dark_pool_events": (0, None),
            "short_interest_snapshots": (1, 1),
            "opportunity_scores": (1, None),
            "option_surface_snapshots": (0, 0),
            "oi_by_expiry": (0, 0),
        }
        failures: list[str] = []
        with conn.cursor() as cur:
            for table, (min_count, max_count) in gate.items():
                cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
                (n,) = cur.fetchone()
                if n < min_count:
                    failures.append(f"{table}: got {n}, expected ≥ {min_count}")
                if max_count is not None and n > max_count:
                    failures.append(f"{table}: got {n}, expected ≤ {max_count}")
        assert not failures, "exit gate row counts failed:\n  " + "\n  ".join(failures)
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()
        conn.close()
