"""Freshness-monitor autoheal: circuit breaker, no-adapter skip, and the
scoped heal-retrigger wiring (fake HealSpec injection, same pattern as
tests/integration/scripts/test_data_gap_healer_cli.py -- no live providers)."""

from __future__ import annotations

import types
from datetime import date, timedelta

import psycopg

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.worker.jobs.data_freshness_monitor import (
    _GAP_HEALER_LOCK_KEY,
    AUTOHEAL_LOOKBACK_DAYS,
    _autoheal_frozen_tables,
    data_freshness_monitor,
)
from uw_scan.worker.jobs.data_gap_adapters import HealSpec


def _peer_dsn(conn: psycopg.Connection) -> str:
    """Build a DSN for a second, independent connection to the same test DB
    -- same pattern as test_backfill_vcg_v2.py's advisory-lock test."""
    info = conn.info
    parts = [
        f"host={info.host}" if info.host else "",
        f"port={info.port}" if info.port else "",
        f"dbname={info.dbname}",
        f"user={info.user}",
    ]
    if info.password:
        parts.append(f"password={info.password}")
    return " ".join(p for p in parts if p)


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


def _calendar(repo, *dates: date) -> None:
    """Seed the trading-day reference (market_tide_sentiment_daily) -- the
    sole source audit_into_run's strict_ticker_date mode uses to know which
    sessions are expected. Same helper as
    tests/integration/scripts/test_data_gap_healer_cli.py."""
    with repo.conn.cursor() as cur:
        for d in dates:
            cur.execute(
                f"INSERT INTO {repo._schema}.market_tide_sentiment_daily "
                "(data_date, state, magnitude, driver, momentum, bars) "
                "VALUES (%s, 'BALANCED', 'FLAT', 'x', 'x', 1) ON CONFLICT DO NOTHING",
                (d,),
            )
    repo.conn.commit()


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
    # flow_alerts_daily_rollup is freshness_only with no healer_adapter --
    # nothing to retrigger. (This used to name pcr_history, which gained the
    # pipeline_replay adapter on 2026-08-16 and is no longer adapter-less.)
    result = _autoheal_frozen_tables(
        repo, settings, date(2026, 7, 2), [_frozen_row("flow_alerts_daily_rollup")]
    )
    assert result["skipped_no_adapter"] == ["flow_alerts_daily_rollup"]
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
    # audit_into_run's strict_ticker_date mode needs the trading-day
    # reference calendar (market_tide_sentiment_daily) seeded, or it audits
    # zero expected sessions and claims nothing regardless of watchlist size.
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    _calendar(repo, today)
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
    assert calls, "the fake heal adapter must actually have been invoked"


def test_autoheal_invokes_run_once_lookback_adapter_directly(seeded_db_empty_cards):
    """macro_series_daily (and most of the gold/rates/macro tables) are
    freshness_only/run_once_lookback -- audit() never produces gap items for
    non-strict_* audit modes, so execute_into_run()'s claim-and-dispatch path
    finds nothing to claim and silently no-ops. Autoheal must instead call
    run_refresh_adapters (the same path the nightly job uses for these), or
    the retry is a no-op for the majority of tables this PR added coverage
    for."""
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    _seed_frozen_streak(repo, "macro_series_daily", today, nights=1)
    settings = _settings(repo, data_freshness_autoheal_circuit_breaker_nights=3)

    calls: list[int] = []

    def fake_lookback(ctx, lookback_days):
        calls.append(lookback_days)

    specs = {
        "macro_fred": HealSpec(
            "macro_fred", "external", "run_once_lookback", fake_lookback
        )
    }
    result = _autoheal_frozen_tables(
        repo, settings, today, [_frozen_row("macro_series_daily")], specs=specs
    )
    assert calls == [AUTOHEAL_LOOKBACK_DAYS]
    assert result["circuit_broken"] == []
    assert result["healed"] == ["macro_series_daily"]


