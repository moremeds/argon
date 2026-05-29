"""Unit tests for the M5 massive fundamentals provider + parsers.

Payloads are SPEC-DERIVED synthetic fixtures: field names + nesting shape are
taken from the massive probe log
(docs/research/goyal-saretto-ipca-options/14-massive-endpoint-probe-log.md) —
vX financials nest real fields under
financials.{income_statement,balance_sheet,cash_flow_statement}.<field>.value.
Not recorded responses.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from uw_scan.sources.massive_fundamentals import (
    MassiveFundamentalsProvider,
    _parse_financials_row,
)


def _vx_row(end_date: str, fiscal: str, revenue, gp, oi, ni, shares) -> dict:
    def leaf(v):
        return {"value": v, "unit": "USD", "label": "x", "order": 1}

    return {
        "end_date": end_date,
        "fiscal_period": fiscal,
        "filing_date": "2026-05-01",
        "financials": {
            "income_statement": {
                "revenues": leaf(revenue),
                "gross_profit": leaf(gp),
                "operating_income_loss": leaf(oi),
                "net_income_loss": leaf(ni),
                "diluted_average_shares": leaf(shares),
            },
            "balance_sheet": {
                "assets": leaf(1000),
                "long_term_debt": leaf(200),
                "equity": leaf(600),
            },
            "cash_flow_statement": {
                "net_cash_flow_from_operating_activities": leaf(150),
                "net_cash_flow_from_investing_activities": leaf(-40),
            },
        },
    }


def test_parse_financials_row_pulls_leaves():
    row = _parse_financials_row(_vx_row("2026-03-28", "Q1", 500, 300, 120, 90, 1000))
    assert row is not None
    assert row["period_end"] == date(2026, 3, 28)
    assert row["fiscal_period"] == "Q1"
    assert row["filing_date"] == date(2026, 5, 1)
    assert row["revenue"] == Decimal("500")
    assert row["gross_profit"] == Decimal("300")
    assert row["operating_income"] == Decimal("120")
    assert row["net_income"] == Decimal("90")
    assert row["total_assets"] == Decimal("1000")
    assert row["total_debt"] == Decimal("200")
    assert row["shareholders_equity"] == Decimal("600")
    assert row["diluted_shares"] == Decimal("1000")
    assert row["operating_cash_flow"] == Decimal("150")
    assert row["investing_cash_flow"] == Decimal("-40")
    assert row["raw"]["end_date"] == "2026-03-28"


def test_parse_financials_row_skips_rows_without_end_date():
    assert _parse_financials_row({"fiscal_period": "Q1"}) is None


def test_parse_financials_row_tolerates_missing_leaves():
    row = _parse_financials_row({"end_date": "2026-03-28", "financials": {}})
    assert row is not None
    assert row["revenue"] is None
    assert row["total_assets"] is None


class _FakeHttpProvider(MassiveFundamentalsProvider):
    """Subclass that stubs the HTTP layer with canned per-path payloads."""

    def __init__(self, payloads: dict[str, dict]) -> None:  # no super().__init__
        self._payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def _results(self, path, params):
        self.calls.append((path, params))
        payload = self._payloads.get(path, {})
        results = payload.get("results")
        return results if isinstance(results, list) else []


def test_fetch_financials_parses_results():
    provider = _FakeHttpProvider(
        {
            "/vX/reference/financials": {
                "results": [_vx_row("2026-03-28", "Q1", 500, 300, 120, 90, 1000)]
            }
        }
    )
    rows = provider.fetch_financials("nvda", limit=8)
    assert len(rows) == 1
    assert rows[0]["revenue"] == Decimal("500")
    path, params = provider.calls[0]
    assert path == "/vX/reference/financials"
    assert params == {"ticker": "NVDA", "timeframe": "quarterly", "limit": 8}


def test_fetch_dividends_and_splits_typed():
    provider = _FakeHttpProvider(
        {
            "/v3/reference/dividends": {
                "results": [{"ex_dividend_date": "2026-05-11", "cash_amount": "0.26"}]
            },
            "/v3/reference/splits": {
                "results": [
                    {"execution_date": "2020-08-31", "split_from": 1, "split_to": 4}
                ]
            },
        }
    )
    divs = provider.fetch_dividends("aapl")
    assert divs[0]["ex_dividend_date"] == date(2026, 5, 11)
    assert divs[0]["cash_amount"] == Decimal("0.26")
    splits = provider.fetch_splits("aapl")
    assert splits[0]["execution_date"] == date(2020, 8, 31)
    assert splits[0]["split_from"] == Decimal("1")
    assert splits[0]["split_to"] == Decimal("4")


def test_results_helper_raises_on_http_error():
    # Real provider against a transport that 404s → raise_for_status fires.
    provider = MassiveFundamentalsProvider("dummy-key")
    provider._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(404, json={"error": "nope"})
        ),
        base_url="https://example",
    )
    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        provider.fetch_financials("AAPL")
    provider.close()
