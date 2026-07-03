from __future__ import annotations

from datetime import date

from uw_scan.storage.backtest_repository import BacktestRepository


def test_run_and_results_roundtrip(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)
    run_id = repo.create_run(
        strategy="vrp_macro_sweep",
        reproduce_cmd="uv run python scripts/_vrp_macro_param_sweep.py",
        params_grid={"short_delta": [0.25, 0.30]},
        data_start=date(2006, 1, 3),
        data_end=date(2026, 6, 30),
        notes="test",
    )
    assert isinstance(run_id, int)
    rid1 = repo.insert_result(
        run_id,
        config={"short_delta": 0.25, "hold_days": 30, "sizing": "ramp+"},
        metrics={"sharpe": 1.65, "maxdd": -0.12},
        gates={"survives_walkforward": True},
        n_trades=210,
    )
    rid2 = repo.insert_result(
        run_id,
        config={"short_delta": 0.30},
        status="error",
        error="ValueError('no solution')",
    )
    assert rid2 > rid1
    repo.complete_run(run_id)
    rows = repo.fetch_run_results(run_id)
    assert len(rows) == 2
    assert rows[0]["config"]["sizing"] == "ramp+"
    assert float(rows[0]["metrics"]["sharpe"]) == 1.65
    assert rows[1]["status"] == "error" and rows[1]["metrics"] is None


def test_complete_run_sets_status(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)
    run_id = repo.create_run(strategy="s", reproduce_cmd="cmd")
    repo.complete_run(run_id, status="error", error="all configs failed")
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT status, error FROM backtest_sweep_runs WHERE id = %s", (run_id,)
        )
        status, error = cur.fetchone()
    assert status == "error" and error == "all configs failed"
