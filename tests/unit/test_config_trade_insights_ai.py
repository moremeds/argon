"""Config tests for Trade Insights AI DeepSeek provider.

Uses a nonexistent env_path to bypass the dev box's .env — verifies pure
defaults from the model.
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.config import Settings

NO_ENV = Path("/nonexistent/.env")


def _clear_deepseek_env(monkeypatch) -> None:
    for k in (
        "DEEPSEEK_API_KEY",
        "TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED",
        "TRADE_INSIGHTS_AI_DEEPSEEK_MODEL",
        "TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS",
        "TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-dummy")


def test_settings_parses_deepseek_env(monkeypatch) -> None:
    _clear_deepseek_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-fake")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED", "true")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT", "2")
    settings = Settings.from_env(env_path=NO_ENV)
    assert settings.trade_insights_ai_deepseek_enabled is True
    assert settings.trade_insights_ai_deepseek_model == "deepseek-v4-pro"
    assert settings.trade_insights_ai_deepseek_timeout_seconds == 240.0
    assert settings.trade_insights_ai_deepseek_worker_count == 2
    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "sk-deepseek-fake"


def test_settings_deepseek_defaults_when_env_unset(monkeypatch) -> None:
    _clear_deepseek_env(monkeypatch)
    settings = Settings.from_env(env_path=NO_ENV)
    assert settings.trade_insights_ai_deepseek_enabled is True
    assert settings.trade_insights_ai_deepseek_model == ""
    assert settings.trade_insights_ai_deepseek_timeout_seconds == 300.0
    assert settings.trade_insights_ai_deepseek_worker_count == 2
    assert settings.deepseek_api_key is None
