from uw_scan.config import Settings


def test_defaults(monkeypatch):
    for k in (
        "UW_SCAN_TECHNICAL_LIVE_ENABLED",
        "TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES",
        "TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.technical_live_enabled is False
    assert s.technical_live_scan_interval_minutes == 5
    assert s.technical_live_quote_max_age_seconds == 900


def test_env_override(monkeypatch):
    monkeypatch.setenv("UW_SCAN_TECHNICAL_LIVE_ENABLED", "true")
    monkeypatch.setenv("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES", "3")
    s = Settings.from_env()
    assert s.technical_live_enabled is True
    assert s.technical_live_scan_interval_minutes == 3
