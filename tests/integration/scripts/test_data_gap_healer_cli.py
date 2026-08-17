"""CLI orchestration tests: audit_into_run -> finalize, execute_into_run wiring
(with injected fake specs, no live providers), and verify_run before/after."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import date, timedelta

import psycopg
import pytest

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
        # audit_into_run does not write the rollup -- its caller finalizes. Seed
        # it as a completed-then-re-resumed run would carry, so the assertion
        # below proves resume MERGES into the summary instead of replacing it.
        cur.execute(
            f"UPDATE {repo._schema}.data_gap_runs "
            'SET summary_jsonb = \'{"datasets": {"daily_ohlc": {}}}\'::jsonb '
            "WHERE id=%s",
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
    # and the run is CLOSED. A resume that succeeded used to leave status
    # 'running' forever, which wedges the nightly job's active-run guard just as
    # a killed process does -- via the ordinary operator path, not a crash.
    run = gap.get_run(run_id)
    assert run["status"] == "complete"
    assert run["finished_at"] is not None
    # the audit's per-dataset rollup survives the merge
    assert "datasets" in run["summary_jsonb"]
    assert run["summary_jsonb"]["resumes"][-1]["outcome"] == outcome

    # staged resumes APPEND. An operator draining a run dataset-by-dataset would
    # otherwise lose every earlier stage's outcome and budget from the audit trail.
    cli.resume_run(
        repo,
        gap,
        _settings(repo),
        run_id,
        today=date(2026, 6, 30),
        max_uw_calls=20000,
        specs=specs,
    )
    assert len(gap.get_run(run_id)["summary_jsonb"]["resumes"]) == 2


def test_cli_refuses_to_race_another_heal(seeded_db_empty_cards, _migrated_settings):
    """`execute` and `resume` now take the healer's single-flight advisory lock.
    Racing another heal would re-audit the same still-missing gaps and heal them
    twice, double-charging the provider budget -- the hazard data_freshness_monitor
    already documents at this same lock key. The CLI re-exports HealerBusy so
    main() can map it to exit code 2 ("busy", not "broken")."""
    cli = _load_cli()
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)

    # A second connection stands in for the nightly job / another operator. Take
    # the DSN from the fixture's own Settings -- conn.info deliberately withholds
    # the password, so a hand-built DSN passes on a trust-auth dev box and fails
    # against CI's password-authenticated Postgres service.
    with psycopg.connect(_migrated_settings.db_dsn()) as holder, holder.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(92010)")
        assert cur.fetchone()[0] is True

        with pytest.raises(cli.HealerBusy):
            cli.execute_into_run(
                repo,
                gap,
                _settings(repo),
                start=date(2026, 6, 10),
                end=date(2026, 6, 11),
                datasets=["daily_ohlc"],
                max_uw_calls=0,
                today=date(2026, 6, 30),
            )
        with pytest.raises(cli.HealerBusy):
            cli.resume_run(
                repo,
                gap,
                _settings(repo),
                1,
                today=date(2026, 6, 30),
                max_uw_calls=0,
            )


def test_main_maps_healer_busy_to_exit_code_2(monkeypatch):
    """`2` is an operator contract, not an implementation detail: a wrapper needs
    to tell "another heal holds the lock, try later" apart from "this run broke".
    build_parser() resolves cmd_execute from module globals when main() calls it,
    so patching the command is enough to drive the handler."""
    cli = _load_cli()

    def _busy(_args, _settings):
        raise cli.HealerBusy("another gap-heal holds the single-flight lock")

    monkeypatch.setattr(cli, "cmd_execute", _busy)
    monkeypatch.setattr(
        sys, "argv", ["data_gap_healer.py", "execute", "--start", "2026-01-01"]
    )
    assert cli.main() == 2
