"""E5 regression: run_vrp_markout must compute the forward RV from the
corp-action-adjusted PRICE series (item 1), not read the (here deliberately
wrong) vrp_daily.rv column."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.vrp_markout import run_vrp_markout


def _seed_spy(repo, *, n: int = 60, iv: float = 0.30) -> None:
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(n):
            d = d0 + timedelta(days=i)
            # gentle oscillation → finite, positive realized vol (~0.16 annualized)
            price = 100.0 if i % 2 == 0 else 101.0
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s, %s, %s)",
                ("SPY", d, price),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ("SPY", d, iv, 0.0, iv, 2.0),  # rv=0 is WRONG on purpose; z=2 → RICH
            )
    repo.conn.commit()


def test_harvest_uses_exact_rv_not_vrp_daily_rv(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spy(repo)
    out = run_vrp_markout(repo=repo)
    assert out["tickers"] == 1
    rows = {
        (r["asset_class"], r["deviation_class"]): r
        for r in repo.fetch_vrp_harvest_verdicts()
    }
    rich = rows[("index_macro", "RICH")]
    mean = float(rich["mean_realized_vrp"])
    # If the stale rv=0 were used, mean would be iv - 0 = 0.30. With exact RV from
    # the price oscillation (~0.16), mean ≈ 0.30 - 0.16 = ~0.14 — provably lower.
    assert 0.05 < mean < 0.25, f"expected price-derived RV harvest, got {mean}"
    assert abs(mean - 0.30) > 0.05, "harvest still reflects the stale rv=0 column"
