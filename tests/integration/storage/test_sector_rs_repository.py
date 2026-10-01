"""sector_rs_daily persistence: idempotent upsert, ordering, latest-as-of.

Row values are the real XLK-vs-SPY numbers measured to 2026-09-18
(apex adjusted, adjustment_revision 81; see Task 2's fixture).
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.sector_rs import SectorRsRepository

from uw_scan.reports.sector_rs import SectorRsRow


def _repo(seeded) -> SectorRsRepository:
    return SectorRsRepository(seeded.conn, schema=seeded._schema)


def _row(
    as_of: date,
    *,
    key: str = "Technology",
    rs12: float = 23.315,
    degraded: bool = False,
    source: str = "apex",
) -> SectorRsRow:
    return SectorRsRow(
        as_of=as_of,
        group_kind="gics",
        group_key=key,
        weighting="etf",
        rs_symbol="XLK",
        n_members=3,
        n_classified=3,
        n_priced=3,
        rs={"1m": 3.958, "3m": -3.098, "6m": 20.954, "12m": rs12},
        breadth={"1m": 1.0, "3m": 1.0, "6m": 1.0, "12m": 2 / 3},
        degraded=degraded,
        source=source,
    )


def test_upsert_is_idempotent_and_last_write_wins(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    d = date(2026, 9, 18)
    assert r.upsert_rows([_row(d)]) == 1
    assert r.upsert_rows([_row(d, rs12=-1.5, degraded=True, source="daily_ohlc")]) == 1
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {seeded_db_empty_cards._schema}.sector_rs_daily"
        )
        assert cur.fetchone()[0] == 1
    (got,) = r.history("gics", "Technology", d)
    assert got == _row(d, rs12=-1.5, degraded=True, source="daily_ohlc")


def test_empty_upsert_writes_nothing(seeded_db_empty_cards):
    assert _repo(seeded_db_empty_cards).upsert_rows([]) == 0


def test_history_is_ascending_and_bounded_by_since(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    days = [date(2026, 9, 18), date(2026, 9, 11), date(2026, 9, 14)]
    r.upsert_rows([_row(d) for d in days])
    r.upsert_rows([_row(date(2026, 9, 14), key="Energy")])
    assert [
        x.as_of for x in r.history("gics", "Technology", date(2026, 9, 1))
    ] == sorted(days)
    assert [x.as_of for x in r.history("gics", "Technology", date(2026, 9, 14))] == [
        date(2026, 9, 14),
        date(2026, 9, 18),
    ]


def test_latest_returns_the_last_session_at_or_before_as_of(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.upsert_rows(
        [
            _row(date(2026, 9, 11)),
            _row(date(2026, 9, 18)),
            _row(date(2026, 9, 18), key="Energy"),
        ]
    )
    sat = r.latest(date(2026, 9, 19), "gics")
    assert [(x.as_of, x.group_key) for x in sat] == [
        (date(2026, 9, 18), "Energy"),
        (date(2026, 9, 18), "Technology"),
    ]
    assert [x.as_of for x in r.latest(date(2026, 9, 12), "gics")] == [date(2026, 9, 11)]
    assert r.latest(date(2026, 9, 19), "chain") == []


def test_dates_present_per_kind(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.upsert_rows([_row(date(2026, 9, 11)), _row(date(2026, 9, 18))])
    assert r.dates_present("gics", date(2026, 9, 1), date(2026, 9, 15)) == {
        date(2026, 9, 11)
    }
    assert r.dates_present("chain", date(2026, 9, 1), date(2026, 9, 30)) == set()
