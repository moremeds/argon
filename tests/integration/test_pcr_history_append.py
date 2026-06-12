"""Repository.append_pcr_history persists a row and idempotently updates it on
re-write. Pipeline-level test (full run_single_stock + live UW client) is
covered by the wider e2e suite — this verifies the repo layer the pipeline
relies on.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def test_pcr_history_appended_and_idempotent(repo):
    today = date.today()
    repo.append_pcr_history(
        ticker="ZZTEST",
        snapshot_date=today,
        pcr_oi=Decimal("1.75"),
        pcr_vol=Decimal("1.60"),
    )
    row = repo.get_pcr_history_row("ZZTEST", today)
    assert row is not None
    assert row.pcr_oi == Decimal("1.7500")

    # Re-append same date with new values — should update, not duplicate.
    repo.append_pcr_history(
        ticker="ZZTEST",
        snapshot_date=today,
        pcr_oi=Decimal("2.00"),
        pcr_vol=Decimal("1.80"),
    )
    row2 = repo.get_pcr_history_row("ZZTEST", today)
    assert row2 is not None
    assert row2.pcr_oi == Decimal("2.0000")


def test_pcr_history_30d_ago_lookup(repo):
    from datetime import timedelta

    today = date(2026, 5, 12)
    repo.append_pcr_history(
        ticker="ZZTEST",
        snapshot_date=today - timedelta(days=35),
        pcr_oi=Decimal("1.50"),
        pcr_vol=None,
    )
    row = repo.get_pcr_history_30d_ago("ZZTEST", today)
    assert row is not None
    assert row.pcr_oi == Decimal("1.5000")
