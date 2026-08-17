"""Adapters over entrypoints that were already date-aware (E5).

Every writer wrapped here already accepted the date (or already recomputes its
full history). The registry refused all of them on one copy-pasted assumption
that round 1 measured false on 2026-08-16.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget


def _ctx(repo, settings) -> HealContext:
    return HealContext(
        repo=repo,
        gap=None,
        schema=repo._schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )


@pytest.mark.parametrize(
    "adapter,module,provider",
    [
        ("cri_recover", "uw_scan.scanners.cri", "db"),
        ("vcg_recover", "uw_scan.scanners.vcg", "db"),
        ("canary_recover", "uw_scan.scanners.canary", "db"),
    ],
)
def test_recover_adapter_forwards_the_lookback(
    seeded_db_empty_cards, monkeypatch, adapter, module, provider
) -> None:
    seen: dict = {}

    def _fake(conn, schema="uw_scan", **kw):
        seen["schema"] = schema
        seen["lookback_days"] = kw["lookback_days"]
        return {"checked": 3, "filled": 2, "skipped": 1}

    monkeypatch.setattr(f"{module}.recover_recent_gaps", _fake)
    settings = Settings.from_env()
    repo = seeded_db_empty_cards
    spec = HEAL_SPECS[adapter]
    assert (spec.granularity, spec.provider) == ("run_once_lookback", provider)

    assert spec.run(_ctx(repo, settings), 9) == 2
    assert seen == {"schema": repo._schema, "lookback_days": 9}


@pytest.mark.parametrize(
    "adapter,target",
    [
        ("market_tide", "uw_scan.scanners.market_tide.run"),
        ("top_net_impact", "uw_scan.scanners.top_net_impact.run"),
    ],
)
def test_per_date_adapter_forwards_the_trading_date(
    seeded_db_empty_cards, monkeypatch, adapter, target
) -> None:
    seen: dict = {}

    def _fake(client, repo, **kw):
        seen.update(kw)
        return 81

    monkeypatch.setattr(target, _fake)
    settings = Settings.from_env()
    ctx = _ctx(seeded_db_empty_cards, settings)
    ctx._uw = object()

    # strict_session gap items carry ticker=None — pass what production passes.
    assert HEAL_SPECS[adapter].run(ctx, None, date(2026, 8, 12)) == 81
    assert seen["trading_date"] == date(2026, 8, 12)


def test_market_tide_backfill_does_not_stamp_a_live_spot(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """A current spot against a past bar is fabricated history, not a backfill."""
    seen: dict = {}
    monkeypatch.setattr(
        "uw_scan.scanners.market_tide.run",
        lambda client, repo, **kw: seen.update(kw) or 81,
    )
    settings = Settings.from_env()
    ctx = _ctx(seeded_db_empty_cards, settings)
    ctx._uw = object()

    HEAL_SPECS["market_tide"].run(ctx, None, date(2026, 8, 12))
    assert seen["capture_spot"] is False


def test_the_calendar_reference_is_healable(seeded_db_empty_cards) -> None:
    """The audit's own spine reference must have a heal path, or an outage that
    truncates it can never be repaired unattended."""
    from uw_scan.reports.data_gap_healer import _REFERENCE_CALENDAR, REGISTRY

    ref = _REFERENCE_CALENDAR[0]  # market_tide_sentiment_daily
    by_name = {e.table_name: e for e in REGISTRY}
    assert by_name[ref].healer_adapter, f"{ref} (the spine) has no heal path"
    # ...and so must the dataset IT derives from.
    assert by_name["market_tide_snapshots"].healer_adapter
