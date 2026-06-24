from __future__ import annotations

import zlib
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.models import MarketAggregates
from uw_scan.worker.jobs.option_intraday_jobs import refresh_intraday_for_top_oi_movers


def _shard(ticker: str, count: int = 2) -> int:
    return zlib.crc32(ticker.strip().upper().encode("utf-8")) % count


class _FakeUw:
    """Stand-in UW client; the job calls fetch_option_contract_intraday which
    we monkeypatch, so this only needs to exist as a placeholder handle."""


def _seed_ticker_with_movers(repo, ticker: str, trade_date: date) -> None:
    run_id = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(
        run_id, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
    repo.finish_scan_run(run_id, status="ok")
    repo.upsert_watchlist_card(
        ticker=ticker,
        run_id=run_id,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("100.00"),
        iv_atm=Decimal("0.50"),
        iv_rank=Decimal("40.0"),
    )
    # One OI mover so fetch_oi_change_top returns a row to fetch. The source
    # table is oi_change_events (NOT "oi_change_top" — that is the method name,
    # not a table); its ticker column is underlying_symbol; PK (run_id,
    # option_symbol). fetch_oi_change_top reads e.option_symbol + e.curr_date,
    # which the job consumes as row["option_symbol"]/row["curr_date"].
    occ = f"{ticker}260710C00100000"
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.oi_change_events
                (run_id, underlying_symbol, option_symbol, curr_date, rnk, volume, avg_price)
            VALUES (%s, %s, %s, %s, 1, 500, 1.25)
            """,
            (run_id, ticker, occ, trade_date),
        )
    repo.conn.commit()


def test_unfiltered_job_covers_both_shards(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    td = date(2026, 6, 23)
    # Pick two real watchlist tickers on opposite shards (count=2).
    a, b = "AAPL", "TSLA"
    assert _shard(a) != _shard(b), "fixture assumption: opposite shards"
    _seed_ticker_with_movers(repo, a, td)
    _seed_ticker_with_movers(repo, b, td)

    attempted: list[str] = []

    def _fake_fetch(client, r, run_id, option_symbol, date_str):
        attempted.append(option_symbol)
        return []  # no buckets; we only care that the fetch was attempted

    monkeypatch.setattr(
        "uw_scan.worker.jobs.option_intraday_jobs.fetch_option_contract_intraday",
        _fake_fetch,
    )

    # Settings is a plain BaseModel with a REQUIRED api_key (no default), so
    # bare Settings() raises ValidationError. The job only reads
    # settings.db_schema, so a SimpleNamespace stub keyed to the test schema is
    # the correct, dependency-free double (mirrors the _FakeSettings pattern in
    # test_option_surface_iv_canary.py).
    settings = SimpleNamespace(db_schema=repo._schema)
    summary = refresh_intraday_for_top_oi_movers(
        repo=repo, client=_FakeUw(), settings=settings, ticker_filter=None
    )

    # Both shards' contracts were attempted — the #180 regression guard.
    assert any(s.startswith("AAPL") for s in attempted)
    assert any(s.startswith("TSLA") for s in attempted)
    # New counter surface exists.
    for key in (
        "tickers",
        "contracts",
        "buckets",
        "skipped_no_run",
        "skipped_no_movers",
        "contracts_empty",
        "contracts_error",
    ):
        assert key in summary
