"""Report assembler attaches strike_exposures and exposures_summary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import GreekExposureRow
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.storage.repository import Repository


def _seed_exposures(
    repo: Repository, ticker: str, run_id: int, market_date: date
) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, %s, now()) ON CONFLICT DO NOTHING",
            (run_id, ticker),
        )
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_vanna, put_vanna, call_charm, put_charm,
                 call_gex, put_gex, call_delta, put_delta)
            VALUES
                (%s, %s, %s, '2026-05-30', 100, 9, 100, -30, -2000, 500, 0, 0, 0, 0),
                (%s, %s, %s, '2026-05-30', 110, 9, 200, -50, -3000, 800, 0, 0, 0, 0)
            """,
            (run_id, ticker, market_date, run_id, ticker, market_date),
        )
    repo.conn.commit()


def test_report_includes_strike_exposures_and_summary(
    seeded_db_empty_cards: Repository,
):
    repo = seeded_db_empty_cards
    market_date = date.fromisoformat("2026-05-21")
    _seed_exposures(repo, "TSLA", run_id=20, market_date=market_date)

    raw = [
        GreekExposureRow(
            date=market_date,
            expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("100"),
            dte=9,
            call_vanna=Decimal("100"),
            put_vanna=Decimal("-30"),
            call_charm=Decimal("-2000"),
            put_charm=Decimal("500"),
        ),
        GreekExposureRow(
            date=market_date,
            expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("110"),
            dte=9,
            call_vanna=Decimal("200"),
            put_vanna=Decimal("-50"),
            call_charm=Decimal("-3000"),
            put_charm=Decimal("800"),
        ),
    ]
    repo.upsert_exposures_summary(
        run_id=20,
        ticker="TSLA",
        market_date=market_date,
        rows=build_summary_rows(raw, spot=Decimal("105")),
    )
    repo.conn.commit()

    report = assemble_single_stock_report(ticker="TSLA", run_id=20, repo=repo)
    assert len(report.strike_exposures) == 2
    assert {row.strike for row in report.strike_exposures} == {
        Decimal("100"),
        Decimal("110"),
    }
    assert len(report.exposures_summary) == 1
    summary = report.exposures_summary[0]
    assert summary.expiry == date.fromisoformat("2026-05-30")
    assert summary.vanna_headline
