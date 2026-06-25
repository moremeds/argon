from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository


def test_health_exposes_freshness(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    DataFreshnessRepository(repo.conn, schema=repo._schema).upsert_snapshot(
        date(2026, 6, 25),
        [
            FreshnessRow(
                "vrp_daily",
                "market_date",
                "watchlist",
                100,
                9,
                0.09,
                date(2026, 5, 22),
                34,
                True,
            ),
            FreshnessRow(
                "daily_ohlc",
                "market_date",
                "watchlist",
                100,
                100,
                1.0,
                date(2026, 6, 24),
                1,
                False,
            ),
        ],
    )
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("freshness") is not None
    fresh = body["freshness"]
    # Frozen table surfaces in the frozen list; fresh one does not.
    assert "vrp_daily" in fresh["frozen"]
    assert "daily_ohlc" not in fresh["frozen"]
    assert fresh["as_of"] == "2026-06-25"
    by_name = {t["table_name"]: t for t in fresh["tables"]}
    assert by_name["vrp_daily"]["frozen"] is True
    assert by_name["vrp_daily"]["coverage_pct"] == 0.09
