def test_webhook_url_reads_env_via_from_env(monkeypatch):
    # Regression: `_webhook_url` must load Settings via `from_env()` AND
    # `from_env()` must map `UW_SCAN_OPS_ALERT_WEBHOOK_URL`. Both were broken:
    # bare `Settings()` raises (it never reads env) and the field wasn't wired
    # into from_env — so the URL was permanently "". Every other alerts test
    # mocked `_webhook_url`, hiding it. Exercise the real path here.
    monkeypatch.setenv("UW_SCAN_API_KEY", "dummy")
    monkeypatch.setenv(
        "UW_SCAN_DB_HOST", "127.0.0.1"
    )  # keep db-isolation tripwire happy
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    monkeypatch.setenv("UW_SCAN_OPS_ALERT_WEBHOOK_URL", "https://hook.test/x")

    from uw_scan import alerts

    assert alerts._webhook_url() == "https://hook.test/x"


def test_webhook_url_empty_when_env_unset(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "dummy")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    monkeypatch.delenv("UW_SCAN_OPS_ALERT_WEBHOOK_URL", raising=False)

    from uw_scan import alerts

    assert alerts._webhook_url() == ""


def test_send_alert_noop_without_url(monkeypatch):
    from uw_scan import alerts

    monkeypatch.setattr(alerts, "_webhook_url", lambda: "")
    assert alerts.send_alert("t", "m") is False


def test_send_alert_posts_when_configured(monkeypatch):
    from uw_scan import alerts

    posted = {}
    monkeypatch.setattr(alerts, "_webhook_url", lambda: "https://example.test/hook")

    class _Resp:
        status_code = 200

    def _fake_post(url, json, timeout):
        posted["url"] = url
        return _Resp()

    monkeypatch.setattr(alerts.httpx, "post", _fake_post)
    assert alerts.send_alert("worker died", "full_scan streak=3") is True
    assert posted["url"] == "https://example.test/hook"
