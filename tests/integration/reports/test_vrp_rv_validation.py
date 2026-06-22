from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.vrp_rv_validation import run_vrp_rv_validation


def test_validation_quantifies_approx_vs_exact(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(40):
            d = d0 + timedelta(days=i)
            price = 100.0 if i % 2 == 0 else 101.0  # gentle oscillation
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s, %s, %s)",
                ("TST", d, price),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ("TST", d, 0.30, 0.30, 0.0, 0.5),  # rv=0.30 (the approximation)
            )
    repo.conn.commit()

    out = run_vrp_rv_validation(repo=repo, horizons=(5,))
    assert out["rows_written"] == 1
    rows = repo.fetch_vrp_rv_validation()
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "TST" and r["horizon"] == 5
    assert r["n"] == 35  # anchors 0..34 (i+5 < 40)
    # approx (0.30) systematically exceeds the exact oscillation RV (~0.16),
    # so the signed deviation is clearly positive.
    assert float(r["mean_signed_dev"]) > 0.05
    assert float(r["mean_abs_dev"]) > 0.05


def test_validation_skips_ticker_without_prices(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(30):
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ("NOPX", d0 + timedelta(days=i), 0.3, 0.2, 0.1, 0.5),
            )
    repo.conn.commit()
    out = run_vrp_rv_validation(repo=repo, horizons=(5,))
    assert out["rows_written"] == 0  # no price series → cannot compute exact RV
