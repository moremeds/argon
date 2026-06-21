from __future__ import annotations

from datetime import date


def test_upsert_and_fetch_vrp_harvest_verdict(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.031,
        mean_holdout=0.028,
        rich_cheap_spread=0.015,
        n=42,
        n_holdout=17,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 6, 21),
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_harvest_verdicts()
    assert len(rows) == 1
    r = rows[0]
    assert r["asset_class"] == "single_name"
    assert r["deviation_class"] == "RICH"
    assert r["verdict"] == "HARVEST_SELLABLE"
    assert float(r["mean_realized_vrp"]) == 0.031
    assert r["n"] == 42
    assert r["survives_walkforward"] is True


def test_upsert_vrp_harvest_verdict_is_idempotent(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    for verdict in ("NONE", "HARVEST_SELLABLE"):
        repo.upsert_vrp_harvest_verdict(
            asset_class="index_macro",
            deviation_class="RICH",
            verdict=verdict,
            mean_realized_vrp=0.05,
            mean_holdout=0.04,
            rich_cheap_spread=0.02,
            n=30,
            n_holdout=12,
            survives_walkforward=True,
            survives_window_gate=True,
            confidence="med",
            as_of=date(2026, 6, 21),
        )
    repo.conn.commit()
    rows = repo.fetch_vrp_harvest_verdicts()
    assert len(rows) == 1  # same PK overwrites
    assert rows[0]["verdict"] == "HARVEST_SELLABLE"


def test_fetch_known_earnings_dates_distinct_set(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    # flow_events requires run_id (FK -> scan_runs) + alert_id (NOT NULL),
    # UNIQUE(run_id, alert_id). Seed rows recording the "next earnings" as it
    # rolled forward over time (proven pattern: test_skew_storage.py:101).
    run_id = repo.insert_scan_run(ticker="TESTX")
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date) VALUES "
            "(%s, 'a1', 'TESTX', %s), "
            "(%s, 'a2', 'TESTX', %s), "
            "(%s, 'a3', 'TESTX', %s), "
            "(%s, 'a4', 'TESTX', %s)",
            (
                run_id,
                date(2026, 1, 28),
                run_id,
                date(2026, 1, 28),  # duplicate date, distinct alert_id
                run_id,
                date(2026, 4, 29),
                run_id,
                None,  # null earnings → excluded by the query
            ),
        )
    repo.conn.commit()
    got = repo.fetch_known_earnings_dates("testx")  # case-insensitive
    assert got == {date(2026, 1, 28), date(2026, 4, 29)}
    assert repo.fetch_known_earnings_dates("NOPE") == set()
