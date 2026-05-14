"""Worker job tests: spot refresh, full scan, OHLC pull, rescan loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from uw_scan.models import (
    FlowSnapshot,
    MarketStructure,
    SingleStockReport,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.sources.ohlc import IntradayQuote, OhlcBar


def _stub_report(ticker: str = "TSLA", run_id: int = 999) -> SingleStockReport:
    return SingleStockReport(
        run_id=run_id,
        ticker=ticker,
        generated_at=datetime.now(timezone.utc),
        market_structure=MarketStructure(spot=Decimal("445")),
        volatility=VolatilityProfile(iv=Decimal("0.5")),
        flow=FlowSnapshot(
            ticker=ticker,
            flow_count=0,
            net_premium=Decimal("0"),
            bull_premium=Decimal("0"),
            bear_premium=Decimal("0"),
            ask_side_premium=Decimal("0"),
            bid_side_premium=Decimal("0"),
        ),
        vrp=VRPAssessment(vrp=None, signal="—", note=""),
    )


# ---- spot_refresh --------------------------------------------------------


def test_spot_refresh_updates_quote_and_card(seeded_db_with_cards):
    from uw_scan.worker.jobs.spot_refresh import spot_refresh_once

    fake = MagicMock()
    fake.fetch_intraday_quote.side_effect = lambda t, **_kw: IntradayQuote(
        ticker=t,
        price=Decimal("999.99"),
        quoted_at=datetime(2026, 5, 8, 13, 0, tzinfo=timezone.utc),
    )
    n = spot_refresh_once(seeded_db_with_cards, fake)
    assert n >= 1
    q = seeded_db_with_cards.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("999.9900")
    card = seeded_db_with_cards.get_watchlist_card("TSLA")
    assert card.spot == Decimal("999.9900")
    assert card.spot_source == "massive.com_intraday"


def test_spot_refresh_skips_when_no_quote(seeded_db_with_cards):
    from uw_scan.worker.jobs.spot_refresh import spot_refresh_once

    fake = MagicMock()
    fake.fetch_intraday_quote.return_value = None
    assert spot_refresh_once(seeded_db_with_cards, fake) == 0


def test_spot_refresh_passes_market_date_to_provider(seeded_db_with_cards):
    from uw_scan.worker.jobs.spot_refresh import spot_refresh_once

    fake = MagicMock()
    fake.fetch_intraday_quote.return_value = None
    spot_refresh_once(
        seeded_db_with_cards,
        fake,
        market_date=date(2026, 5, 13),
    )

    fake.fetch_intraday_quote.assert_any_call("TSLA", market_date=date(2026, 5, 13))


# ---- full_scan -----------------------------------------------------------


def test_full_scan_writes_card_for_active_tickers(seeded_db_empty_cards):
    from uw_scan.worker.jobs.full_scan import full_scan_once

    repo = seeded_db_empty_cards
    real_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(real_run_id, status="ok")

    fake_uw = MagicMock()
    fake_ohlc = MagicMock()
    with patch(
        "uw_scan.worker.jobs.full_scan.run_single_stock",
        side_effect=lambda ticker, *_a, **_k: _stub_report(ticker, run_id=real_run_id),
    ):
        n = full_scan_once(repo, fake_uw, fake_ohlc)
    assert n >= 1
    card = repo.get_watchlist_card("TSLA")
    assert card is not None
    assert card.spot == Decimal("445")


# ---- ohlc_pull -----------------------------------------------------------


def test_ohlc_pull_writes_daily_rows(seeded_db_empty_cards):
    from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once

    today = date(2026, 5, 8)
    fake = MagicMock()
    fake.fetch_daily.side_effect = lambda t, start, end: [
        OhlcBar(
            ticker=t,
            date=today - timedelta(days=i),
            open=None,
            high=None,
            low=None,
            close=Decimal(str(100 + i)),
            volume=10_000,
        )
        for i in range(30)
    ]
    n = ohlc_pull_once(seeded_db_empty_cards, fake, lookback_days=30)
    assert n >= 1
    rows = seeded_db_empty_cards.list_daily_ohlc("TSLA", limit=10)
    assert len(rows) >= 1


# ---- rescan_loop ---------------------------------------------------------


def test_rescan_tick_returns_false_when_queue_empty(seeded_db_with_cards):
    from uw_scan.worker.jobs.rescan_loop import rescan_tick

    assert rescan_tick(seeded_db_with_cards, MagicMock(), MagicMock()) is False


def test_rescan_tick_claims_and_marks_done(seeded_db_with_cards):
    from uw_scan.worker.jobs.rescan_loop import rescan_tick

    repo = seeded_db_with_cards
    new_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(new_run_id, status="ok")
    job_id = repo.enqueue_rescan_job("TSLA")

    with patch(
        "uw_scan.worker.jobs.rescan_loop.run_single_stock",
        side_effect=lambda ticker, *_a, **_k: _stub_report(ticker, run_id=new_run_id),
    ):
        worked = rescan_tick(repo, MagicMock(), MagicMock())
    assert worked is True
    job = repo.get_job(job_id)
    assert job is not None
    assert job.status == "done"
    assert job.run_id == new_run_id


def test_rescan_tick_marks_failed_on_exception(seeded_db_with_cards):
    from uw_scan.worker.jobs.rescan_loop import rescan_tick

    job_id = seeded_db_with_cards.enqueue_rescan_job("TSLA")
    with patch(
        "uw_scan.worker.jobs.rescan_loop.run_single_stock",
        side_effect=RuntimeError("boom"),
    ):
        worked = rescan_tick(seeded_db_with_cards, MagicMock(), MagicMock())
    assert worked is True
    job = seeded_db_with_cards.get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert "boom" in (job.error or "")
