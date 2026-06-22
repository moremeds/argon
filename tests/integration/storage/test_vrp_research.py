from __future__ import annotations

from datetime import date


def test_earnings_calendar_includes_massive_filing_date(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # massive_fundamentals.filing_date is the NEW earnings leg (item 3). All other
    # upsert_massive_fundamentals kwargs are optional → omit them.
    repo.upsert_massive_fundamentals(
        ticker="AAPL",
        period_end=date(2024, 12, 28),
        fiscal_period="Q1",
        filing_date=date(2025, 1, 30),
    )
    repo.conn.commit()
    assert date(2025, 1, 30) in repo.fetch_historical_earnings_dates("AAPL")
    # fetch_earnings_events tags the filing-sourced date with the 15-day buffer.
    assert (date(2025, 1, 30), 15) in repo.fetch_earnings_events("AAPL")


def test_earnings_calendar_includes_flow_events(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("AAPL", notes="test")
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date) VALUES (%s, %s, %s, %s)",
            (run_id, "a1", "AAPL", date(2025, 2, 1)),
        )
    repo.conn.commit()
    assert date(2025, 2, 1) in repo.fetch_historical_earnings_dates("AAPL")
    assert (date(2025, 2, 1), 0) in repo.fetch_earnings_events(
        "AAPL"
    )  # flow → buffer 0


def test_price_series_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for i, px in enumerate((100.0, 101.5, 99.5)):
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s, %s, %s)",
                ("AAPL", date(2026, 1, 5 + i), px),
            )
    repo.conn.commit()
    series = repo.fetch_price_series("AAPL")
    assert [round(v, 2) for _, v in series] == [100.0, 101.5, 99.5]


def test_directional_verdict_roundtrip_and_full_rewrite(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_directional_verdict(
        asset_class="single_name",
        horizon=20,
        verdict="BULLISH_TILT",
        mean_differential=0.012,
        mean_holdout=0.009,
        mean_rich_return=0.03,
        mean_cheap_return=0.018,
        n=120,
        n_holdout=48,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 6, 22),
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_directional_verdicts()
    assert len(rows) == 1 and rows[0]["verdict"] == "BULLISH_TILT"
    # full-rewrite: clear drops stale rows
    repo.clear_vrp_directional_verdicts()
    repo.conn.commit()
    assert repo.fetch_vrp_directional_verdicts() == []


def test_rv_validation_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_rv_validation(
        ticker="SPY",
        horizon=20,
        n=200,
        mean_abs_dev=0.015,
        mean_signed_dev=-0.002,
        p95_abs_dev=0.04,
        corr=0.88,
        as_of=date(2026, 6, 22),
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_rv_validation()
    assert len(rows) == 1 and rows[0]["ticker"] == "SPY"
    assert float(rows[0]["corr"]) == 0.88
