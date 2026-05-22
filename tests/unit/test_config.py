from uw_scan.config import Settings


def test_trade_insights_ai_default_timeout_matches_deep_prompt_budget():
    settings = Settings(
        api_key="dummy",
    )

    assert settings.trade_insights_ai_timeout_seconds == 300.0


def test_from_env_loads_optional_fred_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UW_SCAN_API_KEY=dummy-uw",
                "FRED_API_KEY=fred-secret",
            ]
        )
    )

    settings = Settings.from_env(env_path=env_path)

    assert settings.api_key.get_secret_value() == "dummy-uw"
    assert settings.fred_api_key is not None
    assert settings.fred_api_key.get_secret_value() == "fred-secret"


def test_from_env_treats_blank_fred_api_key_as_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UW_SCAN_API_KEY=dummy-uw",
                "FRED_API_KEY=   ",
            ]
        )
    )

    settings = Settings.from_env(env_path=env_path)

    assert settings.fred_api_key is None
