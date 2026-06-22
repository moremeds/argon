from __future__ import annotations

from datetime import date, timedelta

from uw_scan.worker.jobs.vrp_markout import vrp_markout_refresh


def test_vrp_markout_refresh_writes_verdicts(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    # Tag MACX 'Macro' → index_macro (the single_name earnings safeguard skips
    # single-names with no flow_events coverage; index_macro needs none).
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) "
            "VALUES ('MACX', 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
    repo.upsert_vrp_daily_rows(
        [
            {
                "ticker": "MACX",
                "market_date": start + timedelta(days=i),
                "iv": 0.30,
                "rv": 0.20,
                "vrp": 0.10,
                "vrp_z_20": 1.5,
            }
            for i in range(80)
        ]
    )
    repo.conn.commit()

    out = vrp_markout_refresh(repo=repo)
    assert out["buckets_written"] >= 1
    assert out["tickers"] >= 1
    verdicts = repo.fetch_vrp_harvest_verdicts()
    assert any(v["verdict"] == "HARVEST_SELLABLE" for v in verdicts)
