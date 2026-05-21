"""Cockpit daily snapshot must persist exposures_summary after greek_exposure rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import GreekExposureRow
from uw_scan.storage.repository import Repository


def _seed_scan_run(repo: Repository, run_id: int) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, 'TSLA', now()) ON CONFLICT DO NOTHING",
            (run_id,),
        )
    repo.conn.commit()


def test_summary_persisted_alongside_greek_exposure(seeded_db_empty_cards: Repository):
    """Smoke: insert greek-exposure rows, call build_summary_rows + upsert,
    one summary row appears per expiry."""
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=10)

    rows = [
        GreekExposureRow(
            date=date.fromisoformat("2026-05-21"),
            expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("100"),
            dte=9,
            call_vanna=Decimal("100"),
            put_vanna=Decimal("-30"),
            call_charm=Decimal("-2000"),
            put_charm=Decimal("500"),
        ),
        GreekExposureRow(
            date=date.fromisoformat("2026-05-21"),
            expiry=date.fromisoformat("2026-06-20"),
            strike=Decimal("100"),
            dte=30,
            call_vanna=Decimal("10"),
            put_vanna=Decimal("-5"),
            call_charm=Decimal("-200"),
            put_charm=Decimal("50"),
        ),
    ]
    repo.insert_greek_exposure_rows(run_id=10, ticker="TSLA", rows=rows)
    repo.conn.commit()

    summary = build_summary_rows(rows, spot=Decimal("100"))
    repo.upsert_exposures_summary(
        run_id=10,
        ticker="TSLA",
        market_date=date.fromisoformat("2026-05-21"),
        rows=summary,
    )
    repo.conn.commit()

    fetched = repo.fetch_exposures_summary(10, "TSLA")
    assert len(fetched) == 2
    expiries = {r["expiry"] for r in fetched}
    assert expiries == {
        date.fromisoformat("2026-05-30"),
        date.fromisoformat("2026-06-20"),
    }
    assert all(r["vanna_headline"] for r in fetched)
    assert all(r["charm_headline"] for r in fetched)
