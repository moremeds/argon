"""End-to-end pipeline test against the live UW API.

Gated on `UW_SCAN_API_KEY` being set — skipped on CI. The S1 exit gate is
encoded here as concrete row-count assertions on every populated table after
one TSLA run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock
from uw_scan.storage.repository import Repository

LIVE_MARK = pytest.mark.live
REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_live_key() -> bool:
    settings_env = os.environ.get("UW_SCAN_API_KEY", "")
    return bool(settings_env.strip())


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to run live pipeline e2e "
            "against the working DB.",
            pytrace=False,
        )
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _reset_and_migrate(settings: Settings) -> None:
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )


pytestmark = pytest.mark.skipif(
    not _has_live_key(), reason="UW_SCAN_API_KEY not set; live pipeline test is skipped"
)


@LIVE_MARK
def test_pipeline_e2e_tsla_exit_gate(tmp_path_factory):
    """Run the S1 pipeline against TSLA and assert the exit-gate row counts.

    Uses the local `option_wizard` DB but a fresh schema (`uw_scan_e2e`) so this
    test does not collide with developer state.
    """
    settings = _test_settings()
    _reset_and_migrate(settings)
    schema = "uw_scan"
    conn = psycopg.connect(settings.db_dsn())
    try:
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
