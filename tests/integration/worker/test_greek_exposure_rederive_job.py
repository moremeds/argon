from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from uw_scan.models import MarketAggregates
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.worker.jobs.greek_exposure_rederive import greek_exposure_rederive


def _ok_run(repo, ticker):
    rid = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(rid, MarketAggregates(call_oi_total=1, iv30d=None))
    repo.finish_scan_run(rid, status="ok")
    return rid


def _strike(repo, rid, ticker, md, cg, pg):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id,ticker,market_date,expiry,strike,dte,call_delta,put_delta,call_gex,put_gex)
                VALUES (%s,%s,%s,%s,100,30,1,-1,%s,%s)
                ON CONFLICT DO NOTHING""",
            (rid, ticker, md, date(2026, 6, 20), cg, pg),
        )
    repo.conn.commit()


def test_rederive_job_populates_daily(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    md = date(2026, 5, 21)
    rid = _ok_run(repo, "NVDA")
    _strike(repo, rid, "NVDA", md, 4.0, -1.0)

    # Stub settings — the job reads only db_schema + gex_scan_tickers.
    settings = SimpleNamespace(
        db_schema=repo._schema, gex_scan_tickers=["SPX", "SPY", "TLT"]
    )
    summary = greek_exposure_rederive(
        repo=repo, settings=settings, run_date=date(2026, 5, 22)
    )
    assert summary["rows"] >= 1

    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    hist = g.fetch_history("NVDA", days=10)
    assert hist and hist[-1]["net_gex"] == pytest.approx(3.0)
