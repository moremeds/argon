from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "backfill"
        / "uw_long_weekend_history_backfill.py"
    )
    spec = importlib.util.spec_from_file_location("uw_long_weekend_history_backfill", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_market_sessions_skip_weekends_and_nyse_holidays():
    mod = _load_module()

    sessions = mod.market_sessions(date(2026, 6, 18), date(2026, 6, 22))

    assert sessions == [date(2026, 6, 18), date(2026, 6, 22)]


def test_estimate_requests_for_dataset_mix():
    mod = _load_module()

    estimate = mod.estimate_requests(
        ["market_tide", "top_net_impact", "gex_levels", "flow_bars", "dark_lit"],
        ticker_count=103,
        session_count=2,
    )

    assert estimate["market_tide"] == 2
    assert estimate["top_net_impact"] == 2
    assert estimate["gex_levels"] == 206
    assert estimate["flow_bars"] == 412
    assert estimate["dark_lit"] == 412
    assert estimate["total_estimated_requests"] == 1034

