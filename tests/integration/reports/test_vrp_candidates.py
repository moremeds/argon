from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_candidates import run_vrp_candidates


def test_emits_rich_sellable_candidate(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 5, 1)
    with repo.conn.cursor() as cur:
        for i in range(30):
            d = start + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                ("CAND", d, 0.50, 0.20, 0.30, 2.0),  # currently RICH
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                ("CAND", d, 100.0),
            )
        # earnings coverage (far in the past → no forward-window overlap)
        cur.execute(
            "INSERT INTO uw_scan.massive_fundamentals"
            "(ticker, period_end, fetched_at, filing_date) "
            "VALUES (%s, %s, now(), %s) ON CONFLICT DO NOTHING",
            ("CAND", date(2025, 12, 31), date(2026, 1, 15)),
        )
    repo.upsert_vrp_harvest_by_sector(
        sector="unknown",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.3,
        mean_holdout=0.3,
        rich_cheap_spread=None,
        n=30,
        n_holdout=12,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 5, 30),
    )
    repo.conn.commit()
    out = run_vrp_candidates(repo=repo, settings=Settings(api_key=SecretStr("test")))
    assert out["written"] >= 1
    rows = repo.fetch_vrp_candidates()
    cand = next(r for r in rows if r["ticker"] == "CAND")
    assert cand["bucket_verdict"] == "HARVEST_SELLABLE"
    assert cand["long_put"] < cand["short_put"] < cand["short_call"] < cand["long_call"]
    assert cand["entry_credit"] > 0 and cand["max_loss"] > 0
    assert cand["entry_cost"] is not None and cand["entry_cost"] > 0
