from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_backtest import run_vrp_backtest


def _seed_quiet_rich_ticker(repo, ticker="TESTQ"):
    """High IV, then a FLAT realized path → condor expires at max profit every time."""
    start = date(2024, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(80):
            d = start + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 0.60, 0.10, 0.50, 2.0),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 100.0),  # flat → zero realized move
            )
        # earnings coverage so the single_name skip-guard admits the ticker;
        # filing_date is far outside the 2024 trade windows → no exclusion overlap
        cur.execute(
            "INSERT INTO uw_scan.massive_fundamentals"
            "(ticker, period_end, fetched_at, filing_date) "
            "VALUES (%s, %s, now(), %s) ON CONFLICT DO NOTHING",
            (ticker, date(2024, 12, 31), date(2025, 1, 1)),
        )
    repo.conn.commit()


def test_quiet_rich_ticker_is_profitable(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_quiet_rich_ticker(repo)
    # make its sector SELLABLE so the gate admits it
    repo.upsert_vrp_harvest_by_sector(
        sector="unknown",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.4,
        mean_holdout=0.4,
        rich_cheap_spread=None,
        n=80,
        n_holdout=32,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2024, 4, 1),
    )
    repo.conn.commit()
    out = run_vrp_backtest(
        repo=repo, settings=Settings(api_key=SecretStr("test")), hold_days=20
    )
    assert out["units"] >= 1
    rows = {(r["unit_key"], r["scope"]): r for r in repo.fetch_vrp_backtest_results(20)}
    full = rows[("TESTQ", "full")]
    assert full["n_trades"] > 0
    assert full["total_net"] > 0  # flat path + rich IV → net positive after costs
    assert full["breach_rate"] == 0  # never breached a short strike
    assert ("TESTQ", "holdout") in rows  # honest headline present


def test_non_sellable_sector_is_excluded(seeded_db_empty_cards, monkeypatch):
    """Gate negative: a RICH single name whose sector bucket is NOT SELLABLE
    must produce zero backtest rows."""
    repo = seeded_db_empty_cards
    _seed_quiet_rich_ticker(repo, ticker="EXCL")
    monkeypatch.setattr(repo, "fetch_watchlist_sector", lambda t: "BadSector")
    # seed a SELLABLE bucket for a DIFFERENT sector only
    repo.upsert_vrp_harvest_by_sector(
        sector="GoodSector",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.4,
        mean_holdout=0.4,
        rich_cheap_spread=None,
        n=80,
        n_holdout=32,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2024, 4, 1),
    )
    repo.conn.commit()
    run_vrp_backtest(
        repo=repo, settings=Settings(api_key=SecretStr("test")), hold_days=20
    )
    rows = {(r["unit_key"], r["scope"]) for r in repo.fetch_vrp_backtest_results(20)}
    assert ("EXCL", "full") not in rows  # excluded by the SELLABLE-sector gate
