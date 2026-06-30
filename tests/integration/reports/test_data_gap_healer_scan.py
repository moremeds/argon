from __future__ import annotations

from datetime import UTC, date, datetime

from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    audit,
    discover_unregistered_tables,
    registered_table_names,
)
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository


def _ohlc(repo, ticker: str, d: date) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ticker, d, 1.0, "test"),
        )
    repo.conn.commit()


def _sentiment_session(repo, d: date) -> None:
    """Reference equity-session calendar row."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.market_tide_sentiment_daily "
            "(data_date, state, magnitude, driver, momentum, bars) "
            "VALUES (%s, 'BALANCED', 'FLAT', 'x', 'x', 1) ON CONFLICT DO NOTHING",
            (d,),
        )
    repo.conn.commit()


def _tide_snapshot(repo, d: date) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.market_tide_snapshots "
            "(data_date, ts, net_call_premium, net_put_premium) "
            "VALUES (%s, %s, 0, 0)",
            (d, datetime(d.year, d.month, d.day, 15, 0, tzinfo=UTC)),
        )
    repo.conn.commit()


def _entry(name: str):
    return next(e for e in REGISTRY if e.table_name == name)


def test_strict_ticker_date_finds_missing_pairs(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    _ohlc(repo, "AAPL", d1)
    _ohlc(repo, "AAPL", d2)
    _ohlc(repo, "NVDA", d1)  # NVDA missing d2

    summaries, items = audit(
        repo.conn,
        repo._schema,
        [_entry("daily_ohlc")],
        active=["AAPL", "NVDA"],
        caveats=[],
        start=d1,
        end=d2,
    )
    assert len(items) == 1
    assert items[0].ticker == "NVDA"
    assert items[0].data_date == d2
    assert items[0].scope_key == f"{d2.isoformat()}|NVDA"
    s = summaries[0]
    assert (s.expected_pairs, s.covered_pairs, s.missing_pairs) == (4, 3, 1)
    assert s.gap_dates == (d2,)


def test_caveat_suppresses_ticker_before_listing(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    before, after = date(2026, 6, 10), date(2026, 6, 18)
    _ohlc(repo, "AAPL", before)
    _ohlc(repo, "AAPL", after)
    # the seeded SPCX caveat ends 2026-06-16 -> SPCX excluded on/before, included after
    caveats = DataGapHealerRepository(repo.conn, repo._schema).list_caveats()

    _, items = audit(
        repo.conn,
        repo._schema,
        [_entry("daily_ohlc")],
        active=["AAPL", "SPCX"],
        caveats=caveats,
        start=before,
        end=after,
    )
    keys = {(it.ticker, it.data_date) for it in items}
    assert keys == {("SPCX", after)}  # SPCX@before suppressed, AAPL fully present


def test_strict_session_finds_missing_days(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d1, d2, d3 = date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)
    for d in (d1, d2, d3):
        _sentiment_session(repo, d)  # reference calendar has all three
    _tide_snapshot(repo, d1)
    _tide_snapshot(repo, d3)  # snapshot missing d2

    summaries, items = audit(
        repo.conn,
        repo._schema,
        [_entry("market_tide_snapshots")],
        active=[],
        caveats=[],
        start=d1,
        end=d3,
    )
    assert len(items) == 1
    assert items[0].data_date == d2
    assert items[0].ticker is None
    assert (summaries[0].expected_pairs, summaries[0].missing_pairs) == (3, 1)


def test_discover_excludes_registered_tables(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    unreg = discover_unregistered_tables(repo.conn, repo._schema)
    assert isinstance(unreg, list)
    assert registered_table_names(REGISTRY).isdisjoint(unreg)
