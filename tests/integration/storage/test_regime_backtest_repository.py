"""Round-trip test for RegimeBacktestRepository against pytest-postgresql.

Uses the existing seeded_db_empty_cards fixture from tests/integration/conftest.py
which applies scripts/migrate.sh (including migration 057) to the test DB.
"""

from __future__ import annotations

from datetime import date


def test_insert_then_find_latest_round_trip(seeded_db_empty_cards) -> None:
    """insert_run -> bulk_insert_daily -> mark_run_completed -> find_latest_run."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)

    run_id = rb.insert_run(
        indicator="cri",
        composite_version="3",
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=4873,
        params={"rolling_window": 150},
        summary={
            "oos": {
                "as_of": "2026-05-25",
                "notebook": "scripts/backtest_cri.py",
                "method": "Forward-drawdown labels...",
                "labels": [{"name": "label_dd5", "definition": "..."}],
                "scores": [{"model": "CRI v3", "auc_dd5": 0.6343, "auc_dd10": 0.6329}],
                "versions": [{"label": "CRI v3", "version": 3, "auc_dd5": 0.6343}],
                "interpretation": "Test.",
            },
            "extras": {"fired_count": 47},
        },
        note="round-trip test",
    )
    assert isinstance(run_id, int) and run_id > 0

    # find_latest_run filters on completed_at IS NOT NULL — must return None
    # until mark_run_completed fires.
    assert rb.find_latest_run("cri", composite_version="3") is None, (
        "find_latest_run must NOT return rows where completed_at IS NULL — "
        "this guard prevents the deploy-order outage from the spec §10.4"
    )

    rb.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": date(2008, 9, 15),
                "score": 78.0,
                "level": "CRITICAL",
                "payload": {"vix": 31.7, "vvix": 110.0, "fired": True},
            },
            {
                "trade_date": date(2020, 3, 16),
                "score": 97.0,
                "level": "CRITICAL",
                "payload": {"vix": 82.69, "vvix": 195.0, "fired": True},
            },
        ],
    )
    rb.mark_run_completed(run_id)

    latest = rb.find_latest_run("cri", composite_version="3")
    assert latest is not None
    assert latest["id"] == run_id
    assert latest["composite_version"] == "3"
    assert latest["window_days"] == 150
    assert latest["summary"]["extras"]["fired_count"] == 47

    daily = rb.fetch_daily_for_run(run_id)
    assert len(daily) == 2
    assert daily[0]["trade_date"] == date(2008, 9, 15)
    assert daily[0]["level"] == "CRITICAL"
    assert daily[0]["payload"]["fired"] is True


def test_find_latest_run_filters_to_current_composite_version_by_default(
    seeded_db_empty_cards,
) -> None:
    """Experimental runs at non-production composite_version must NOT surface."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)

    prod_id = rb.insert_run(
        indicator="cri",
        composite_version="3",
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=10,
        params={},
        summary={"oos": None, "extras": {}},
    )
    rb.bulk_insert_daily(
        prod_id,
        [
            {
                "trade_date": date(2026, 5, 15),
                "score": 12.0,
                "level": "LOW",
                "payload": {},
            }
        ],
    )
    rb.mark_run_completed(prod_id)

    exp_id = rb.insert_run(
        indicator="cri",
        composite_version="4-candidate",
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=10,
        params={},
        summary={"oos": None, "extras": {}},
    )
    rb.bulk_insert_daily(
        exp_id,
        [
            {
                "trade_date": date(2026, 5, 15),
                "score": 18.0,
                "level": "ELEVATED",
                "payload": {},
            }
        ],
    )
    rb.mark_run_completed(exp_id)

    # Default: filters on current production composite_version ("3").
    default = rb.find_latest_run("cri", composite_version="3")
    assert default is not None
    assert default["id"] == prod_id

    # Explicit experimental query opt-in.
    exp = rb.find_latest_run("cri", composite_version="4-candidate")
    assert exp is not None
    assert exp["id"] == exp_id
