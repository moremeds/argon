"""latest_run_id selects the most recent run that actually persisted its
aggregates — regardless of the scan_runs.notes label.

This is the property-based guard that replaces the per-note denylist. Any run
that did not write the per-ticker detail payload (``aggregates``) must never
shadow a real full_scan run — *including* a brand-new side-channel job that
nobody has taught the selector about yet. The denylist re-broke this three
times (PRs #106, #129, and the skew engine); keying on data presence instead
of a hand-maintained list of notes closes the class of bug.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.models import MarketAggregates


def _full_scan(db, ticker: str) -> int:
    """A completed full_scan run that persisted its aggregates (the canonical run)."""
    run_id = db.insert_scan_run(ticker, notes="")
    db.set_aggregates(
        run_id, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
    db.finish_scan_run(run_id, status="ok")
    return run_id


def _side_channel(db, ticker: str, notes: str) -> int:
    """A completed side-channel run that wrote NO aggregates."""
    run_id = db.insert_scan_run(ticker, notes=notes)
    db.finish_scan_run(run_id, status="ok")
    return run_id


def test_skew_swing_greeks_run_does_not_shadow_full_scan(seeded_db_empty_cards):
    """The exact regression: a later skew_swing_greeks run must not win."""
    db = seeded_db_empty_cards
    full = _full_scan(db, "QQQ")
    _side_channel(db, "QQQ", notes="skew_swing_greeks")  # higher run_id, no aggregates
    assert db.latest_run_id("QQQ") == full


def test_unknown_future_side_channel_note_is_ignored(seeded_db_empty_cards):
    """The property generalises: a note the selector was never taught about
    is still ignored because it carries no aggregates."""
    db = seeded_db_empty_cards
    full = _full_scan(db, "AVGO")
    _side_channel(db, "AVGO", notes="some_future_job_2027")
    assert db.latest_run_id("AVGO") == full


def test_ticker_with_only_empty_aggregate_runs_resolves_to_zero(seeded_db_empty_cards):
    """A ticker whose only runs wrote no aggregates is not renderable -> 0 (404)."""
    db = seeded_db_empty_cards
    _side_channel(db, "NVDA", notes="skew_swing_greeks")
    assert db.latest_run_id("NVDA") == 0


def _scan_with_duration(db, ticker, notes, seconds, *, aggregates):
    """Insert a completed run with an explicit duration; optionally persist aggregates."""
    finished = datetime.now(timezone.utc)
    started = finished - timedelta(seconds=seconds)
    with db.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {db._schema}.scan_runs "
            "(ticker, started_at, finished_at, status, notes) "
            "VALUES (%s, %s, %s, 'ok', %s) RETURNING run_id",
            (ticker, started, finished, notes),
        )
        run_id = int(cur.fetchone()[0])
    if aggregates:
        db.set_aggregates(run_id, MarketAggregates(call_oi_total=1000))
    db.conn.commit()
    return run_id


def test_scan_duration_summary_excludes_runs_without_aggregates(seeded_db_empty_cards):
    """The duration health metric counts only canonical full scans (those that
    wrote aggregates) — a fast skew_swing_greeks run must not drag the average
    down. Same property guard as latest_run_id, applied to the twin selector."""
    db = seeded_db_empty_cards
    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    window_end = datetime.now(timezone.utc) + timedelta(minutes=1)
    _scan_with_duration(db, "QQQ", "", 60, aggregates=True)  # real full_scan
    _scan_with_duration(
        db, "QQQ", "skew_swing_greeks", 1, aggregates=False
    )  # side-channel
    summary = db.get_scan_duration_summary(window_start, window_end)
    assert summary.avg_seconds == 60.0
