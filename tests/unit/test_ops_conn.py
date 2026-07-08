"""Regression guard for ops_health._ops_conn Settings loading.

_ops_conn must build its DSN from `Settings.from_env()`. Bare `Settings()`
raises ValidationError (plain BaseModel, required api_key, never reads env),
which the scheduler failure-listener silently swallows -> job_failures never
written -> /api/health streak block always empty. The integration tests
monkeypatch `_ops_conn`, so the real Settings-loading line is only covered
here.
"""


def test_ops_conn_builds_dsn_via_from_env(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "dummy")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")

    import psycopg

    captured: dict[str, str] = {}
    monkeypatch.setattr(psycopg, "connect", lambda dsn, **_k: captured.update(dsn=dsn))

    from uw_scan.storage.ops_health import _ops_conn

    _ops_conn()  # raises if the code path uses bare Settings()
    assert "dbname=option_wizard_local" in captured["dsn"]
