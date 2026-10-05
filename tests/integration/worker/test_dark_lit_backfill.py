"""dark_lit_backfill against a real migrated DB: oldest-first progress, the
quota stop, resume from the progress table, the out-of-window skip, and the
governor stop. UW is a stub serving one short page per ticker-day (labelled
synthetic prints, no market values)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx

from uw_scan.api.client import UwHTTPError
from uw_scan.worker.jobs.dark_lit_backfill import (
    JOB_NAME,
    dark_lit_backfill,
    spent_today,
)

D0, D1, D2, D3 = (
    date(2023, 10, 31),
    date(2023, 11, 2),
    date(2023, 11, 3),
    date(2023, 11, 6),
)
_OUT_OF_WINDOW = (
    '{"code":"historic_data_access_missing","message":"The earliest date currently '
    'available to this token is 2023-11-02 (730 trading days)."}'
)


class _Uw:
    def __init__(self):
        self.rate_limit = SimpleNamespace(
            daily_count=0, minute_remaining=110, minute_reset=None
        )
        self.dates: list[str] = []

    def get(self, slug, ticker=None, params=None, run_id=None, *, option_symbol=None):
        d = params["date"]
        self.dates.append(d)
        if d == D0.isoformat():
            raise UwHTTPError(403, str(slug), _OUT_OF_WINDOW)
        rows = [
            {
                "tracking_id": f"syn-{ticker}-{d}-{k}",
                "ticker": ticker,
                "executed_at": f"{d}T15:00:0{k}Z",
                "volume": k,
                # placeholders, not market data: the PK needs price and size
                "price": "0",
                "size": 1,
            }
            for k in range(3)
        ]
        resp = httpx.Response(
            200, json={"data": rows}, request=httpx.Request("GET", "https://x/y")
        )
        return resp, {}


def _setup(repo, settings, quota: int):
    keep = sorted(c.ticker for c in repo.list_active_watchlist())[:2]
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.watchlist SET removed_at = now() "
            "WHERE removed_at IS NULL AND ticker <> ALL(%s)",
            (keep,),
        )
        # (keep[0], D1) is already complete: under a page in both sources.
        cur.execute(
            "INSERT INTO uw_scan.uw_dark_lit_flow_prints "
            "(source, tracking_id, ticker, executed_at, market_date, price, size,"
            " volume, raw_jsonb) VALUES ('darkpool', 'pre', %s,"
            " '2023-11-02T15:00:00Z', %s, 0, 1, 0, '{}')",
            (keep[0], D1),
        )
    repo.conn.commit()
    caps = {
        "dark_lit_backfill_weekday_max_calls": quota,
        "dark_lit_backfill_saturday_max_calls": quota,
        "dark_lit_backfill_sunday_max_calls": quota,
    }
    return keep, settings.model_copy(update=caps)


def _run(repo, settings, uw, budget_ok=lambda: True):
    return dark_lit_backfill(
        repo=repo,
        client=uw,
        settings=settings,
        sessions_fn=lambda start, end: [D0, D1, D2, D3],
        budget_ok=budget_ok,
    )


def test_quota_stop_then_resume(seeded_db_empty_cards, _migrated_settings):
    repo = seeded_db_empty_cards
    (a, b), settings = _setup(repo, _migrated_settings, quota=125)

    # Worst case per ticker-day is 120 calls; each stub day costs 2 (+1 for the
    # 403). 125 admits three ticker-days after the out-of-window probe.
    first = _run(repo, settings, uw := _Uw())
    assert first["stop_reason"] == "quota"
    assert (first["done"], first["unavailable"], first["remaining"]) == (3, 1, 2)
    # D0 was probed once and then skipped for the second ticker too.
    assert uw.dates.count(D0.isoformat()) == 1

    second = _run(repo, settings, uw2 := _Uw())
    assert second["stop_reason"] == "exhausted"
    assert (second["done"], second["remaining"]) == (2, 0)
    assert set(uw2.dates) == {D3.isoformat()}  # resumed; nothing re-fetched

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, market_date, status FROM uw_scan.dark_lit_backfill_progress"
        )
        progress = set(cur.fetchall())
        cur.execute(
            "SELECT stop_reason FROM uw_scan.dark_lit_backfill_runs ORDER BY id"
        )
        runs = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT count(*) FROM uw_scan.uw_dark_lit_flow_prints "
            "WHERE tracking_id LIKE 'syn-%%'"
        )
        prints = cur.fetchone()[0]
    assert progress == {
        (a, D0, "unavailable"),
        (b, D1, "done"),
        (a, D2, "done"),
        (b, D2, "done"),
        (a, D3, "done"),
        (b, D3, "done"),
    }
    assert runs == ["quota", "exhausted"]
    assert prints == 5 * 2 * 3  # 5 days x 2 sources x 3 prints


def test_governor_no_stops_before_any_call(seeded_db_empty_cards, _migrated_settings):
    repo = seeded_db_empty_cards
    _, settings = _setup(repo, _migrated_settings, quota=15000)
    out = _run(repo, settings, uw := _Uw(), budget_ok=lambda: False)
    assert out["stop_reason"] == "research_budget"
    assert out["done"] == 0 and uw.dates == []


def _telemetry(cur, provider: str, job: str, at: datetime) -> None:
    cur.execute(
        "INSERT INTO uw_scan.external_api_requests "
        "(provider, endpoint_key, method, path, status_code, status_family, "
        " request_started_at, request_finished_at, latency_ms, job_name) "
        "VALUES (%s, 'ep', 'GET', '/p', 200, '2xx', %s, %s, 1, %s)",
        (provider, at, at + timedelta(milliseconds=1), job),
    )


def test_spent_today_counts_this_jobs_uw_rows_in_the_budget_day(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    now = datetime(2026, 10, 10, 2, 30, tzinfo=UTC)  # Fri 22:30 EDT = UTC Sat
    with repo.conn.cursor() as cur:
        _telemetry(cur, "uw", JOB_NAME, datetime(2026, 10, 10, 0, 30, tzinfo=UTC))
        _telemetry(cur, "uw", JOB_NAME, datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
        _telemetry(cur, "uw", JOB_NAME, datetime(2026, 10, 9, 23, 59, tzinfo=UTC))
        _telemetry(cur, "uw", "full_scan", datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
        _telemetry(cur, "massive", JOB_NAME, datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
    repo.conn.commit()
    assert spent_today(repo.conn, "uw_scan", now) == 2


def test_recorded_spend_stops_the_run_on_quota(
    seeded_db_empty_cards, _migrated_settings
):
    repo = seeded_db_empty_cards
    _, settings = _setup(repo, _migrated_settings, quota=125)
    with repo.conn.cursor() as cur:
        for _ in range(6):  # 6 + a worst-case 120 > 125
            _telemetry(cur, "uw", JOB_NAME, datetime.now(UTC))
    repo.conn.commit()
    out = _run(repo, settings, uw := _Uw())
    assert out["stop_reason"] == "quota"
    assert out["done"] == 0 and uw.dates == []
