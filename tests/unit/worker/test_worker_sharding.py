from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.scheduler import (
    _rescan_worker_concurrency,
    _ticker_shard_filter,
    _worker_groups,
    _worker_owns_ticker,
)


def _settings(**overrides):
    values = {"api_key": SecretStr("uw"), **overrides}
    return Settings(**values)


def test_two_worker_shards_are_exclusive_and_exhaustive() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "SOXX", "TSLA", "XOM"]
    shard_0 = {t for t in tickers if _worker_owns_ticker(t, index=0, count=2)}
    shard_1 = {t for t in tickers if _worker_owns_ticker(t, index=1, count=2)}

    assert shard_0
    assert shard_1
    assert shard_0.isdisjoint(shard_1)
    assert shard_0 | shard_1 == set(tickers)


def test_ticker_shard_filter_is_disabled_for_single_worker() -> None:
    ticker_filter = _ticker_shard_filter(_settings(worker_count=1))

    assert ticker_filter("AAPL") is True
    assert ticker_filter("MSFT") is True


def test_worker_groups_split_provider_roles() -> None:
    assert _worker_groups(_settings(worker_role="uw")) == {"uw"}
    assert _worker_groups(_settings(worker_role="massive")) == {"massive"}
    assert _worker_groups(_settings(worker_role="ai")) == {"ai"}
    assert _worker_groups(_settings(worker_role="all")) == {"uw", "massive", "ai"}


def test_split_uw_workers_run_one_rescan_instance_each() -> None:
    assert _rescan_worker_concurrency(_settings(worker_role="uw", worker_count=2)) == 1
    assert _rescan_worker_concurrency(_settings(worker_role="all", worker_count=1)) == 2


def test_ohlc_pull_respects_ticker_filter() -> None:
    repo = MagicMock()
    repo.list_active_watchlist.return_value = [
        SimpleNamespace(ticker="AAPL"),
        SimpleNamespace(ticker="MSFT"),
    ]
    provider = MagicMock()
    provider.fetch_daily.return_value = []

    ohlc_pull_once(repo, provider, ticker_filter=lambda ticker: ticker == "MSFT")

    assert provider.fetch_daily.call_count == 1
    assert provider.fetch_daily.call_args.args[0] == "MSFT"


def test_full_scan_respects_ticker_filter() -> None:
    repo = MagicMock()
    repo.list_watchlist_cards.return_value = [
        SimpleNamespace(ticker="AAPL", scanned_at=None),
        SimpleNamespace(ticker="MSFT", scanned_at=None),
    ]

    with patch(
        "uw_scan.worker.jobs.full_scan.run_single_stock",
        side_effect=RuntimeError("stop after ownership check"),
    ) as run_single_stock:
        completed = full_scan_once(
            repo,
            MagicMock(),
            MagicMock(),
            ticker_filter=lambda ticker: ticker == "MSFT",
        )

    assert completed == 0
    run_single_stock.assert_called_once()
    assert run_single_stock.call_args.args[0] == "MSFT"


def _four_stale_cards() -> list[SimpleNamespace]:
    # hot-first order is applied by the repo SQL; here they arrive pre-ordered.
    return [
        SimpleNamespace(ticker=t, scanned_at=None)
        for t in ("AAPL", "MSFT", "NVDA", "TSLA")
    ]


def test_full_scan_max_tickers_caps_the_cold_tail() -> None:
    """The governor's core promise: with a budget cap, only the first N stale
    tickers are scanned and the rest are dropped (not 429-stormed)."""
    repo = MagicMock()
    repo.list_watchlist_cards.return_value = _four_stale_cards()

    with patch(
        "uw_scan.worker.jobs.full_scan.run_single_stock",
        side_effect=RuntimeError("counted then swallowed"),
    ) as run_single_stock:
        full_scan_once(repo, MagicMock(), MagicMock(), max_tickers=2)

    # first two (AAPL, MSFT) scanned; NVDA/TSLA cold tail dropped.
    assert run_single_stock.call_count == 2
    assert [c.args[0] for c in run_single_stock.call_args_list] == ["AAPL", "MSFT"]


def test_full_scan_max_tickers_none_means_no_cap() -> None:
    repo = MagicMock()
    repo.list_watchlist_cards.return_value = _four_stale_cards()

    with patch(
        "uw_scan.worker.jobs.full_scan.run_single_stock",
        side_effect=RuntimeError("counted then swallowed"),
    ) as run_single_stock:
        full_scan_once(repo, MagicMock(), MagicMock(), max_tickers=None)

    assert run_single_stock.call_count == 4


def test_full_scan_max_tickers_zero_scans_nothing() -> None:
    repo = MagicMock()
    repo.list_watchlist_cards.return_value = _four_stale_cards()

    with patch(
        "uw_scan.worker.jobs.full_scan.run_single_stock",
        side_effect=RuntimeError("should never be called"),
    ) as run_single_stock:
        full_scan_once(repo, MagicMock(), MagicMock(), max_tickers=0)

    run_single_stock.assert_not_called()
