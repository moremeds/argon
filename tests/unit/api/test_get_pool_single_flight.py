"""get_pool() must build exactly one pool when the first requests race."""

import threading
import time

from uw_scan.api import deps


def test_concurrent_first_calls_open_one_pool(monkeypatch):
    built = []

    def fake_pool(*_args, **_kwargs):
        built.append(object())
        time.sleep(0.05)  # widen the window the unlocked lru_cache lost
        return built[-1]

    monkeypatch.setattr(deps, "ConnectionPool", fake_pool)
    monkeypatch.setattr(deps, "get_settings", lambda: type("S", (), {"db_dsn": lambda self: "x"})())
    deps._open_pool.cache_clear()
    try:
        threads = [threading.Thread(target=deps.get_pool) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(built) == 1
    finally:
        deps._open_pool.cache_clear()
