"""Unit tests for the /stock response cache helper (_assemble_cached).

Covers the three behaviours that make it safe on the hot path: a hit reuses
the assembled report (no re-derivation), the returned object is an isolated
copy (so the router's in-place spot mutation can't corrupt the cache), and a
zero TTL disables caching entirely.
"""

from __future__ import annotations

from uw_scan.api.routers import stock as stock_router


def _fake_report(spot):
    from uw_scan.models import SingleStockReport

    # Build via the assembler's model to get a real, mutable instance without a DB.
    report = SingleStockReport.model_construct(ticker="TSLA")
    report.market_structure = type("MS", (), {"spot": spot})()
    return report


def test_hit_dedups_and_returns_isolated_copy(monkeypatch):
    stock_router._report_cache_clear()
    monkeypatch.setattr(stock_router, "_REPORT_CACHE_TTL_S", 60.0)

    calls = {"n": 0}

    def _fake_assemble(ticker, run_id, repo):
        calls["n"] += 1
        return _fake_report(spot=100)

    monkeypatch.setattr(stock_router, "assemble_single_stock_report", _fake_assemble)

    first = stock_router._assemble_cached("TSLA", 1, repo=None)
    second = stock_router._assemble_cached("TSLA", 1, repo=None)

    assert calls["n"] == 1, "second call must hit the cache, not re-assemble"
    assert first is not second, "each caller gets its own copy"

    stats = stock_router.report_cache_stats()
    assert stats["misses"] == 1 and stats["hits"] == 1
    assert stats["hit_rate"] == 0.5

    # Mutating a returned copy (as _with_latest_spot does) must not leak into
    # the cache: a fresh call still sees the pristine value.
    first.market_structure.spot = 999
    third = stock_router._assemble_cached("TSLA", 1, repo=None)
    assert third.market_structure.spot == 100
    stock_router._report_cache_clear()


def test_zero_ttl_disables_cache(monkeypatch):
    stock_router._report_cache_clear()
    monkeypatch.setattr(stock_router, "_REPORT_CACHE_TTL_S", 0.0)

    calls = {"n": 0}

    def _fake_assemble(ticker, run_id, repo):
        calls["n"] += 1
        return _fake_report(spot=100)

    monkeypatch.setattr(stock_router, "assemble_single_stock_report", _fake_assemble)

    stock_router._assemble_cached("TSLA", 1, repo=None)
    stock_router._assemble_cached("TSLA", 1, repo=None)
    assert calls["n"] == 2, "TTL<=0 must bypass the cache every call"


def test_distinct_run_ids_are_separate_keys(monkeypatch):
    stock_router._report_cache_clear()
    monkeypatch.setattr(stock_router, "_REPORT_CACHE_TTL_S", 60.0)

    calls = {"n": 0}

    def _fake_assemble(ticker, run_id, repo):
        calls["n"] += 1
        return _fake_report(spot=run_id)

    monkeypatch.setattr(stock_router, "assemble_single_stock_report", _fake_assemble)

    a = stock_router._assemble_cached("TSLA", 1, repo=None)
    b = stock_router._assemble_cached("TSLA", 2, repo=None)
    assert calls["n"] == 2
    assert a.market_structure.spot == 1
    assert b.market_structure.spot == 2
    stock_router._report_cache_clear()
