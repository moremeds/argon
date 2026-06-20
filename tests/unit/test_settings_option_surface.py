from __future__ import annotations

from uw_scan.config import Settings


def test_settings_reads_option_surface_flags(monkeypatch, tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "x")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    monkeypatch.setenv("OPTION_SURFACE_CAPTURE_ENABLED", "false")
    monkeypatch.setenv("OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD", "0.05")

    s = Settings.from_env(env_path=env)

    assert s.option_surface_capture_enabled is False
    assert s.option_surface_iv_canary_enabled is True  # default
    assert s.option_surface_iv_canary_warn_threshold == 0.05
    assert s.xenon_query_api_url == "http://127.0.0.1:8421"  # default
    assert s.xenon_query_api_key is None  # unset -> None
