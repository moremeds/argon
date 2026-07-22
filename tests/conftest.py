from __future__ import annotations

import os

import pytest


def pytest_configure() -> None:
    # Local safety default: integration fixtures still point at an isolated DB,
    # but developers do not need to prefix every pytest command.
    os.environ.setdefault("UW_SCAN_TEST_DB_NAME", "option_wizard_test")


@pytest.fixture(autouse=True)
def _restore_os_environ():
    """Confine os.environ mutations to the test that made them.

    Settings.from_env() calls _load_dotenv, which copies every key from the repo
    .env / .env.local into os.environ with a *raw* assignment (for keys not
    already set) — not via monkeypatch, so nothing reverts it. The first test to
    call bare from_env() therefore leaks the developer's local dotenv into every
    later test. On a machine whose .env points XENON_QUERY_API_URL at the mini
    (http://100.66.147.98:8321), that leak makes test_settings_option_surface —
    which asserts the *default* url — pass in isolation but fail after any leaker
    runs. CI has no .env, so it never sees this: a purely local false negative.

    Snapshot/restore per test contains any such raw write to its origin.
    monkeypatch already reverts its own changes; this only adds coverage for the
    os.environ writes monkeypatch does not manage. Keys set before the first test
    (e.g. UW_SCAN_TEST_DB_NAME in pytest_configure) are in every snapshot and so
    are preserved, not stripped.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
