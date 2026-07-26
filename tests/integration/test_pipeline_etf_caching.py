"""Pipeline-side tests for the ETF AUM cache helper (A1 from backend code
review addendum, REQUIRED per Codex review ISSUE-6).

Repo-level tests in tests/integration/storage/test_repository_etf_aum.py
prove the cache table works in isolation. These tests prove the pipeline's
wire-up: cache hit skips the UW call, cache miss fetches + upserts, fetch
failures degrade gracefully, and we don't write spurious None aum values.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from uw_scan.pipeline import _get_or_fetch_etf_aum
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


class _StubClient:
    """Stand-in for UwClient. _get_or_fetch_etf_aum only passes it through to
    uw_sources.fetch_etf_info, which is monkeypatched in each test."""


class _StubEtfInfo:
    def __init__(self, aum: Decimal | None) -> None:
        self.aum = aum


def test_get_or_fetch_etf_aum_returns_cached_when_fresh(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache hit — MUST NOT call UW."""
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))

    def _should_not_call(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fetch_etf_info called despite fresh cache")

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _should_not_call)

    out = _get_or_fetch_etf_aum(ticker="SPY", repo=repo, client=_StubClient(), run_id=1)
    assert out == Decimal("500000000000")


def test_get_or_fetch_etf_aum_fetches_and_upserts_on_miss(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache miss — calls UW, upserts result, returns it. A second call
    within TTL must hit the cache (no second UW call)."""
    call_count = {"n": 0}

    def _fake_fetch(*args: Any, **kwargs: Any) -> _StubEtfInfo:
        call_count["n"] += 1
        return _StubEtfInfo(aum=Decimal("465904858198"))  # QQQ, 2026-07-24 probe

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _fake_fetch)

    out = _get_or_fetch_etf_aum(ticker="QQQ", repo=repo, client=_StubClient(), run_id=1)
    assert out == Decimal("465904858198")
    assert call_count["n"] == 1

    # Verify upsert landed.
    cached = repo.get_recent_etf_aum("QQQ", max_age=timedelta(days=7))
    assert cached == Decimal("465904858198")

    # Second call within TTL must NOT increment counter.
    out2 = _get_or_fetch_etf_aum(
        ticker="QQQ", repo=repo, client=_StubClient(), run_id=1
    )
    assert out2 == Decimal("465904858198")
    assert call_count["n"] == 1


def test_get_or_fetch_etf_aum_returns_none_when_fetch_raises(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch failure must NOT raise — returns None so the scan continues."""

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("UW 500")

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _boom)

    out = _get_or_fetch_etf_aum(ticker="ZZZ", repo=repo, client=_StubClient(), run_id=1)
    assert out is None

    # And we did NOT cache a None value.
    assert repo.get_recent_etf_aum("ZZZ", max_age=timedelta(days=7)) is None


def test_get_or_fetch_etf_aum_no_cache_write_when_uw_returns_none_aum(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If UW returns an ETF row with aum=None, we MUST NOT cache it (would
    permanently demote the ticker until the bogus row aged out)."""

    def _fake_fetch(*args: Any, **kwargs: Any) -> _StubEtfInfo:
        return _StubEtfInfo(aum=None)

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _fake_fetch)

    out = _get_or_fetch_etf_aum(ticker="ZZZ", repo=repo, client=_StubClient(), run_id=1)
    assert out is None
    assert repo.get_recent_etf_aum("ZZZ", max_age=timedelta(days=7)) is None
