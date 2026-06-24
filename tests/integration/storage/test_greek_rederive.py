from __future__ import annotations

from datetime import date

import pytest

from uw_scan.models import MarketAggregates
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository


def _insert_strike(repo, run_id, ticker, market_date, expiry, strike, cg, pg, cd, pd):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_delta, put_delta, call_gex, put_gex)
            VALUES (%s,%s,%s,%s,%s,30,%s,%s,%s,%s)
            ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING
            """,
            (run_id, ticker, market_date, expiry, strike, cd, pd, cg, pg),
        )
    repo.conn.commit()


def _ok_run(repo, ticker):
    run_id = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(run_id, MarketAggregates(call_oi_total=1, iv30d=None))
    repo.finish_scan_run(run_id, status="ok")
    return run_id


def test_rederive_sums_strikes_per_canonical_run(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 21)

    # Two runs for the SAME (ticker, market_date) — naive SUM would double-count.
    stale = _ok_run(repo, "NVDA")  # earlier, smaller capture
    _insert_strike(repo, stale, "NVDA", md, date(2026, 6, 20), 900, 1.0, -0.5, 10, -5)
    canon = _ok_run(repo, "NVDA")  # later, canonical
    _insert_strike(repo, canon, "NVDA", md, date(2026, 6, 20), 900, 2.0, -1.0, 20, -8)
    _insert_strike(repo, canon, "NVDA", md, date(2026, 6, 20), 950, 3.0, -1.5, 30, -9)

    rows = g.select_rederived_rows(ticker="NVDA")
    assert len(rows) == 1
    r = rows[0]
    assert r["trade_date"] == md
    # Only the canonical (later) run's strikes summed: 2+3, -1-1.5, 20+30, -8-9
    assert r["call_gex"] == pytest.approx(5.0)
    assert r["put_gex"] == pytest.approx(-2.5)
    assert r["call_delta"] == pytest.approx(50.0)
    assert r["put_delta"] == pytest.approx(-17.0)


def test_rederive_skips_non_ok_runs(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 22)
    bad = repo.insert_scan_run(ticker="AMD")  # no aggregates, not finished ok
    _insert_strike(repo, bad, "AMD", md, date(2026, 6, 20), 100, 9.0, -9.0, 9, -9)
    assert g.select_rederived_rows(ticker="AMD") == []


def test_compare_to_stored_and_persist(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 23)
    # Stored aggregate (as if UW-fed): net_gex = 10 + (-4) = 6
    g.upsert_rows(
        "SPY",
        [
            {
                "trade_date": md,
                "call_gex": 10.0,
                "put_gex": -4.0,
                "call_delta": 1.0,
                "put_delta": -1.0,
                "payload": {},
            }
        ],
    )
    # Re-derived rows that net to 5 (abs_diff 1, pct ~16.7%)
    diffs = g.compare_to_stored(
        [
            {
                "ticker": "SPY",
                "trade_date": md,
                "call_gex": 7.0,
                "put_gex": -2.0,
                "call_delta": 0.0,
                "put_delta": 0.0,
            }
        ]
    )
    assert len(diffs) == 1
    d = diffs[0]
    assert d["rederived_net_gex"] == pytest.approx(5.0)
    assert d["stored_net_gex"] == pytest.approx(6.0)
    assert d["abs_diff"] == pytest.approx(1.0)
    n = g.insert_validation_rows(date(2026, 5, 24), diffs)
    assert n == 1


def test_compare_to_stored_skips_null_sums(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 25)
    g.upsert_rows(
        "SPY",
        [
            {
                "trade_date": md,
                "call_gex": 1.0,
                "put_gex": -1.0,
                "call_delta": 0.0,
                "put_delta": 0.0,
                "payload": {},
            }
        ],
    )
    # All-NULL-strike day -> SUM(call_gex)/SUM(put_gex) come back None. Must NOT
    # crash on float(None); the row is simply skipped (nothing to compare).
    diffs = g.compare_to_stored(
        [
            {
                "ticker": "SPY",
                "trade_date": md,
                "call_gex": None,
                "put_gex": None,
                "call_delta": None,
                "put_delta": None,
            }
        ]
    )
    assert diffs == []
