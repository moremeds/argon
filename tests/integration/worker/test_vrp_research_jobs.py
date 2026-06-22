from __future__ import annotations

from datetime import date, timedelta

from uw_scan.worker.jobs.vrp_research_jobs import vrp_research_refresh


def _seed_spy(repo, *, n=80):
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) VALUES ('SPY','Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
        for i in range(n):
            d = d0 + timedelta(days=i)
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES ('SPY', %s, %s)",
                (d, 100.0 if i % 2 == 0 else 101.0),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES ('SPY', %s, %s, %s, %s, %s)",
                (d, 0.30, 0.20, 0.10, 1.5),
            )
    repo.conn.commit()


def test_orchestrator_runs_all_axes_and_persists(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spy(repo)
    results = vrp_research_refresh(repo=repo)
    # all five axes ran without raising
    assert set(results) == {
        "rv_validation",
        "harvest_by_sector",
        "harvest_multihorizon",
        "directional",
        "dvrp_reversion",
    }
    assert all("error" not in v for v in results.values())
    # SPY (index_macro) populates validation + multi-horizon + ΔVRP
    assert repo.fetch_vrp_rv_validation()
    assert repo.fetch_vrp_harvest_multihorizon()
    assert repo.fetch_vrp_dvrp_reversion()
