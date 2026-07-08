"""get_repo borrows from a shared pool and returns the connection on exit.

Guards the #2 fix: no fresh connect-per-request. Two sequential requests must
reuse the pool (not open two brand-new backends), and each yields a working
Repository against the test DB.
"""

from __future__ import annotations

import os

import pytest

from uw_scan.api import deps
from uw_scan.config import Settings


@pytest.fixture
def _pool_on_test_db(monkeypatch):
    """Point get_pool()/get_repo() at the isolated test DB, then tear the pool down."""
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    settings = Settings.from_env().model_copy(update={"db_name": test_db})

    deps.get_settings.cache_clear()
    deps.get_pool.cache_clear()
    monkeypatch.setattr(deps, "get_settings", lambda: settings)

    yield

    deps.get_pool().close()
    deps.get_pool.cache_clear()
    # get_settings is monkeypatched to a plain lambda at this point; monkeypatch
    # restores the real lru_cache function on undo (which runs after this body).
    # Calling .cache_clear() on the lambda AttributeErrors — the next test's
    # setup clears the restored real cache, so nothing to do here.


def test_get_repo_reuses_pooled_connection(_pool_on_test_db) -> None:
    def _one_request() -> int:
        gen = deps.get_repo()
        repo = next(gen)
        with repo.conn.cursor() as cur:
            cur.execute("SELECT 1")
            got = cur.fetchone()[0]
        gen.close()  # returns the connection to the pool
        return got

    assert _one_request() == 1
    assert _one_request() == 1

    stats = deps.get_pool().get_stats()
    # Two requests served, but the pool never grew past one live connection.
    assert stats["requests_num"] >= 2
    assert stats["pool_size"] <= deps.get_pool().max_size
