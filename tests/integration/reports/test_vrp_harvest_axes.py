from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.vrp_harvest_axes import (
    run_vrp_harvest_by_sector,
    run_vrp_harvest_multihorizon,
)


def _seed(repo, ticker, *, n=80, z=1.5, iv=0.30):
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(n):
            d = d0 + timedelta(days=i)
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s, %s, %s)",
                (ticker, d, 100.0 if i % 2 == 0 else 101.0),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (ticker, d, iv, 0.20, iv - 0.20, z),
            )
    repo.conn.commit()


def _tag_sector(repo, ticker, sector):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) VALUES (%s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET sector=EXCLUDED.sector, removed_at=NULL",
            (ticker, sector),
        )
    repo.conn.commit()


def _seed_earnings(repo, ticker, d):
    run_id = repo.insert_scan_run(ticker=ticker)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date) VALUES (%s, %s, %s, %s)",
            (run_id, "e0", ticker, d),
        )
    repo.conn.commit()


def test_sector_run_buckets_single_names_by_sector(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _tag_sector(repo, "AAPL", "Tech")  # not a special tag → single_name
    _seed_earnings(repo, "AAPL", date(2030, 1, 1))  # far-future → no window straddles
    _seed(repo, "AAPL")
    out = run_vrp_harvest_by_sector(repo=repo)
    assert out["buckets_written"] >= 1
    rows = {
        (r["sector"], r["deviation_class"]): r
        for r in repo.fetch_vrp_harvest_by_sector()
    }
    assert ("Tech", "RICH") in rows
    assert rows[("Tech", "RICH")]["n"] >= 20


def test_multihorizon_writes_decay_rows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _tag_sector(repo, "SPY", "Macro")  # → index_macro, no earnings needed
    _seed(repo, "SPY")
    out = run_vrp_harvest_multihorizon(repo=repo, horizons=(5, 20))
    assert out["buckets_written"] >= 2
    rows = {
        (r["asset_class"], r["deviation_class"], r["horizon"]): r
        for r in repo.fetch_vrp_harvest_multihorizon()
    }
    assert ("index_macro", "RICH", 5) in rows
    assert ("index_macro", "RICH", 20) in rows
    # shorter horizon → more scorable anchors
    assert (
        rows[("index_macro", "RICH", 5)]["n"] > rows[("index_macro", "RICH", 20)]["n"]
    )
