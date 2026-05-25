"""R2 settings are parsed from env vars; absent vars become None."""

from __future__ import annotations

from uw_scan.config import Settings


def test_r2_settings_present_when_env_set(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")
    monkeypatch.setenv("R2_ACCOUNT_ID", "abcd1234")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "market-data")
    s = Settings.from_env(env)
    assert s.r2_account_id == "abcd1234"
    assert s.r2_access_key_id is not None
    assert s.r2_access_key_id.get_secret_value() == "key-id"
    assert s.r2_secret_access_key is not None
    assert s.r2_secret_access_key.get_secret_value() == "secret"
    assert s.r2_bucket == "market-data"
    assert s.r2_endpoint_override is None


def test_r2_settings_none_when_env_unset(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")
    for k in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_ENDPOINT_OVERRIDE",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(env)
    assert s.r2_account_id is None
    assert s.r2_access_key_id is None
    assert s.r2_secret_access_key is None
    assert s.r2_bucket is None
    assert s.r2_endpoint_override is None
