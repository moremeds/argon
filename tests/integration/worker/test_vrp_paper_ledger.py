from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.jobs.vrp_trading_jobs import vrp_paper_mark, vrp_paper_open


def _seed_candidate_and_prices(repo):
    open_day = date(2026, 5, 1)
    repo.upsert_vrp_candidate(
        ticker="PAP",
        as_of=open_day,
        structure="iron_condor",
        spot=100.0,
        iv=0.5,
        vrp_z=2.0,
        hold_days=20,
        short_put=90.0,
        long_put=84.0,
        short_call=110.0,
        long_call=116.0,
        entry_credit=2.0,
        max_loss=4.0,
        put_width=6.0,
        call_width=6.0,
        bucket_sector="unknown",
        bucket_verdict="HARVEST_SELLABLE",
        earnings_clear=True,
        contracts=1,
    )
    with repo.conn.cursor() as cur:
        for i in range(40):
            d = open_day + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                ("PAP", d, 0.40, 0.20, 0.20, 1.5),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                ("PAP", d, 100.0),  # flat → settles at max profit
            )
    repo.conn.commit()
    return open_day


def test_open_then_close_at_expiry(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    open_day = _seed_candidate_and_prices(repo)
    s = Settings(api_key=SecretStr("test"))
    opened = vrp_paper_open(repo=repo, settings=s, as_of=open_day)
    assert opened["opened"] == 1
    assert len(repo.fetch_open_vrp_paper_positions()) == 1
    # mark on a date past expiry → position closes at realized expiry payoff
    far = open_day + timedelta(days=35)
    marked = vrp_paper_mark(repo=repo, settings=s, as_of=far)
    assert marked["closed"] == 1
    closed = repo.fetch_vrp_paper_positions(status="closed")
    assert closed[0]["realized_pnl"] is not None
    assert closed[0]["realized_pnl"] > 0  # flat path → keep credit minus costs


def test_no_same_day_close(seeded_db_empty_cards):
    """Regression for ISSUE-1: marking on the open day must NOT close the position
    (expiry is a future date and the price series hasn't reached it)."""
    repo = seeded_db_empty_cards
    open_day = _seed_candidate_and_prices(repo)
    s = Settings(api_key=SecretStr("test"))
    vrp_paper_open(repo=repo, settings=s, as_of=open_day)
    marked = vrp_paper_mark(repo=repo, settings=s, as_of=open_day)
    assert marked["closed"] == 0
    assert len(repo.fetch_open_vrp_paper_positions()) == 1
