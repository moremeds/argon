"""regime_live_scan_once — basis='live' SPX VRP macro short-vol persist leg.

Seeds >=252 SPX/VIX vol_index rows (so vrp_z is computable) + fresh SPX/VIX
intraday quotes, then asserts the 5-min job writes a basis='live' SPX row.
The cri/vcg legs may no-op here (missing VVIX/VIX3M/COR1M history) — that's the
intended per-leg isolation; the seed is committed first so a cri/vcg rollback
can't wipe it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from uw_scan.config import Settings
from uw_scan.worker.jobs.regime_live import regime_live_scan_once

_QUOTED = datetime(2026, 6, 12, 15, 30, tzinfo=timezone.utc)  # a Friday RTH instant


def _settings() -> Settings:
    return Settings.from_env()


def test_regime_live_persists_vrp_live_spx(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()  # commit seed + quotes before the scan (survive a cri/vcg rollback)

    summary = regime_live_scan_once(
        repo, _settings(), now=_QUOTED + timedelta(minutes=1)
    )
    assert summary["status"] == "ok"
    assert summary["vrp"] == "ok"

    live = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="live")
    assert len(live) == 1
    assert live[0]["snapshot_date"] == datetime.now(ZoneInfo("America/New_York")).date()
    assert live[0]["action"] in ("TRADE", "SKIP")


def test_regime_live_vrp_skips_without_spx_or_vix_quote(seeded_db_empty_cards) -> None:
    """No SPX/VIX quote → vrp leg skips (status 'skipped'), no live row written."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes([("HYG", Decimal("78.90"), _QUOTED, "xenon_ws")])
    repo.conn.commit()

    summary = regime_live_scan_once(
        repo, _settings(), now=_QUOTED + timedelta(minutes=1)
    )
    assert summary["vrp"] == "skipped"
    assert repo.fetch_latest_vrp_macro_signals(["SPX"], basis="live") == []
