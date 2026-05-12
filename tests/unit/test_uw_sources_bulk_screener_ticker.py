"""fetch_bulk_screener_ticker delegates to fetch_bulk_screener with a `ticker=`
param and returns the first row (or None when empty).

Tested as a delegation wrapper: the underlying `fetch_bulk_screener` is the
existing audit/raw-payload-persisting code path and is exercised by integration
tests against the real UW client. Here we just verify the wrapper contract.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from uw_scan.models import BulkScreenerRow
from uw_scan.sources import uw as uw_sources


def _fake_row(ticker: str) -> BulkScreenerRow:
    return BulkScreenerRow(
        ticker=ticker,
        call_open_interest=1_200_000,
        put_open_interest=2_100_000,
        put_volume_ask_side=400_000,
        put_call_ratio=Decimal("1.75"),
    )


def test_fetch_bulk_screener_ticker_returns_first_row():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(
        uw_sources, "fetch_bulk_screener", return_value=[_fake_row("TSLA")]
    ) as mock_bulk:
        row = uw_sources.fetch_bulk_screener_ticker(
            client, repo, run_id=42, ticker="TSLA"
        )
    assert isinstance(row, BulkScreenerRow)
    assert row.ticker == "TSLA"
    assert row.call_open_interest == 1_200_000
    assert row.put_call_ratio == Decimal("1.75")
    assert row.put_volume_ask_side == 400_000
    mock_bulk.assert_called_once()
    kwargs = mock_bulk.call_args.kwargs
    assert kwargs.get("ticker") == "TSLA"


def test_fetch_bulk_screener_ticker_returns_none_when_empty():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(uw_sources, "fetch_bulk_screener", return_value=[]):
        row = uw_sources.fetch_bulk_screener_ticker(
            client, repo, run_id=42, ticker="ZZZZ"
        )
    assert row is None
