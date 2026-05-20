"""Smoke tests for scripts/backtest_cri.py — pure-function helpers only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


def _load_backtest_module():
    """Load scripts/backtest_cri.py as a module without invoking main()."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "backtest_cri.py"
    spec = importlib.util.spec_from_file_location("backtest_cri", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compute_cri_for_window_returns_score() -> None:
    bt = _load_backtest_module()
    n = 150
    aligned = {
        "VIX": np.full(n, 14.0),
        "VVIX": np.full(n, 80.0),
        "SPY": np.linspace(400.0, 450.0, n),
        "COR1M": np.full(n, 20.0),
    }
    common_dates = [f"2020-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    payload = bt.compute_cri_for_window(aligned, common_dates)
    assert "cri" in payload
    assert 0 <= payload["cri"]["score"] <= 100
    # Calm regime: should be very low
    assert payload["cri"]["score"] < 10


def test_summarize_distribution_has_required_keys() -> None:
    bt = _load_backtest_module()
    scores = [0.5, 1.0, 4.0, 12.0, 25.0, 50.0, 75.0, 90.0]
    summary = bt.summarize_distribution(scores)
    for key in ("mean", "p25", "p50", "p75", "p90", "p95", "level_counts"):
        assert key in summary
    # Band boundaries: LOW < 25, ELEVATED < 50, HIGH < 75, CRITICAL >= 75
    # 0.5, 1.0, 4.0, 12.0 → LOW (4)
    # 25.0 → ELEVATED (1)
    # 50.0 → HIGH (1)
    # 75.0, 90.0 → CRITICAL (2)
    assert summary["level_counts"]["LOW"] == 4
    assert summary["level_counts"]["ELEVATED"] == 1
    assert summary["level_counts"]["HIGH"] == 1
    assert summary["level_counts"]["CRITICAL"] == 2
