"""_run_greek_exposure must heal gex_scan_tickers (E4).

The nightly greek_exposure_daily_refresh job skips settings.gex_scan_tickers to
avoid double-fetching with the regime GEX scan. Delegating the HEAL to that job
made exactly those 11 mega-caps/ETFs unhealable, and `skipped_index` made the
skip look deliberate. The heal path needs its own writer.
"""

from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    RequestBudget,
    _run_greek_exposure,
)


class _StubUw:
    """Stand-in for UwClient; uw_client() returns it without building a real one."""


def test_heals_a_gex_scan_ticker(seeded_db_empty_cards, monkeypatch) -> None:
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    # AAPL is in settings.gex_scan_tickers -> the old adapter skipped it.
    assert "AAPL" in {t.upper() for t in settings.gex_scan_tickers}

    # The parser's REAL key is `date`, not `trade_date`. Stubbing `trade_date`
    # here would make the test pass while production raises KeyError — the exact
    # way a test masks a contract error.
    series = [
        {"date": date(2026, 8, 11), "call_gex": 1.0, "put_gex": -2.0},
        {"date": date(2026, 8, 12), "call_gex": 3.0, "put_gex": -4.0},
    ]
    monkeypatch.setattr(
        "uw_scan.scanners.gex.fetch_aggregate_gex",
        lambda client, r, run_id, ticker: series,
    )

    ctx = HealContext(
        repo=repo,
        gap=None,
        schema=repo._schema,
        today=date(2026, 8, 16),
        budget=RequestBudget(uw_cap=None),
        settings=settings,
    )
    ctx._uw = _StubUw()

    written = _run_greek_exposure(ctx, "AAPL", date(2026, 8, 11), date(2026, 8, 12))

    assert written == 2
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {repo._schema}.greek_exposure_daily "
            "WHERE UPPER(ticker) = 'AAPL' AND trade_date IN (%s, %s)",
            (date(2026, 8, 11), date(2026, 8, 12)),
        )
        assert cur.fetchone()[0] == 2
