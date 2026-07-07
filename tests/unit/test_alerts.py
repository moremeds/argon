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
