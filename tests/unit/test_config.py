from uw_scan.config import Settings


def test_macro_policy_ingest_flags_default_off():
    settings = Settings(api_key="dummy")

    assert settings.macro_fomc_ingest_enabled is False
    assert settings.macro_sep_ingest_enabled is False
    assert settings.macro_sme_ingest_enabled is False


def test_macro_policy_ingest_flags_read_env(tmp_path, monkeypatch):
    for key in (
        "UW_SCAN_API_KEY",
        "UW_SCAN_MACRO_FOMC_INGEST_ENABLED",
        "UW_SCAN_MACRO_SEP_INGEST_ENABLED",
        "UW_SCAN_MACRO_SME_INGEST_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UW_SCAN_API_KEY=dummy-uw",
                "UW_SCAN_MACRO_FOMC_INGEST_ENABLED=1",
                "UW_SCAN_MACRO_SEP_INGEST_ENABLED=true",
                "UW_SCAN_MACRO_SME_INGEST_ENABLED=yes",
            ]
        )
    )

    settings = Settings.from_env(env_path=env_path)

    assert settings.macro_fomc_ingest_enabled is True
    assert settings.macro_sep_ingest_enabled is True
    assert settings.macro_sme_ingest_enabled is True


def test_trade_insights_ai_default_timeout_matches_deep_prompt_budget():
    settings = Settings(
        api_key="dummy",
    )

    assert settings.trade_insights_ai_timeout_seconds == 300.0


def test_uw_alpha_capture_flag_default_off():
    assert Settings(api_key="dummy").uw_alpha_capture_enabled is False


def test_uw_alpha_capture_flag_reads_env(tmp_path, monkeypatch):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)
    monkeypatch.delenv("UW_SCAN_UW_ALPHA_CAPTURE_ENABLED", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "UW_SCAN_API_KEY=dummy-uw\nUW_SCAN_UW_ALPHA_CAPTURE_ENABLED=1\n"
    )
    assert Settings.from_env(env_path=env_path).uw_alpha_capture_enabled is True


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
