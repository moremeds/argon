from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor


def test_monitor_persists_and_flags_frozen(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    g.upsert_rows(
        "NVDA",
        [
            {
                "trade_date": date(2026, 5, 20),
                "call_gex": 1.0,
                "put_gex": -1.0,
                "call_delta": 1.0,
                "put_delta": -1.0,
                "payload": {},
            }
        ],
    )
    # Stub settings — autoheal is off, so only db_schema and the enable flag
    # (read before short-circuiting) are needed.
    settings = SimpleNamespace(
        db_schema=repo._schema, data_freshness_autoheal_enabled=False
    )
    summary = data_freshness_monitor(
        repo=repo, settings=settings, today=date(2026, 6, 25)
    )
    assert summary["persisted"] >= 1
    latest = DataFreshnessRepository(repo.conn, schema=repo._schema).latest_snapshot()
    g_row = next(r for r in latest if r["table_name"] == "greek_exposure_daily")
    assert g_row["frozen"] is True
