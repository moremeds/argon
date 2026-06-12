"""End-to-end pipeline test against the live UW API.

Gated on `UW_SCAN_API_KEY` being set — skipped on CI. The S1 exit gate is
encoded here as concrete row-count assertions on every populated table after
one TSLA run.
"""

from __future__ import annotations

import os
import re

import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock

LIVE_MARK = pytest.mark.live

# UW issues bearer tokens in canonical UUID form. We require that shape so a
# placeholder like `dummy` or `test-dummy-not-used-by-db-tests` doesn't trip
# the test into a guaranteed 401 from the live API.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _has_live_key() -> bool:
    return bool(_UUID_RE.match(os.environ.get("UW_SCAN_API_KEY", "").strip()))


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to run live pipeline e2e "
            "against the working DB.",
            pytrace=False,
        )
    return Settings.from_env().model_copy(update={"db_name": test_db})


pytestmark = pytest.mark.skipif(
    not _has_live_key(),
    reason="UW_SCAN_API_KEY not set or not a UUID; live pipeline test is skipped",
)


@LIVE_MARK
def test_pipeline_e2e_tsla_exit_gate(seeded_db_empty_cards, tmp_path_factory):
    """Run the S1 pipeline against TSLA and assert the exit-gate row counts.

    Uses `seeded_db_empty_cards` for the schema migration (in-process, no
    psql subprocess) and runs against the shared option_wizard_test DB.
    """
    settings = _test_settings()
    repo = seeded_db_empty_cards
    schema = repo._schema
    conn = repo.conn
    try:
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
        # `seeded_db_empty_cards` owns the connection and restores baseline
        # for the next test — no per-test schema drop is needed here.
        pass
