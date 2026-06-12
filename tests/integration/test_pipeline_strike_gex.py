"""After a scan_run is created and a strike_gex_curve is persisted,
assemble_single_stock_report should round-trip the curve into the report.

Runs against the isolated test DB (UW_SCAN_TEST_DB_NAME required) so this never
touches the developer's `option_wizard_local` data.
"""

from __future__ import annotations

import os
from decimal import Decimal
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to commit to the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def test_strike_gex_curve_persisted_and_round_trips(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    run_id = repo.insert_scan_run("ZZTEST", notes="t")
    repo.set_strike_gex_curve(
        run_id,
        [
            {
                "strike": "100",
                "expiry": "2026-05-30",
                "net_gex": "12.5",
                "call_gex": "20",
                "put_gex": "-7.5",
            },
            {
                "strike": "110",
                "expiry": "2026-05-30",
                "net_gex": "-5",
                "call_gex": "10",
                "put_gex": "-15",
            },
        ],
    )
    repo.finish_scan_run(run_id, status="ok")

    curve = repo.get_strike_gex_curve(run_id)
    assert len(curve) == 2
    assert Decimal(str(curve[0]["strike"])) == Decimal("100")
    assert Decimal(str(curve[1]["net_gex"])) == Decimal("-5")
