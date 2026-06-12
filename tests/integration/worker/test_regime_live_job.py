"""regime_live_scan_once — quote-gated live snapshot of CRI + VCG."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from uw_scan.worker.jobs.regime_live import regime_live_scan_once

# reuse the seeding helpers from the live-compute test
from tests.integration.test_regime_live_compute import SESSION, _seed
from uw_scan.config import Settings
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository


def _settings() -> Settings:
    return Settings.from_env()


def test_skips_when_no_fresh_quotes(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    summary = regime_live_scan_once(repo, _settings())
    assert summary["status"] == "skipped_no_fresh_quotes"
    assert CriSnapshotRepository(repo.conn).fetch_latest(basis="live") is None


def test_persists_live_cri_and_vcg_rows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    quoted = datetime.combine(SESSION, time(15, 30), tzinfo=timezone.utc)
    repo.bulk_upsert_intraday_quotes(
        [
            ("VIX", Decimal("25.5"), quoted, "xenon_ws"),
            ("VVIX", Decimal("112.0"), quoted, "xenon_ws"),
            ("SPX", Decimal("7300.0"), quoted, "xenon_ws"),
            ("HYG", Decimal("78.90"), quoted, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    summary = regime_live_scan_once(
        repo, _settings(), now=quoted + timedelta(minutes=1)
    )
    assert summary["status"] == "ok"
    assert summary["cri"] is True and summary["vcg"] is True
    assert CriSnapshotRepository(repo.conn).fetch_latest(basis="live")["vix"] == 25.5
    assert (
        VcgSnapshotRepository(repo.conn).fetch_latest(proxy="HYG", basis="live")
        is not None
    )
