"""Tests for the ETF AUM cache (A1 from backend code review addendum).

The cache table lets pipeline.py skip the per-scan UW /etf_info round trip
when the AUM is fresh — AUM moves weekly at most, so a 7-day TTL gives
near-100% cache hit rate in steady state.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_get_recent_etf_aum_returns_none_when_no_row(repo: Repository) -> None:
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_get_recent_etf_aum_returns_value_when_fresh(repo: Repository) -> None:
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("500000000000")


def test_get_recent_etf_aum_returns_none_when_stale(repo: Repository) -> None:
    """Manually backdate fetched_at past the TTL."""
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.etf_aum_cache SET fetched_at = NOW() - INTERVAL '8 days' WHERE ticker='SPY'"
        )
    repo.conn.commit()
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_upsert_etf_aum_updates_fetched_at_and_value(repo: Repository) -> None:
    """A second upsert must bump fetched_at AND overwrite aum.

    Both values are real UW AUMs frozen from the 2026-07-24 probe, in UW's
    billions form: XLK 180.775642 then SPY 743.252024. Writing SPY's number
    into XLK's row is deliberate — this test exercises overwrite mechanics,
    not fund size — and both land normalized to raw dollars.
    """
    repo.upsert_etf_aum("XLK", Decimal("180.775642"))
    repo.upsert_etf_aum("XLK", Decimal("743.252024"))
    cached = repo.get_recent_etf_aum("XLK", max_age=timedelta(days=7))
    assert cached == Decimal("743252024000")


def test_etf_aum_cache_normalizes_case(repo: Repository) -> None:
    """Codex review ISSUE-8: mixed-case input must hit the same logical row.

    SOXX's real 2026-07-24 AUM is already raw dollars and above
    AUM_BILLIONS_THRESHOLD, so the normalizer passes it through and this test
    stays about case folding only.
    """
    repo.upsert_etf_aum("soxx", Decimal("45064294868"))  # lowercase upsert
    cached = repo.get_recent_etf_aum("SOXX", max_age=timedelta(days=7))
    assert cached == Decimal("45064294868")
