from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once


class _FakeProvider:
    def fetch_splits(self, ticker, *, limit=12):
        return [
            {
                "execution_date": date(2024, 6, 10),
                "split_from": Decimal("1"),
                "split_to": Decimal("10"),
            }
        ]

    def fetch_dividends(self, ticker, *, limit=24):
        return [{"ex_dividend_date": date(2024, 9, 12), "cash_amount": Decimal("0.01")}]


def test_ingest_writes_events(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    monkeypatch.setattr(
        repo, "list_active_watchlist", lambda: [SimpleNamespace(ticker="NVDA")]
    )
    n = corporate_actions_refresh_once(repo, _FakeProvider())
    # Regression guard: the function MUST commit its own writes (the scheduler's
    # _repo closes the connection without committing). Roll back here — if the
    # ingest left work uncommitted, this discards it and the assert below fails.
    repo.conn.rollback()
    assert n == 1
    rows = repo.fetch_corporate_actions("NVDA")
    assert {r["event_type"] for r in rows} == {"split", "dividend"}
    split = next(r for r in rows if r["event_type"] == "split")
    assert split["split_ratio"] == Decimal("10")


def test_null_provider_noops(seeded_db_empty_cards):
    assert corporate_actions_refresh_once(seeded_db_empty_cards, None) == 0


def test_ingest_covers_the_fundamental_universe(seeded_db_empty_cards, monkeypatch):
    """A universe name with no watchlist or VRP row must still get its splits.

    This is the half that was broken in production: the store held 137 of the
    fundamental universe's 450 names on 2026-08-21, and 9 of the 19 names whose
    valuation band was priced across an unadjusted split — BKNG, CTAS, CPRT,
    DXCM, FAST, FTNT, ETR, NVTS, CXAI — had no row at all. `load_raw_closes`
    cannot adjust for an event nobody fetched, so a band built on a name missing
    here is silently wrong rather than absent.
    """
    repo = seeded_db_empty_cards
    monkeypatch.setattr(repo, "list_active_watchlist", lambda: [])
    monkeypatch.setattr(repo, "fetch_distinct_vrp_tickers", lambda: [])
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.fundamental_universe (ticker, tier, reason) "
            "VALUES ('BKNG', 'ranked', 'test') ON CONFLICT DO NOTHING"
        )
    repo.conn.commit()

    assert corporate_actions_refresh_once(repo, _FakeProvider()) == 1
    repo.conn.rollback()
    assert [r["event_type"] for r in repo.fetch_corporate_actions("BKNG")] == [
        "split",
        "dividend",
    ]


def test_split_factors_reads_the_universe_in_one_pass(seeded_db_empty_cards):
    """`split_factors` is what the anchors job reads, so it must agree with the
    ingest and drop rows that cannot answer the question it is asked.

    A null or non-positive ratio is not evidence that a split happened on a
    usable basis, so those rows are dropped rather than defaulted — counting one
    would refuse a band on a row that says nothing.
    """
    from decimal import Decimal

    repo = seeded_db_empty_cards
    for ticker, ratio in (("BKNG", Decimal("25")), ("CTAS", None)):
        repo.upsert_corporate_action(
            ticker=ticker,
            event_type="split",
            event_date=date(2026, 4, 6),
            split_ratio=ratio,
        )
    repo.upsert_corporate_action(
        ticker="BKNG",
        event_type="dividend",
        event_date=date(2026, 4, 6),
        cash_amount=Decimal("0.50"),
    )
    repo.conn.commit()

    got = repo.split_factors(["bkng", "CTAS"])
    assert got == {"BKNG": [(date(2026, 4, 6), 25.0)]}
    assert repo.split_factors([]) == {}


def test_ingested_tickers_counts_a_dividend_as_evidence(seeded_db_empty_cards):
    """The distinction the anchors guard turns on: "never split" vs "never asked".

    A name the ingest reached but that never split has an empty `split_factors`
    entry and must still be bandable from bronze, so membership here cannot be
    split-only — a dividend row proves the ingest arrived. A name it never
    reached has nothing at all, and that is the one the guard must refuse: on
    2026-08-22 that described 15 of the 18 names with no silver series, back
    when the ingest covered 137 of the universe's 450.
    """
    from decimal import Decimal

    repo = seeded_db_empty_cards
    repo.upsert_corporate_action(
        ticker="CTAS",
        event_type="dividend",
        event_date=date(2026, 4, 6),
        cash_amount=Decimal("0.50"),
    )
    repo.conn.commit()

    assert repo.split_factors(["CTAS"]) == {}
    assert repo.ingested_tickers(["ctas", "HON"]) == {"CTAS"}
    assert repo.ingested_tickers([]) == set()
