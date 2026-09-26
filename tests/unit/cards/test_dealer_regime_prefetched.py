"""gather_inputs reuses rows the report already read — but only for the same run."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from uw_scan.cards import dealer_regime as mod


class _Repo:
    def __init__(self, latest: int):
        self.calls: list[str] = []
        self._latest = latest
        self.conn = SimpleNamespace()
        self._schema = "uw_scan"

    def latest_run_id(self, _t):
        self.calls.append("latest_run_id")
        return self._latest

    def get_strike_gex_curve(self, _run):
        self.calls.append("get_strike_gex_curve")
        return []

    def fetch_exposures_summary(self, _run, _t):
        self.calls.append("fetch_exposures_summary")
        return []

    def fetch_realized_vol_latest(self, _t):
        self.calls.append("fetch_realized_vol_latest")
        return {"price": 100.0}

    def fetch_exposures_aggregate(self, _run, _t):
        self.calls.append("fetch_exposures_aggregate")
        return {"total_call_gex": 1.0, "total_put_gex": -0.5}


PRE = {
    "run_id": 7,
    "strike_gex_curve": [],
    "exposures_summary": [],
    "realized_vol": {"price": 100.0},
    "exposures_aggregate": {"total_call_gex": 1.0, "total_put_gex": -0.5},
}


def _gather(repo, prefetched):
    fake_hist = SimpleNamespace(fetch_history=lambda _t, days: [])
    with patch(
        "uw_scan.storage.greek_exposure_repository.GreekExposureDailyRepository",
        lambda *_a, **_k: fake_hist,
    ):
        return mod.gather_inputs(repo, ticker="AAPL", today=date(2026, 9, 25), prefetched=prefetched)


def test_same_run_skips_the_four_reads():
    repo = _Repo(latest=7)
    out = _gather(repo, PRE)
    assert out["run_id"] == 7
    assert out["spot"] == 100.0 and out["net_gex"] == 0.5
    assert repo.calls == ["latest_run_id"]


def test_different_run_ignores_prefetched_rows():
    repo = _Repo(latest=8)
    _gather(repo, PRE)
    assert set(repo.calls) == {
        "latest_run_id",
        "get_strike_gex_curve",
        "fetch_exposures_summary",
        "fetch_realized_vol_latest",
        "fetch_exposures_aggregate",
    }


def test_no_prefetched_is_unchanged():
    repo = _Repo(latest=7)
    _gather(repo, None)
    assert repo.calls.count("get_strike_gex_curve") == 1
