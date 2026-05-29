"""Integration test for fundamentals_refresh_once — real repo + fake provider."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once


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


def test_job_no_provider_is_noop(seeded_db_empty_cards):
    assert fundamentals_refresh_once(seeded_db_empty_cards, None) == 0


def test_job_skips_outside_shard(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert (
        fundamentals_refresh_once(repo, _FakeProvider(), ticker_filter=lambda t: False)
        == 0
    )
