"""Regime live-scan settings — defaults + env parsing."""

from __future__ import annotations

from uw_scan.config import Settings


def test_regime_live_defaults(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-dummy")
    for var in (
        "REGIME_WS_SYMBOLS",
        "REGIME_LIVE_SCAN_INTERVAL_MINUTES",
        "REGIME_LIVE_QUOTE_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.regime_ws_symbols == ["VIX", "VVIX", "VIX3M", "COR1M", "SPX", "HYG"]
    assert s.regime_live_scan_interval_minutes == 5
    assert s.regime_live_quote_max_age_seconds == 900


def test_regime_live_env_overrides(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-dummy")
    monkeypatch.setenv("REGIME_WS_SYMBOLS", "VIX,HYG")
    monkeypatch.setenv("REGIME_LIVE_SCAN_INTERVAL_MINUTES", "2")
    monkeypatch.setenv("REGIME_LIVE_QUOTE_MAX_AGE_SECONDS", "300")
    s = Settings.from_env()
    assert s.regime_ws_symbols == ["VIX", "HYG"]
    assert s.regime_live_scan_interval_minutes == 2
    assert s.regime_live_quote_max_age_seconds == 300
