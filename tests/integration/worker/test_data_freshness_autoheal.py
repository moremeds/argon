"""Freshness-monitor autoheal: circuit breaker, no-adapter skip, and the
scoped heal-retrigger wiring (fake HealSpec injection, same pattern as
tests/integration/scripts/test_data_gap_healer_cli.py -- no live providers)."""

from __future__ import annotations

import types
from datetime import date, timedelta

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.worker.jobs.data_freshness_monitor import (
    _autoheal_frozen_tables,
    data_freshness_monitor,
)
from uw_scan.worker.jobs.data_gap_adapters import HealSpec


def _settings(repo, **overrides):
    base = dict(
        db_schema=repo._schema,
        db_host="127.0.0.1",
        db_name="option_wizard_test",
        data_freshness_autoheal_enabled=True,
        data_freshness_autoheal_circuit_breaker_nights=3,
        data_freshness_autoheal_max_uw_calls=500,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _frozen_row(table_name: str, days_stale: int = 30) -> FreshnessRow:
    return FreshnessRow(
        table_name=table_name,
        date_col="date",
        scope="watchlist",
        expected_count=1,
        covered_count=0,
        coverage_pct=0.0,
        max_data_date=date(2026, 6, 1),
        days_stale=days_stale,
        frozen=True,
    )


def _seed_frozen_streak(repo, table_name: str, today: date, nights: int) -> None:
    fresh = DataFreshnessRepository(repo.conn, schema=repo._schema)
    for i in range(1, nights + 1):
        fresh.upsert_snapshot(today - timedelta(days=i), [_frozen_row(table_name)])


def test_autoheal_disabled_by_default_produces_no_summary_key(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    settings = types.SimpleNamespace(
        db_schema=repo._schema, data_freshness_autoheal_enabled=False
    )
    summary = data_freshness_monitor(
        repo=repo, settings=settings, today=date(2026, 7, 2)
    )
    assert "autoheal" not in summary


def test_autoheal_skips_table_without_healer_adapter(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    settings = _settings(repo)
    # pcr_history is freshness_only with no healer_adapter -- nothing to retrigger.
    result = _autoheal_frozen_tables(
        repo, settings, date(2026, 7, 2), [_frozen_row("pcr_history")]
    )
    assert result["skipped_no_adapter"] == ["pcr_history"]
    assert result["healed"] == []
    assert result["circuit_broken"] == []


def test_autoheal_circuit_breaker_stops_retriggering(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    # daily_ohlc frozen for the 3 nights preceding today -- at the
    # circuit_breaker_nights=3 threshold, must not retrigger.
    _seed_frozen_streak(repo, "daily_ohlc", today, nights=3)
    settings = _settings(repo, data_freshness_autoheal_circuit_breaker_nights=3)

    def fail_if_called(*_a, **_k):
        raise AssertionError("heal must not run once the circuit breaker trips")

    specs = {
        "daily_ohlc": HealSpec(
            "daily_ohlc", "massive", "per_ticker_range", fail_if_called
        )
    }
    result = _autoheal_frozen_tables(
        repo, settings, today, [_frozen_row("daily_ohlc")], specs=specs
    )
    assert result["circuit_broken"] == ["daily_ohlc"]
    assert result["healed"] == []


def test_autoheal_retriggers_heal_below_circuit_breaker_threshold(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    # Only 1 prior frozen night -- below the threshold of 3, so this must
    # actually retrigger a scoped heal.
    _seed_frozen_streak(repo, "daily_ohlc", today, nights=1)
    settings = _settings(repo, data_freshness_autoheal_circuit_breaker_nights=3)

    calls: list[str] = []

    def fake_range(ctx, ticker, lo, hi):
        calls.append(ticker)
        with ctx.repo.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {ctx.schema}.daily_ohlc (ticker, date, close, source) "
                "VALUES (%s, %s, 1.0, 'test') ON CONFLICT DO NOTHING",
                (ticker, hi),
            )
        return 1

    specs = {
        "daily_ohlc": HealSpec("daily_ohlc", "massive", "per_ticker_range", fake_range)
    }
    result = _autoheal_frozen_tables(
        repo, settings, today, [_frozen_row("daily_ohlc")], specs=specs
    )
    assert result["circuit_broken"] == []
    assert result["healed"] == ["daily_ohlc"]