def test_autoheal_reports_attempted_no_change_when_adapter_fails(
    seeded_db_empty_cards,
):
    """A heal that runs but doesn't actually fix anything (budget exhausted,
    adapter raises, provider returns nothing) must not be reported as
    'healed' -- that hides real failures from /api/health and the logs."""
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    _seed_frozen_streak(repo, "macro_series_daily", today, nights=1)
    settings = _settings(repo, data_freshness_autoheal_circuit_breaker_nights=3)

    def raises(ctx, lookback_days):
        raise RuntimeError("FRED unreachable")

    specs = {
        "macro_fred": HealSpec("macro_fred", "external", "run_once_lookback", raises)
    }
    result = _autoheal_frozen_tables(
        repo, settings, today, [_frozen_row("macro_series_daily")], specs=specs
    )
    assert result["healed"] == []
    assert result["attempted_no_change"] == ["macro_series_daily"]


def test_end_to_end_monitor_does_not_trip_breaker_one_night_early(
    seeded_db_empty_cards, monkeypatch
):
    """data_freshness_monitor() itself persists tonight's snapshot -- the
    circuit breaker must count only PRIOR nights, or a table with nights-1
    prior frozen nights (one below threshold, which should still retry
    tonight) would see tonight's own just-persisted row on the same
    connection/transaction and trip one night early."""
    import uw_scan.worker.jobs.data_freshness_monitor as mod

    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    # Exactly threshold-1 = 2 PRIOR frozen nights. A same-night-persist-first
    # ordering bug would make consecutive_frozen_counts() see 2 + tonight = 3
    # and trip the breaker; the correct behavior is to still retry tonight.
    _seed_frozen_streak(repo, "daily_ohlc", today, nights=2)

    monkeypatch.setattr(
        mod, "compute_freshness", lambda *a, **kw: [_frozen_row("daily_ohlc")]
    )
    monkeypatch.setattr(
        mod,
        "execute_into_run",
        lambda *a, **kw: (
            1,
            {"healed": 1},
            types.SimpleNamespace(as_dict=lambda: {}),
            [],
            [],
        ),
    )

    settings = _settings(repo, data_freshness_autoheal_circuit_breaker_nights=3)
    summary = data_freshness_monitor(repo=repo, settings=settings, today=today)

    assert summary["autoheal"]["circuit_broken"] == []
    assert summary["autoheal"]["healed"] == ["daily_ohlc"]


def test_autoheal_yields_to_a_concurrent_gap_healer_holding_the_lock(
    seeded_db_empty_cards,
):
    """_another_run_active() alone is check-then-act -- it can't see a
    nightly gap-healer run that acquires the advisory lock a moment later.
    Autoheal must take the SAME lock key so the two are truly mutually
    exclusive, not just usually non-overlapping."""
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    settings = _settings(repo)

    def fail_if_called(*_a, **_k):
        raise AssertionError("heal must not run while the gap-healer lock is held")

    specs = {
        "daily_ohlc": HealSpec(
            "daily_ohlc", "massive", "per_ticker_range", fail_if_called
        )
    }

    with psycopg.connect(_peer_dsn(repo.conn)) as holder:
        with holder.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_GAP_HEALER_LOCK_KEY,))
            assert cur.fetchone()[0] is True

        result = _autoheal_frozen_tables(
            repo, settings, today, [_frozen_row("daily_ohlc")], specs=specs
        )
        assert result["healed"] == []
        assert result["skipped_no_adapter"] == ["daily_ohlc"]

        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_GAP_HEALER_LOCK_KEY,))
        holder.commit()

    # Once the peer releases the lock, autoheal must be able to acquire and
    # release it cleanly on the next call (no leaked lock from this test).
    with repo.conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_GAP_HEALER_LOCK_KEY,))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT pg_advisory_unlock(%s)", (_GAP_HEALER_LOCK_KEY,))
