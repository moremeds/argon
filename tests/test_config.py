from uw_scan.config import UwScanConfig


def test_config_defaults_do_not_contain_secret_token(monkeypatch):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)

    config = UwScanConfig.from_env(dotenv_path="missing-test.env")

    assert config.api_key is None
    assert config.db_name == "option_wizard"
    assert config.db_schema == "uw_scan"
    assert config.max_requests_per_cycle == 250
    assert config.max_deep_surface_tickers == 8
    assert config.max_analysis_tickers == 3


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "runtime-token")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_PORT", "5544")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard")
    monkeypatch.setenv("UW_SCAN_DB_USER", "moremeds")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("UW_SCAN_POLL_SECONDS", "45")
    monkeypatch.setenv("UW_SCAN_MAX_REQUESTS_PER_CYCLE", "120")
    monkeypatch.setenv("UW_SCAN_MAX_ANALYSIS_TICKERS", "4")

    config = UwScanConfig.from_env(dotenv_path="missing-test.env")

    assert config.api_key == "runtime-token"
    assert config.db_host == "127.0.0.1"
    assert config.db_port == 5544
    assert config.db_user == "moremeds"
    assert config.db_password == "secret"
    assert config.poll_seconds == 45
    assert config.max_requests_per_cycle == 120
    assert config.max_analysis_tickers == 4


def test_config_reads_dotenv_without_printing_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath(".env").write_text("UW_SCAN_API_KEY=dotenv-token\nUW_SCAN_POLL_SECONDS=30\n")

    config = UwScanConfig.from_env()

    assert config.api_key == "dotenv-token"
    assert config.poll_seconds == 30
