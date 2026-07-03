# tests/unit/backtest/test_sweep.py
from __future__ import annotations

from uw_scan.backtest.sweep import json_safe, run_sweep


class _StubRepo:
    def __init__(self):
        self.results = []
        self.completed = None

    def create_run(self, **kw):
        self.run_kw = kw
        return 7

    def insert_result(self, run_id, **kw):
        self.results.append((run_id, kw))
        return len(self.results)

    def complete_run(self, run_id, *, status="completed", error=None):
        self.completed = (run_id, status, error)


def test_json_safe_replaces_non_finite():
    assert json_safe({"a": float("nan"), "b": [1.0, float("inf")], "c": "x"}) == {
        "a": None,
        "b": [1.0, None],
        "c": "x",
    }


def test_run_sweep_persists_each_config_and_survives_failures():
    repo = _StubRepo()

    def run_one(cfg):
        if cfg["x"] == 2:
            raise ValueError("boom")
        return {
            "metrics": {"sharpe": float("nan") if cfg["x"] == 3 else 1.0},
            "n_trades": cfg["x"],
        }

    out = run_sweep(
        [{"x": 1}, {"x": 2}, {"x": 3}],
        run_one,
        repo=repo,
        strategy="s",
        reproduce_cmd="cmd",
    )
    assert out["run_id"] == 7 and out["n_ok"] == 2 and out["n_error"] == 1
    assert len(repo.results) == 3
    assert repo.results[1][1]["status"] == "error"
    assert "ValueError" in repo.results[1][1]["error"]
    assert repo.results[2][1]["metrics"]["sharpe"] is None  # nan sanitized
    assert repo.completed == (7, "completed", None)
    assert len(out["results"]) == 2  # only ok configs returned for in-process use


def test_run_sweep_all_failed_marks_run_error():
    repo = _StubRepo()
    out = run_sweep(
        [{"x": 1}], lambda c: 1 / 0, repo=repo, strategy="s", reproduce_cmd="c"
    )
    assert repo.completed[1] == "error" and out["n_ok"] == 0
