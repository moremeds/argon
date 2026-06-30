"""CLI orchestration tests: audit_into_run -> finalize, execute_into_run wiring
(with injected fake specs, no live providers), and verify_run before/after."""

from __future__ import annotations

import importlib.util
import types
from datetime import date, timedelta

from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_adapters import HealSpec


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "data_gap_healer_cli", "scripts/backfill/data_gap_healer.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _settings(repo):
    return types.SimpleNamespace(
        db_schema=repo._schema, db_host="127.0.0.1", db_name="option_wizard_test"
    )


def _ohlc(repo, ticker, d):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ticker, d, 1.0, "test"),
        )
    repo.conn.commit()


def _calendar(repo, *dates):
    """Seed the trading-day reference (market_tide_sentiment_daily) — the sole
    calendar source after the self-union was dropped."""
    with repo.conn.cursor() as cur:
        for d in dates:
            cur.execute(
                f"INSERT INTO {repo._schema}.market_tide_sentiment_daily "
                "(data_date, state, magnitude, driver, momentum, bars) "
                "VALUES (%s, 'BALANCED', 'FLAT', 'x', 'x', 1) ON CONFLICT DO NOTHING",
                (d,),
            )
    repo.conn.commit()


def test_audit_into_run_persists_run_and_items(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    _calendar(repo, d1, d2)
    _ohlc(repo, "AAPL", d1)
    _ohlc(repo, "AAPL", d2)
    _ohlc(repo, "NVDA", d1)  # NVDA missing d2

    run_id, summaries, items = cli.audit_into_run(
        repo,
        gap,
        repo._schema,
        start=d1,
        end=d2,
        datasets=["daily_ohlc"],
        active=["AAPL", "NVDA"],
    )
    cli.finalize_run(gap, run_id, summaries, items)

    assert len(items) == 1 and items[0].ticker == "NVDA"
    run = gap.get_run(run_id)
    assert run["status"] == "complete"
    assert run["summary_jsonb"]["total_gaps"] == 1


def test_execute_into_run_heals_with_injected_specs(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    _calendar(repo, d1, d2)
    _ohlc(repo, "AAPL", d1)  # AAPL has d1; missing d2. NVDA missing both.

    def fake_range(ctx, ticker, lo, hi):
        d = lo
        while d <= hi:
            _ohlc(ctx.repo, ticker, d)
            d += timedelta(days=1)
        return 1

    specs = {
        "daily_ohlc": HealSpec("daily_ohlc", "massive", "per_ticker_range", fake_range)
    }
    run_id, outcome, budget, summaries, items = cli.execute_into_run(
        repo,
        gap,
        _settings(repo),
        start=d1,
        end=d2,
        datasets=["daily_ohlc"],
        max_uw_calls=20000,
        today=date(2026, 6, 30),
        specs=specs,
        active=["AAPL", "NVDA"],
    )
    assert outcome.get("healed") == len(items)
    run = gap.get_run(run_id)
    assert run["summary_jsonb"]["outcome"]["healed"] == len(items)


def test_verify_run_shows_before_after(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    # calendar established as {d1, d2} via the reference; only NVDA@d2 is a hole
    _calendar(repo, d1, d2)
    _ohlc(repo, "AAPL", d1)
    _ohlc(repo, "AAPL", d2)
    _ohlc(repo, "NVDA", d1)

    run_id, summaries, items = cli.audit_into_run(
        repo,
        gap,
        repo._schema,
        start=d1,
        end=d2,
        datasets=["daily_ohlc"],
        active=["AAPL", "NVDA"],
    )
    cli.finalize_run(gap, run_id, summaries, items)
    before = len(items)
    assert before == 1  # NVDA@d2

    # fill the in-calendar hole, then verify shows it healed
    _ohlc(repo, "NVDA", d2)
    result = cli.verify_run(repo, gap, repo._schema, run_id, active=["AAPL", "NVDA"])
    assert result["before_gaps"] == before
    assert result["after_gaps"] == 0


def test_resume_requeues_orphaned_running_items(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    _calendar(repo, d1, d2)
    _ohlc(repo, "AAPL", d1)  # AAPL@d2, NVDA@d1, NVDA@d2 are gaps

    run_id, _summaries, items = cli.audit_into_run(
        repo,
        gap,
        repo._schema,
        start=d1,
        end=d2,
        datasets=["daily_ohlc"],
        mode="execute",
        active=["AAPL", "NVDA"],
    )
    # simulate a killed run: every item stuck 'running' (claim_next_items skips it)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.data_gap_items SET status='running' WHERE run_id=%s",
            (run_id,),
        )
    repo.conn.commit()

    def fake_range(ctx, ticker, lo, hi):
        d = lo
        while d <= hi:
            _ohlc(ctx.repo, ticker, d)
            d += timedelta(days=1)
        return 1

    specs = {
        "daily_ohlc": HealSpec("daily_ohlc", "massive", "per_ticker_range", fake_range)
    }
    outcome, _budget = cli.resume_run(
        repo,
        gap,
        _settings(repo),
        run_id,
        today=date(2026, 6, 30),
        max_uw_calls=20000,
        specs=specs,
    )
    # the orphaned 'running' items were requeued and then healed
    assert outcome.get("healed") == len(items)
