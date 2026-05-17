"""fetch_bulk_screener_ticker returns one row for the given ticker.

Specifically guards against the `is_s_p_500` filter: passing
`is_s_p_500=false` would silently exclude S&P 500 names like AAPL/MSFT/
NVDA (the screener returns zero rows for them), causing every PCR /
positioning field on the watchlist card to come back null.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from uw_scan.models import BulkScreenerRow, EtfInfo
from uw_scan.sources import uw as uw_sources


def _fake_response_body(ticker: str) -> dict:
    return {
        "data": [
            {
                "ticker": ticker,
                "call_open_interest": 1_200_000,
                "put_open_interest": 2_100_000,
                "put_volume_ask_side": 400_000,
                "put_call_ratio": "1.75",
            }
        ]
    }


def test_fetch_bulk_screener_ticker_returns_first_row():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(
        uw_sources, "_fetch_json", return_value=_fake_response_body("TSLA")
    ) as mock_fetch:
        row = uw_sources.fetch_bulk_screener_ticker(
            client, repo, run_id=42, ticker="TSLA"
        )
    assert isinstance(row, BulkScreenerRow)
    assert row.ticker == "TSLA"
    assert row.call_open_interest == 1_200_000
    assert row.put_call_ratio == Decimal("1.75")
    # Regression guard: must NOT pass is_s_p_500 (any value of it filters out
    # half the watchlist — `true` excludes everything except the 500,
    # `false` excludes the 500 themselves).
    params = mock_fetch.call_args.kwargs.get("params") or {}
    assert "is_s_p_500" not in params
    assert params.get("ticker") == "TSLA"


def test_fetch_bulk_screener_ticker_returns_none_when_empty():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(uw_sources, "_fetch_json", return_value={"data": []}):
        row = uw_sources.fetch_bulk_screener_ticker(
            client, repo, run_id=42, ticker="ZZZZ"
        )
    assert row is None


def test_fetch_etf_info_returns_aum():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(
        uw_sources,
        "_fetch_json",
        return_value={"data": {"aum": "428887833900", "name": "SPDR S&P 500 ETF"}},
    ) as mock_fetch:
        row = uw_sources.fetch_etf_info(client, repo, run_id=42, ticker="SPY")

    assert isinstance(row, EtfInfo)
    assert row.aum == Decimal("428887833900")
    assert mock_fetch.call_args.args[3] == uw_sources.EndpointSlug.ETF_INFO


def test_fetch_etf_in_outflow_returns_recent_flow_rows():
    client = MagicMock()
    repo = MagicMock()
    with patch.object(
        uw_sources,
        "_fetch_json",
        return_value={
            "data": [
                {
                    "date": "2026-05-15",
                    "change": -900000,
                    "change_prem": "-375300000",
                    "close": "417.29",
                    "volume": 8801181,
                    "expiration_cycle": "monthly",
                    "is_fomc": False,
                }
            ]
        },
    ) as mock_fetch:
        rows = uw_sources.fetch_etf_in_outflow(
            client,
            repo,
            run_id=42,
            ticker="GLD",
            start_date="2026-04-02",
            end_date="2026-05-17",
        )

    assert len(rows) == 1
    assert rows[0].ticker == "GLD"
    assert rows[0].date.isoformat() == "2026-05-15"
    assert rows[0].change == Decimal("-900000")
    assert rows[0].change_prem == Decimal("-375300000")
    assert rows[0].close == Decimal("417.29")
    assert mock_fetch.call_args.args[3] == uw_sources.EndpointSlug.ETF_IN_OUTFLOW
    assert mock_fetch.call_args.kwargs["params"] == {
        "start_date": "2026-04-02",
        "end_date": "2026-05-17",
    }
