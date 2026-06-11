"""Config tests for the xenon IB realtime WS feed (primary spot source).

Uses a nonexistent env_path to bypass the dev box's .env — verifies pure
defaults from the model (same pattern as test_config_trade_insights_ai.py).
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.config import Settings

NO_ENV = Path("/nonexistent/.env")

_XENON_KEYS = (
    "XENON_WS_ENABLED",
    "XENON_WS_URL",
    "XENON_WS_PORT_FILE",
    "XENON_WS_RETRY_PRIMARY_SECONDS",
    "XENON_WS_QUIET_FAILOVER_SECONDS",
)


def _clear_xenon_env(monkeypatch) -> None:
    for k in _XENON_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-dummy")


def test_xenon_defaults(monkeypatch) -> None:
    _clear_xenon_env(monkeypatch)
    s = Settings.from_env(env_path=NO_ENV)
    assert s.xenon_ws_enabled is False
    assert s.xenon_ws_url == "ws://127.0.0.1:8765"
    assert s.xenon_ws_port_file == "/tmp/xenon-ib-realtime.json"
    assert s.xenon_ws_retry_primary_seconds == 300.0
    assert s.xenon_ws_quiet_failover_seconds == 120.0


def test_xenon_env_overrides(monkeypatch) -> None:
    _clear_xenon_env(monkeypatch)
    monkeypatch.setenv("XENON_WS_ENABLED", "true")
    monkeypatch.setenv("XENON_WS_URL", "ws://100.66.147.98:8765")
    monkeypatch.setenv("XENON_WS_PORT_FILE", "")
    monkeypatch.setenv("XENON_WS_RETRY_PRIMARY_SECONDS", "60")
    monkeypatch.setenv("XENON_WS_QUIET_FAILOVER_SECONDS", "30")
    s = Settings.from_env(env_path=NO_ENV)
    assert s.xenon_ws_enabled is True
    assert s.xenon_ws_url == "ws://100.66.147.98:8765"
    assert s.xenon_ws_port_file == ""
    assert s.xenon_ws_retry_primary_seconds == 60.0
    assert s.xenon_ws_quiet_failover_seconds == 30.0


def test_ws_spot_enabled_is_or_of_feeds() -> None:
    assert (
        Settings(
            api_key="uw", massive_ws_enabled=False, xenon_ws_enabled=False
        ).ws_spot_enabled
        is False
    )
    assert (
        Settings(
            api_key="uw", massive_ws_enabled=True, xenon_ws_enabled=False
        ).ws_spot_enabled
        is True
    )
    assert (
        Settings(
            api_key="uw", massive_ws_enabled=False, xenon_ws_enabled=True
        ).ws_spot_enabled
        is True
    )
