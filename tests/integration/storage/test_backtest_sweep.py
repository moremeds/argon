# tests/integration/storage/test_backtest_sweep.py
from __future__ import annotations

from uw_scan.backtest.sweep import run_sweep
from uw_scan.storage.backtest_repository import BacktestRepository


def test_run_sweep_end_to_end_with_nan_and_failure(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)

    def run_one(cfg):
        if cfg["hold_days"] == 14:
            raise RuntimeError("no data")
        sharpe = float("nan") if cfg["hold_days"] == 7 else 1.2
        return {"metrics": {"sharpe": sharpe, "maxdd": -0.1}, "n_trades": 5}

    out = run_sweep(
        [{"hold_days": 7}, {"hold_days": 14}, {"hold_days": 30}],
        run_one,
        repo=repo,
        strategy="itest",
        reproduce_cmd="uv run pytest tests/integration/storage/test_backtest_sweep.py",
        params_grid={"hold_days": [7, 14, 30]},
    )
    rows = repo.fetch_run_results(out["run_id"])
    assert [r["status"] for r in rows] == ["ok", "error", "ok"]
    assert (
        rows[0]["metrics"]["sharpe"] is None
    )  # nan persisted as null, jsonb accepted it
    assert rows[2]["metrics"]["sharpe"] == 1.2
    assert "RuntimeError" in rows[1]["error"]
