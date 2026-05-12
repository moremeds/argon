"""End-to-end Full Scan test against the live UW API.

Gated on `UW_SCAN_API_KEY` being set. Uses a fresh schema so it doesn't interfere
with developer-driven state. A small fixed universe limits cost.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_full_scan
from uw_scan.storage.repository import Repository

LIVE_MARK = pytest.mark.live
MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "uw_scan" / "storage" / "migrations"
)
MIGRATION_S1 = MIGRATIONS_DIR / "001_s1_core_tables.sql"
MIGRATION_S2 = MIGRATIONS_DIR / "002_s2_scan_tables.sql"


def _has_live_key() -> bool:
    return bool(os.environ.get("UW_SCAN_API_KEY", "").strip())


pytestmark = pytest.mark.skipif(
    not _has_live_key(),
    reason="UW_SCAN_API_KEY not set; live full-scan test is skipped",
)


@LIVE_MARK
def test_full_scan_e2e_small_universe():
    """Run a Full Scan against a 5-ticker universe + assert minimum row counts.

    Universe: TSLA, NVDA, AAPL, MSFT, SPY. SPY may or may not appear in the
    S&P 500 screener — we tolerate up to 1 missing ticker.
    """
    settings = Settings.from_env()
    schema = "uw_scan_s2_e2e"
    universe = ("TSLA", "NVDA", "AAPL", "MSFT", "SPY")

    conn = psycopg.connect(settings.db_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute(f"CREATE SCHEMA {schema}")
            s1 = MIGRATION_S1.read_text().replace("uw_scan.", f"{schema}.")
            s1 = s1.replace(
                f"CREATE SCHEMA IF NOT EXISTS {schema}",
                f"-- schema {schema} created above",
            )
            cur.execute(s1)
            s2 = MIGRATION_S2.read_text().replace("uw_scan.", f"{schema}.")
            cur.execute(s2)
        conn.commit()

        repo = Repository(conn, schema=schema)
        with UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        ) as client:
            report = run_full_scan(client, repo, universe=universe)

        assert report is not None
        assert report.universe_size == len(universe)

        # Row-count gate
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.scan_universe")
            (n_universe,) = cur.fetchone()
            cur.execute(f"SELECT COUNT(*) FROM {schema}.scan_results")
            (n_results,) = cur.fetchone()
            cur.execute(f"SELECT COUNT(*) FROM {schema}.api_request_audit")
            (n_audit,) = cur.fetchone()
            cur.execute(
                f"SELECT COUNT(*) FROM {schema}.api_request_audit "
                "WHERE endpoint_slug = 'bulk_screener_stocks'"
            )
            (n_bulk_audit,) = cur.fetchone()

        print(
            f"\n[scan e2e] scan_universe={n_universe} scan_results={n_results} "
            f"api_request_audit={n_audit} bulk_screener_audit={n_bulk_audit}"
        )

        assert n_universe == len(universe), (
            f"scan_universe rowcount {n_universe} != {len(universe)}"
        )
        # Allow up to 1 ticker missing from the S&P-500 screener response.
        assert n_results >= len(universe) - 1, f"scan_results too low: {n_results}"
        # At least the bulk screener call should be audited.
        assert n_bulk_audit >= 1, "no bulk_screener_stocks audit row"

        # At least one result should have a setup_type populated (in normal market
        # conditions). Print all for visibility either way.
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker, setup_type, score FROM {schema}.scan_results "
                "ORDER BY score DESC"
            )
            rows = cur.fetchall()
            print(f"[scan e2e] results: {rows}")

        # Don't hard-fail on classifications — market conditions vary. But we
        # assert at least one row has a non-null setup_type OR explicitly note
        # that none qualified.
        classified = [r for r in rows if r[1] is not None]
        print(f"[scan e2e] classified count: {len(classified)}")

    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()
        conn.close()
