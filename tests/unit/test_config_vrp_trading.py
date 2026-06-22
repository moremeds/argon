from pathlib import Path

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings

_NO_ENV = Path("/nonexistent/.env")  # force from_env to read process env only


def test_vrp_trading_defaults():
    s = Settings(api_key=SecretStr("test"))
    assert s.vrp_hold_days == 20  # trading days; ≈ the harvest peak T+20
    assert s.vrp_short_delta == 0.16
    assert s.vrp_wing_delta == 0.08
    assert 0.0 <= s.vrp_risk_free_rate < 0.20
    assert s.vrp_cost_per_contract == 0.65
    assert s.vrp_slippage_frac == 0.01
    assert s.vrp_slippage_min == 0.05
    assert s.vrp_cost_round_trip is True


def test_vrp_env_override(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "test")
    monkeypatch.setenv("UW_SCAN_VRP_HOLD_DAYS", "30")
    monkeypatch.setenv("UW_SCAN_VRP_SLIPPAGE_MIN", "0.10")
    s = Settings.from_env(env_path=_NO_ENV)
    assert s.vrp_hold_days == 30
    assert s.vrp_slippage_min == 0.10


def test_vrp_delta_ordering_validated():
    with pytest.raises(ValueError):
        Settings(api_key=SecretStr("test"), vrp_wing_delta=0.20, vrp_short_delta=0.16)
