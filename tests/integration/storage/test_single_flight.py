"""single_flight and every lock site that moved onto it (I-53/I-54).

Each site must skip exactly as before when ANOTHER session holds its key -- same
key, same early return -- and must leave that session's lock alone. The keys
themselves are frozen in tests/unit/storage/test_advisory_lock_keys.py.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.storage.advisory_locks import (
    fixed_key,
    hashed_key,
    single_flight,
    ticker_key,
    worker_key,
)

pytestmark = pytest.mark.integration


def _held_here(conn: psycopg.Connection, key: int) -> bool:
    """Does THIS backend hold the session lock? (Re-acquiring on the same
    connection always succeeds -- session locks are re-entrant -- so that is
    no proof of release.)"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND pid = pg_backend_pid() AND objsubid = 1 "
            "AND ((classid::bigint << 32) | objid::bigint) = (%s::bigint & x'ffffffffffffffff'::bigint)",
            (key,),
        )
        return cur.fetchone()[0] > 0


@pytest.fixture
def holder(_migrated_settings):
    with psycopg.connect(_migrated_settings.db_dsn(), autocommit=True) as conn:
        yield conn


def _hold(conn: psycopg.Connection, key: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
        assert cur.fetchone()[0]


# ---------------------------------------------------------------- the primitive


def test_acquires_and_releases(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    key = fixed_key("cockpit_snapshot")
    with single_flight(conn, key) as acquired:
        assert acquired
        assert _held_here(conn, key)
    assert not _held_here(conn, key)


def test_skips_when_another_session_holds_it(seeded_db_empty_cards, holder):
    conn = seeded_db_empty_cards.conn
    key = fixed_key("cockpit_snapshot")
    _hold(holder, key)
    with single_flight(conn, key) as acquired:
        assert not acquired
    assert _held_here(holder, key)  # never released someone else's lock


def test_releases_after_an_aborted_transaction(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    key = fixed_key("cockpit_snapshot")
    with pytest.raises(psycopg.errors.DivisionByZero):
        with single_flight(conn, key):
            conn.execute("SELECT 1/0")
    assert not _held_here(conn, key)


def test_a_failed_release_never_masks_the_body_error(
    seeded_db_empty_cards, monkeypatch
):
    import uw_scan.storage.advisory_locks as locks

    def _broken_release(_conn, _key):
        raise RuntimeError("unlock failed")

    conn = seeded_db_empty_cards.conn
    key = fixed_key("cockpit_snapshot")
    monkeypatch.setattr(locks, "_release", _broken_release)
    with pytest.raises(ValueError, match="body"):
        with single_flight(conn, key):
            raise ValueError("body")
    monkeypatch.undo()
    locks._release(conn, key)


def test_reentrant_on_one_connection(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    key = fixed_key("data_gap_healer")
    with single_flight(conn, key) as outer:
        with single_flight(conn, key) as inner:
            assert outer and inner
        assert _held_here(conn, key)  # the inner release only decremented
    assert not _held_here(conn, key)


@pytest.mark.parametrize(
    "text",
    [
        "theta_harvester_scan",
        "theta_harvester_quote",
        "vol_backfill:AAPL",
        "technicals_refresh:NVDA",
    ],
)
def test_python_hash_equals_the_sql_expression_it_replaced(seeded_db_empty_cards, text):
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute("SELECT ('x' || substr(md5(%s), 1, 16))::bit(64)::bigint", (text,))
        assert cur.fetchone()[0] == hashed_key(text)


# ---------------------------------------------------------------- every job site


def _job_cases():
    from uw_scan.worker.jobs import (
        cockpit_daily_snapshot,
        discovery_scan,
        flow_data_refresh,
        greek_exposure_daily_refresh,
        option_intraday_jobs,
        uw_alpha_capture,
        volatility_backfill,
    )

    zero3 = {"tickers": 0, "contracts": 0, "buckets": 0}
    return [
        (
            "cockpit_daily_snapshot",
            fixed_key("cockpit_snapshot"),
            lambda r, s: cockpit_daily_snapshot.cockpit_daily_snapshot(
                repo=r, client=None, settings=s
            ),
            None,
        ),
        (
            "discovery_scan",
            fixed_key("discovery_scan"),
            lambda r, s: discovery_scan.discovery_scan_once(
                repo=r, client=None, settings=s
            ),
            {"status": "skipped_locked"},
        ),
        (
            "flow_data_refresh[uw-1]",
            worker_key("flow_data_refresh", 1),
            lambda r, s: flow_data_refresh.flow_data_refresh(
                repo=r,
                client=None,
                settings=s,
                lock_key=worker_key("flow_data_refresh", 1),
            ),
            None,
        ),
        (
            "greek_daily_refresh",
            fixed_key("greek_daily_refresh"),
            lambda r, s: greek_exposure_daily_refresh.greek_exposure_daily_refresh(
                repo=r, client=None, settings=s
            ),
            {"tickers": 0, "rows": 0, "skipped_index": 0, "errors": 0},
        ),
        (
            "intraday_refresh",
            fixed_key("intraday_refresh"),
            lambda r, s: option_intraday_jobs.refresh_intraday_for_top_oi_movers(
                repo=r, client=None, settings=s
            ),
            zero3,
        ),
        (
            "intraday_backfill",
            fixed_key("intraday_backfill"),
            lambda r, s: option_intraday_jobs.backfill_intraday_history(
                repo=r,
                client=None,
                settings=s,
                tickers=["AAPL"],
                since=date(2026, 9, 1),
                until=date(2026, 9, 2),
            ),
            {"tickers": 0, "sessions": 0, "contracts": 0, "buckets": 0, "errors": 0},
        ),
        (
            "uw_alpha_gex_levels",
            fixed_key("uw_alpha_gex_levels"),
            lambda r, s: uw_alpha_capture.gex_levels_capture(
                repo=r, client=None, settings=s
            ),
            {"tickers": 0, "rows": 0, "errors": 0},
        ),
        (
            "vol_backfill:AAPL",
            ticker_key("vol_backfill:", "AAPL"),
            lambda r, s: volatility_backfill.run_claimed_backfill(
                "AAPL", repo=r, settings=s
            ),
            "running",
        ),
    ]


@pytest.mark.parametrize("case", _job_cases(), ids=lambda c: c[0])
def test_job_skips_while_another_session_holds_its_key(
    seeded_db_empty_cards, _migrated_settings, holder, case
):
    _name, key, run, skipped = case
    repo = seeded_db_empty_cards
    _hold(holder, key)

    assert run(repo, _migrated_settings) == skipped
    assert _held_here(holder, key)
    assert not _held_here(repo.conn, key)


def test_gap_healer_job_and_autoheal_and_manual_heal_share_one_key(
    seeded_db_empty_cards, _migrated_settings, holder
):
    from uw_scan.worker.jobs import data_freshness_monitor, data_gap_healer

    repo = seeded_db_empty_cards
    key = fixed_key("data_gap_healer")
    _hold(holder, key)

    settings = _migrated_settings.model_copy(update={"data_gap_healer_enabled": True})
    assert data_gap_healer.data_gap_healer_job(settings=settings) == {
        "skipped": "locked"
    }
    assert data_freshness_monitor._autoheal_frozen_tables(
        repo, settings, date(2026, 9, 1), []
    ) == {"healed": [], "circuit_broken": [], "skipped_no_adapter": []}
    gap = data_gap_healer.DataGapHealerRepository(repo.conn, schema=settings.db_schema)
    with pytest.raises(data_gap_healer.HealerBusy):
        with data_gap_healer._single_flight(gap):
            pass
    assert _held_here(holder, key)
    assert not _held_here(repo.conn, key)
