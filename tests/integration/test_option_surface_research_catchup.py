"""Catch-up job that fills a research cohort's option-surface history.

The behaviours worth pinning are the ones that decide whether this job is safe to
leave enabled forever: it must spend nothing when there is nothing to do (empty
cohort, or history already complete), and it must respect its per-night call
budget rather than draining the research pool in one go.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs import option_surface_research_catchup as mod
from uw_scan.worker.jobs.option_surface_research_catchup import (
    CALLS_PER_TICKER_SESSION,
    missing_pairs,
    option_surface_research_catchup,
    weekly_sessions,
)

COHORT = "catchup_cohort_v1"
TODAY = date(2026, 7, 29)  # a Wednesday


class _ExplodingClient:
    """Fails the test if the job touches UW at all.

    Asserting "filled 0 pairs" alone would still pass if the job had already
    burned calls before discovering it had nothing to do.
    """

    def __getattr__(self, name: str):  # pragma: no cover - must never run
        raise AssertionError(f"UW client used when there was nothing to do: .{name}")


def _seed(repo: Repository, tickers: list[str]) -> None:
    sql = f"""
        INSERT INTO {repo._schema}.research_universe
               (cohort, ticker, sector, marketcap, option_oi, source, selected_on)
        VALUES (%s, %s, 'Technology', 1000000000, 250000, 'test', %s)
        ON CONFLICT (cohort, ticker) DO NOTHING
    """
    with repo.conn.cursor() as cur:
        for t in tickers:
            cur.execute(sql, (COHORT, t, TODAY))
    repo.conn.commit()


def _grid_row() -> dict:
    # Real CSCO strike/expiry shape; values are structural, the test asserts on
    # presence rather than on any price.
    return {
        "expiry": date(2026, 8, 21),
        "strike": Decimal("70"),
        "call_iv": Decimal("0.25"),
        "call_delta": Decimal("0.5"),
    }


def _capture(repo: Repository, ticker: str, market_date: date) -> None:
    repo.upsert_option_surface_grid(ticker, market_date, None, [_grid_row()])
    repo.conn.commit()


def test_weekly_sessions_are_wednesdays_oldest_first():
    out = weekly_sessions(today=TODAY, history_days=30)
    assert out == sorted(out), "must be oldest-first so the expiring end goes first"
    assert all(d.weekday() == 2 for d in out)
    assert all(d < TODAY for d in out)
    # 30-day window, one per week.
    assert len(out) == 4


def test_missing_pairs_excludes_what_is_already_captured(
    seeded_db_empty_cards: Repository,
):
    repo = seeded_db_empty_cards
    sessions = [TODAY - timedelta(days=7), TODAY - timedelta(days=14)]
    _capture(repo, "CSCO", sessions[0])

    pending = missing_pairs(repo=repo, sessions=sessions, tickers=["CSCO", "MRK"])

    assert (sessions[0], "CSCO") not in pending
    assert (sessions[0], "MRK") in pending
    assert (sessions[1], "CSCO") in pending
    assert len(pending) == 3


def test_empty_cohort_spends_nothing(seeded_db_empty_cards: Repository):
    out = option_surface_research_catchup(
        repo=seeded_db_empty_cards,
        client=_ExplodingClient(),
        cohort="never_seeded",
        today=TODAY,
    )
    assert out == {"pairs_filled": 0, "pairs_remaining": 0, "rows": 0}


def test_complete_history_spends_nothing(seeded_db_empty_cards: Repository):
    """The self-terminating property: once filled, it never spends again."""
    repo = seeded_db_empty_cards
    _seed(repo, ["CSCO"])
    for session in weekly_sessions(today=TODAY):
        _capture(repo, "CSCO", session)

    out = option_surface_research_catchup(
        repo=repo, client=_ExplodingClient(), cohort=COHORT, today=TODAY
    )
    assert out == {"pairs_filled": 0, "pairs_remaining": 0, "rows": 0}


def test_budget_bounds_the_night_and_reports_the_remainder(
    seeded_db_empty_cards: Repository, monkeypatch: pytest.MonkeyPatch
):
    repo = seeded_db_empty_cards
    _seed(repo, ["CSCO", "MRK"])
    calls: list[tuple[str, date]] = []

    def _fake_build(*, client, repo, run_id, ticker, market_date, date_iso, max_dte):
        calls.append((ticker, market_date))
        return [_grid_row()]

    monkeypatch.setattr(mod, "_build_ticker_rows", _fake_build)

    # Budget for exactly two pairs.
    out = option_surface_research_catchup(
        repo=repo,
        client=object(),
        cohort=COHORT,
        today=TODAY,
        max_calls=CALLS_PER_TICKER_SESSION * 2,
    )

    # The budget is a bound, not a meter — it must never overshoot.
    assert out["pairs_filled"] == 2
    assert len(calls) == 2
    # `pairs_remaining` is what the log promises is still to come, so it has to
    # match what is genuinely still missing — otherwise the "N nights to go"
    # estimate drifts and nobody notices the job stalled.
    still_missing = missing_pairs(
        repo=repo, sessions=weekly_sessions(today=TODAY), tickers=["CSCO", "MRK"]
    )
    assert out["pairs_remaining"] == len(still_missing) > 0


def test_resumes_where_it_stopped(
    seeded_db_empty_cards: Repository, monkeypatch: pytest.MonkeyPatch
):
    """Two bounded runs must not refetch the first run's pairs."""
    repo = seeded_db_empty_cards
    _seed(repo, ["CSCO"])
    seen: list[tuple[str, date]] = []

    def _fake_build(*, client, repo, run_id, ticker, market_date, date_iso, max_dte):
        seen.append((ticker, market_date))
        return [_grid_row()]

    monkeypatch.setattr(mod, "_build_ticker_rows", _fake_build)

    kwargs = dict(
        repo=repo,
        client=object(),
        cohort=COHORT,
        today=TODAY,
        max_calls=CALLS_PER_TICKER_SESSION * 2,
    )
    first = option_surface_research_catchup(**kwargs)
    second = option_surface_research_catchup(**kwargs)

    assert first["pairs_filled"] == 2
    assert second["pairs_filled"] == 2
    assert len(seen) == len(set(seen)), "a pair was fetched twice across runs"
    assert second["pairs_remaining"] == first["pairs_remaining"] - 2
