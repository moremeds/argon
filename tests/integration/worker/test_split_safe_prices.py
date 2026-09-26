"""Price inputs stay split-safe: the nightly OHLC pull repairs a restated history,
and stock_analytics rvol comes from daily_ohlc closes, not UW's raw `price`.

Fixture: KLAC across its real 10:1 split on 2026-06-12 (UW price is raw before it,
massive's close is adjusted), frozen in tests/unit/cards/test_vol_series_trailing_rv.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from tests.unit.cards.test_vol_series_trailing_rv import KLAC_ROWS
from uw_scan.models import RealizedVolRow
from uw_scan.sources.ohlc import OhlcBar
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.volatility_jobs import nightly_vol_analytics_rollup

pytestmark = pytest.mark.integration

_DATES = [date.fromisoformat(d) for d, _p, _c in KLAC_ROWS]
_RAW = [Decimal(str(p)) for _d, p, _c in KLAC_ROWS]
_ADJ = [Decimal(str(c)) for _d, _p, c in KLAC_ROWS]


def _seed_ohlc(repo, closes: list[Decimal]) -> None:
    for d, c in zip(_DATES, closes, strict=True):
        repo.upsert_daily_ohlc(
            ticker="KLAC",
            date=d,
            open=None,
            high=None,
            low=None,
            close=c,
            volume=None,
            source="massive.com",
        )


def _provider(window_from: int) -> MagicMock:
    """First call = the nightly window (tail of the series); later calls honour `start`."""
    calls: list[date] = []

    def fetch(ticker, start, end):
        calls.append(start)
        idx = (
            range(window_from, len(_DATES))
            if len(calls) == 1
            else [i for i, d in enumerate(_DATES) if d >= start]
        )
        return [
            OhlcBar(
                ticker=ticker,
                date=_DATES[i],
                open=None,
                high=None,
                low=None,
                close=_ADJ[i],
                volume=None,
            )
            for i in idx
        ]

    prov = MagicMock()
    prov.fetch_daily.side_effect = fetch
    prov.calls = calls
    return prov


def _stored(repo) -> list[Decimal]:
    rows = sorted(repo.list_daily_ohlc("KLAC", limit=100), key=lambda r: r.date)
    return [r.close for r in rows]


def test_ohlc_pull_repulls_full_history_after_split(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.add_watchlist_ticker(ticker="KLAC", sector="Semis")
    _seed_ohlc(repo, _RAW)  # stored before the split: unadjusted
    prov = _provider(
        window_from=_DATES.index(date(2026, 6, 8))
    )  # window spans the split

    ohlc_pull_once(repo, prov, ticker_filter=lambda t: t == "KLAC")

    assert len(prov.calls) == 2
    assert prov.calls[1] == _DATES[0]  # re-pulled from the earliest stored date
    assert _stored(repo) == _ADJ  # no raw/adjusted seam left


def test_ohlc_pull_single_call_when_history_unchanged(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.add_watchlist_ticker(ticker="KLAC", sector="Semis")
    _seed_ohlc(repo, _ADJ)
    prov = _provider(window_from=20)

    ohlc_pull_once(repo, prov, ticker_filter=lambda t: t == "KLAC")

    assert len(prov.calls) == 1
    assert _stored(repo) == _ADJ


def test_stock_analytics_rvol_uses_adjusted_closes(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.add_watchlist_ticker(ticker="KLAC", sector="Semis")
    run_id = repo.insert_scan_run("KLAC")
    repo.upsert_watchlist_card(
        ticker="KLAC", run_id=run_id, scanned_at=datetime.now(timezone.utc)
    )
    repo.upsert_realized_vol_rows(
        "KLAC",
        [
            RealizedVolRow(
                date=d,
                price=p,
                implied_volatility=Decimal("0.45"),
                realized_volatility=None,
            )
            for d, p in zip(_DATES, _RAW, strict=True)
        ],
    )
    _seed_ohlc(repo, _ADJ)
    repo.conn.commit()

    nightly_vol_analytics_rollup(repo=repo)

    rvol = [
        r["rvol_21"]
        for r in repo.fetch_stock_analytics_series("KLAC", limit=100)
        if r["rvol_21"] is not None
    ]
    assert rvol  # 42 closes → rows past the 21-return warm-up
    # UW's raw price drops 2411.64 → 254.54 across the split, an RV of ~5 for 21 rows.
    assert max(float(v) for v in rvol) < 1.5
