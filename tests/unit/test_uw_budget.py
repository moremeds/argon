"""Unit tests for the UW daily-budget governor (pure decision logic)."""

from __future__ import annotations

from uw_scan.sources.uw_budget import (
    BudgetLimits,
    BudgetSnapshot,
    bucket_spend,
    may_spend,
    pool_for_job,
)

LIMITS = BudgetLimits(
    live_ceiling=80_000,
    research_ceiling=30_000,
    total_guard=105_000,
    enabled=True,
)


def test_pool_for_job_classifies_live_vs_research() -> None:
    assert pool_for_job("full_scan") == "live"
    assert pool_for_job("full_scan_hot") == "live"
    assert pool_for_job("rescan_tick") == "live"
    # regime / capture / backfill / unknown all fall to research
    assert pool_for_job("regime_gex_scan") == "research"
    assert pool_for_job("market_tide_backfill") == "research"
    assert pool_for_job(None) == "research"
    assert pool_for_job("something_new") == "research"


def test_live_allowed_below_ceiling() -> None:
    snap = BudgetSnapshot(
        live_spent=40_000, research_spent=10_000, account_count=50_000
    )
    assert may_spend("live", snap, LIMITS) is True


def test_live_blocked_at_ceiling() -> None:
    snap = BudgetSnapshot(live_spent=80_000, research_spent=0, account_count=80_000)
    assert may_spend("live", snap, LIMITS) is False


def test_research_yields_before_live() -> None:
    # research over its ceiling but live has room — live keeps going, research stops
    snap = BudgetSnapshot(
        live_spent=20_000, research_spent=30_000, account_count=50_000
    )
    assert may_spend("live", snap, LIMITS) is True
    assert may_spend("research", snap, LIMITS) is False


def test_total_guard_stops_everything() -> None:
    # account-wide counter near the 120k cap → both pools halt, even under ceiling
    snap = BudgetSnapshot(
        live_spent=10_000, research_spent=5_000, account_count=105_000
    )
    assert may_spend("live", snap, LIMITS) is False
    assert may_spend("research", snap, LIMITS) is False


def test_disabled_governor_always_allows() -> None:
    off = BudgetLimits(80_000, 30_000, 105_000, enabled=False)
    snap = BudgetSnapshot(
        live_spent=999_999, research_spent=999_999, account_count=999_999
    )
    assert may_spend("live", snap, off) is True
    assert may_spend("research", snap, off) is True


def test_account_count_none_falls_back_to_pool_spend() -> None:
    # no header captured yet today → guard can't fire, pool ceilings still hold
    snap = BudgetSnapshot(live_spent=79_000, research_spent=0, account_count=None)
    assert may_spend("live", snap, LIMITS) is True
    snap2 = BudgetSnapshot(live_spent=80_000, research_spent=0, account_count=None)
    assert may_spend("live", snap2, LIMITS) is False


def test_bucket_spend_sums_by_pool() -> None:
    rows = [
        ("full_scan", 8000, 60000),
        ("full_scan_hot", 2000, 61000),
        ("regime_gex_scan", 3000, 62000),
        ("market_tide_backfill", 40000, 100000),
        (None, 10, 100010),
    ]
    snap = bucket_spend(rows)
    assert snap.live_spent == 10_000  # full_scan + hot
    assert snap.research_spent == 43_010  # gex + backfill + None
    assert snap.account_count == 100_010  # max header
