"""Integration tests for GET /api/stock/{ticker}/volatility/series."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import RealizedVolRow
from uw_scan.sources.ohlc import OhlcBar


def _seed_history(repo, ticker: str, n: int = 100) -> None:
    today = date.today()
    base = today - timedelta(days=n)
    rv_rows = [
        RealizedVolRow(
            date=base + timedelta(days=i),
            price=Decimal(str(100 + i * 0.1)),
            implied_volatility=Decimal("0.50"),
            realized_volatility=Decimal("0.40"),
        )
        for i in range(n)
    ]
    repo.upsert_realized_vol_rows(ticker, rv_rows)
    spy_bars = [
        OhlcBar(
            ticker="SPY",
            date=base + timedelta(days=i),
            open=None,
            high=None,
            low=None,
            close=Decimal(str(500 + i * 0.5)),
            volume=None,
        )
        for i in range(n)
    ]
    repo.upsert_index_ohlc_rows(spy_bars)
    repo.conn.commit()


def test_volatility_series_endpoint_ready_when_fresh_history_present(
    client, seeded_db_empty_cards
):
    _seed_history(seeded_db_empty_cards, "TSLA", n=100)

    r = client.get("/api/stock/TSLA/volatility/series")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "TSLA"
    assert body["backfill_status"] == "ready"
    assert "header" in body
    assert "hv_iv_history" in body
    # Should have a non-trivial number of bars.
    assert len(body["hv_iv_history"]) >= 90


def _backfill_rows(repo, ticker: str) -> list[tuple]:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT status, started_at FROM uw_scan.volatility_backfill_status "
            "WHERE ticker = %s",
            (ticker,),
        )
        rows = cur.fetchall()
    repo.conn.commit()
    return rows


def test_volatility_series_endpoint_enqueues_backfill_when_history_thin(
    client, seeded_db_empty_cards
):
    """No history → a durable 'queued' row; the response says "running"."""
    r = client.get("/api/stock/UNSEEDED/volatility/series")
    assert r.status_code == 200
    assert r.json()["backfill_status"] == "running"
    assert _backfill_rows(seeded_db_empty_cards, "UNSEEDED") == [("queued", None)]


def test_two_gets_create_one_queued_backfill(client, seeded_db_empty_cards):
    """The ticker PK dedups: a second GET while queued adds nothing."""
    for _ in range(2):
        r = client.get("/api/stock/DUPTKR/volatility/series")
        assert r.json()["backfill_status"] == "running"
    assert _backfill_rows(seeded_db_empty_cards, "DUPTKR") == [("queued", None)]


def test_get_never_requeues_a_running_or_failed_backfill(client, seeded_db_empty_cards):
    """A running row keeps its started_at (the worker owns stale requeue); a
    failed row reports "failed" and stays failed."""
    from datetime import datetime, timezone

    repo = seeded_db_empty_cards
    started = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    repo.upsert_volatility_backfill_status(
        ticker="RUNTKR", status="running", started_at=started
    )
    repo.upsert_volatility_backfill_status(ticker="BADTKR", status="failed")
    repo.conn.commit()

    assert (
        client.get("/api/stock/RUNTKR/volatility/series").json()["backfill_status"]
        == "running"
    )
    assert (
        client.get("/api/stock/BADTKR/volatility/series").json()["backfill_status"]
        == "failed"
    )
    assert _backfill_rows(repo, "RUNTKR") == [("running", started)]
    assert _backfill_rows(repo, "BADTKR")[0][0] == "failed"


def test_enqueued_backfill_survives_api_restart_and_worker_runs_it(
    client, seeded_db_empty_cards, _migrated_settings, monkeypatch
):
    """The queue lives in Postgres, not the API process: after the GET the API
    can go away, and a worker on a fresh connection still claims and runs it."""
    import psycopg

    import uw_scan.worker.jobs.volatility_backfill as job_mod
    from uw_scan.storage.repository import Repository

    client.get("/api/stock/RESTART/volatility/series")
    client.app.dependency_overrides.clear()  # the API is gone; only the row is left

    class _NoUw:
        def __init__(self, *_a, **_k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    calls: list[str] = []

    def fake_backfill(*, client, repo, run_id, ticker, nearest_expiries):
        calls.append(ticker)
        return "ready"

    monkeypatch.setattr(job_mod, "UwClient", _NoUw)
    monkeypatch.setattr(job_mod, "run_volatility_backfill", fake_backfill)

    with psycopg.connect(_migrated_settings.db_dsn()) as conn:
        worker_repo = Repository(conn, schema=_migrated_settings.db_schema)
        ran = job_mod.volatility_backfill_tick(
            repo=worker_repo, settings=_migrated_settings, budget_ok=lambda: True
        )

    assert ran == "RESTART" and calls == ["RESTART"]
    assert _backfill_rows(seeded_db_empty_cards, "RESTART")[0][0] == "ready"


def test_volatility_series_empty_response_shape_is_safe(client, seeded_db_empty_cards):
    """Even with zero history, response defaults are non-None blocks
    (frontend dereferences .points / .bins directly — review I5)."""
    r = client.get("/api/stock/NEWTKR/volatility/series")
    body = r.json()
    # Empty defaults present, not None.
    assert body["regime_quadrant"] == {
        "points": [],
        "latest": None,
        "cutoff_corr": None,
    }
    assert body["iv_percentile_distribution"]["bins"] == []
    assert body["term_structure"] == []
    assert body["smile"] == []
    assert body["hv_iv_history"] == []
