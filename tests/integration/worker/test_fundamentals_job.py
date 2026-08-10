"""Integration test for fundamentals_refresh_once — real repo + fake provider.

Persistence assertions go through a **separate connection** (`_fetched_at`). The
job's own connection is non-autocommit, so reading back on it proves only that
the statements ran — which is exactly how the job shipped for months while
committing nothing.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import psycopg

from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once


def _fetched_at(settings, ticker: str) -> datetime | None:
    """Read `fetched_at` over a NEW connection — sees only committed rows."""
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max(fetched_at) FROM uw_scan.massive_fundamentals "
            "WHERE ticker = %s",
            (ticker.upper(),),
        )
        return cur.fetchone()[0]


class _FakeProvider:
    """Returns 5 quarters so share_count_delta (idx>=4) is exercised."""

    def fetch_financials(self, ticker, *, timeframe="quarterly", limit=8):
        periods = [
            date(2025, 3, 28),
            date(2025, 6, 28),
            date(2025, 9, 28),
            date(2025, 12, 28),
            date(2026, 3, 28),
        ]
        rows = []
        for i, pe in enumerate(periods):
            rows.append(
                {
                    "period_end": pe,
                    "fiscal_period": f"Q{(i % 4) + 1}",
                    "filing_date": pe,
                    "revenue": Decimal("1000"),
                    "gross_profit": Decimal("600"),
                    "operating_income": Decimal("250"),
                    "net_income": Decimal("180"),
                    "total_assets": Decimal("5000"),
                    "total_debt": Decimal("800"),
                    "shareholders_equity": Decimal("3000"),
                    # diluted shares grow 10% over the 5 quarters (idx 0 -> idx 4)
                    "diluted_shares": Decimal("1000") + Decimal(i) * Decimal("25"),
                    "operating_cash_flow": Decimal("300"),
                    "investing_cash_flow": Decimal("-50"),
                    "raw": {"end_date": pe.isoformat()},
                }
            )
        return rows

    def fetch_dividends(self, ticker, *, limit=4):
        return [{"ex_dividend_date": date(2026, 5, 11), "cash_amount": Decimal("0.26")}]

    def fetch_splits(self, ticker, *, limit=4):
        return [
            {
                "execution_date": date(2020, 8, 31),
                "split_from": Decimal("1"),
                "split_to": Decimal("4"),
            }
        ]


def _first_active_ticker(repo) -> str:
    actives = repo.list_active_watchlist()
    assert actives
    return actives[0].ticker


def test_job_persists_quarters_with_derived_fields(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    n = fundamentals_refresh_once(
        repo, _FakeProvider(), ticker_filter=lambda t: t == target
    )
    assert n == 1

    # 5 quarters persisted
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.massive_fundamentals WHERE ticker = %s",
            (target.upper(),),
        )
        assert cur.fetchone()[0] == 5

    latest = repo.get_massive_fundamentals(target)
    assert latest is not None
    assert latest["period_end"] == date(2026, 3, 28)
    # derived margins
    assert latest["gross_margin"] == Decimal("600") / Decimal("1000")
    assert latest["op_margin"] == Decimal("250") / Decimal("1000")
    assert latest["net_margin"] == Decimal("180") / Decimal("1000")
    # fcf = operating + investing = 300 + (-50)
    assert latest["fcf"] == Decimal("250")
    # share_count_delta: latest 1100 vs 4-quarters-ago 1000 → 0.10
    assert latest["share_count_delta"] == Decimal("1100") / Decimal("1000") - 1
    # corporate-action summary carried on the latest period row
    assert latest["latest_dividend_amount"] == Decimal("0.26")
    assert latest["last_split_ratio"] == Decimal("4")  # split_to/split_from


def test_corporate_action_summary_only_on_latest_row(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    fundamentals_refresh_once(
        repo, _FakeProvider(), ticker_filter=lambda t: t == target
    )
    # an earlier (non-latest) quarter must NOT carry the dividend summary
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT latest_dividend_amount FROM uw_scan.massive_fundamentals "
            "WHERE ticker = %s AND period_end = %s",
            (target.upper(), date(2025, 3, 28)),
        )
        assert cur.fetchone()[0] is None


def test_job_idempotent_on_rerun(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    shard = lambda t: t == target  # noqa: E731
    fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=shard)
    fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=shard)
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.massive_fundamentals WHERE ticker = %s",
            (target.upper(),),
        )
        assert cur.fetchone()[0] == 5  # still 5, not 10


def test_job_commits_visible_from_a_fresh_connection(
    seeded_db_empty_cards, _migrated_settings
):
    """The regression that matters: rows must survive the job's connection.

    A row-count gate would not catch this — production already held 669 rows
    from another path while the scheduled job committed nothing. Assert that a
    *freshness delta* crosses the transaction boundary.
    """
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    shard = lambda t: t == target  # noqa: E731
    assert _fetched_at(_migrated_settings, target) is None

    assert fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=shard) == 1
    first = _fetched_at(_migrated_settings, target)
    assert first is not None, "job did not commit — rows died with the connection"

    # `fetched_at=now()` on conflict, so a rerun that commits must ADVANCE it.
    # Compared against the previous DB value rather than a Python timestamp:
    # Postgres now() is transaction_timestamp(), pinned to the transaction's
    # first statement, so it can legitimately predate a wall clock sampled here.
    assert fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=shard) == 1
    second = _fetched_at(_migrated_settings, target)
    assert second > first


def test_one_ticker_failure_keeps_earlier_tickers(
    seeded_db_empty_cards, _migrated_settings
):
    """One ticker's DB error must not discard the tickers already processed."""

    class _FailsOnSecond(_FakeProvider):
        def __init__(self) -> None:
            self.seen: list[str] = []

        def fetch_financials(self, ticker, *, timeframe="quarterly", limit=8):
            self.seen.append(ticker)
            rows = super().fetch_financials(ticker, limit=limit)
            if len(self.seen) == 2:
                # Must fail SERVER-side, inside the upsert, so the transaction
                # is left aborted — that is the state the rollback clears.
                # `total_assets` is chosen deliberately: it is passed straight
                # through to the numeric column and never enters a Python
                # computation, so the bad value survives to the DB. Corrupting
                # `revenue` instead raises TypeError in the margin division
                # before any statement is sent, which tests nothing.
                rows[0] = {**rows[0], "total_assets": "not-a-number"}
            return rows

    repo = seeded_db_empty_cards
    tickers = [w.ticker for w in repo.list_active_watchlist()][:3]
    assert len(tickers) == 3

    provider = _FailsOnSecond()
    completed = fundamentals_refresh_once(
        repo, provider, ticker_filter=lambda t: t in tickers
    )

    # the failing ticker is skipped, the other two persist
    assert completed == 2
    assert _fetched_at(_migrated_settings, provider.seen[0]) is not None
    assert _fetched_at(_migrated_settings, provider.seen[1]) is None
    assert _fetched_at(_migrated_settings, provider.seen[2]) is not None


def test_job_no_provider_is_noop(seeded_db_empty_cards):
    assert fundamentals_refresh_once(seeded_db_empty_cards, None) == 0


def test_job_skips_outside_shard(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert (
        fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=lambda t: False)
        == 0
    )
