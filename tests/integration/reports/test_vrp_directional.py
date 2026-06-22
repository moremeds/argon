from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.vrp_directional import (
    run_vrp_directional,
    run_vrp_dvrp_reversion,
)

D0 = date(2026, 1, 1)


def _seed_prices_and_z(repo, ticker, *, n, z, price_fn):
    with repo.conn.cursor() as cur:
        for i in range(n):
            d = D0 + timedelta(days=i)
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s, %s, %s)",
                (ticker, d, price_fn(i)),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (ticker, d, 0.30, 0.20, 0.10, z),
            )
    repo.conn.commit()


def test_directional_rich_outperforms_cheap_is_bullish(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    n = 40
    # 2 RICH names trend UP ~1%/day; 2 CHEAP names flat → RICH cohort out-returns
    # CHEAP cohort every date → positive differential → BULLISH_TILT.
    for tk in ("RCH1", "RCH2"):
        _seed_prices_and_z(repo, tk, n=n, z=2.0, price_fn=lambda i: 100.0 * (1.01**i))
    for tk in ("CHP1", "CHP2"):
        _seed_prices_and_z(repo, tk, n=n, z=-2.0, price_fn=lambda i: 100.0)

    out = run_vrp_directional(repo=repo, horizons=(5,))
    assert out["buckets_written"] >= 1
    rows = {
        (r["asset_class"], r["horizon"]): r
        for r in repo.fetch_vrp_directional_verdicts()
    }
    r = rows[("single_name", 5)]
    assert r["verdict"] == "BULLISH_TILT"
    assert float(r["mean_differential"]) > 0
    assert float(r["mean_rich_return"]) > float(r["mean_cheap_return"])
    assert r["n"] >= 20


def test_dvrp_rich_reverts_down(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # RICH (z=2) ticker whose VRP falls 0.01/day → forward ΔVRP strongly negative
    # → RICH reverts DOWN → REVERTS.
    ticker = "ZZZ"
    with repo.conn.cursor() as cur:
        for i in range(40):
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (ticker, D0 + timedelta(days=i), 0.30, 0.20, 0.40 - 0.01 * i, 2.0),
            )
    repo.conn.commit()

    out = run_vrp_dvrp_reversion(repo=repo, horizons=(5,))
    assert out["buckets_written"] >= 1
    rows = {
        (r["asset_class"], r["deviation_class"], r["horizon"]): r
        for r in repo.fetch_vrp_dvrp_reversion()
    }
    r = rows[("single_name", "RICH", 5)]
    assert r["verdict"] == "REVERTS"
    assert float(r["mean_fwd_dvrp"]) < 0
