"""Massive.com fundamentals client (M5 trade-framework).

Polygon-shaped REST client, sibling to ``sources/ohlc.py::MassiveOhlcProvider``.
Three endpoints, all confirmed on our tier in
``docs/research/goyal-saretto-ipca-options/14-massive-endpoint-probe-log.md``:

- GET /vX/reference/financials?ticker={t}&timeframe=quarterly&limit=N
    → Polygon ``results`` list; real financial fields nested under
    ``row.financials.{income_statement,balance_sheet,cash_flow_statement}.<field>.value``.
- GET /v3/reference/dividends?ticker={t}&limit=N  → ``results`` of dividend events.
- GET /v3/reference/splits?ticker={t}&limit=N     → ``results`` of split events.

Parsers return plain dicts (not Pydantic models) — they feed a wide snapshot
upsert, not the API contract. Raises on non-2xx (no silent skipping).
For the nightly framework refresh we read only the most recent few quarters,
so pagination (``next_url``) is intentionally NOT followed here — full-history
backfill is a separate research concern.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        logger.debug("non-numeric value %r: %s", value, repr(exc))
        return None


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        logger.debug("unparseable date %r: %s", value, repr(exc))
        return None


def _leaf(financials: dict, group: str, field: str) -> Decimal | None:
    """Read ``financials[group][field].value`` defensively."""
    grp = financials.get(group) or {}
    leaf = grp.get(field) or {}
    if isinstance(leaf, dict):
        return _dec(leaf.get("value"))
    return None


class FundamentalsProvider(Protocol):
    def fetch_financials(
        self, ticker: str, *, timeframe: str = "quarterly", limit: int = 8
    ) -> list[dict]: ...

    def fetch_dividends(self, ticker: str, *, limit: int = 4) -> list[dict]: ...

    def fetch_splits(self, ticker: str, *, limit: int = 4) -> list[dict]: ...


class MassiveFundamentalsProvider:
    """REST client for api.massive.com fundamentals (Polygon-shaped)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MassiveFundamentalsProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _results(self, path: str, params: dict[str, Any]) -> list[dict]:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        payload = resp.json()
        results = payload.get("results")
        return results if isinstance(results, list) else []

    def fetch_financials(
        self, ticker: str, *, timeframe: str = "quarterly", limit: int = 8
    ) -> list[dict]:
        rows = self._results(
            "/vX/reference/financials",
            {"ticker": ticker.upper(), "timeframe": timeframe, "limit": limit},
        )
        return [parsed for r in rows if (parsed := _parse_financials_row(r))]

    def fetch_dividends(self, ticker: str, *, limit: int = 4) -> list[dict]:
        rows = self._results(
            "/v3/reference/dividends", {"ticker": ticker.upper(), "limit": limit}
        )
        return [
            {
                "ex_dividend_date": _date_or_none(r.get("ex_dividend_date")),
                "cash_amount": _dec(r.get("cash_amount")),
            }
            for r in rows
        ]

    def fetch_splits(self, ticker: str, *, limit: int = 4) -> list[dict]:
        rows = self._results(
            "/v3/reference/splits", {"ticker": ticker.upper(), "limit": limit}
        )
        return [
            {
                "execution_date": _date_or_none(r.get("execution_date")),
                "split_from": _dec(r.get("split_from")),
                "split_to": _dec(r.get("split_to")),
            }
            for r in rows
        ]


def _parse_financials_row(row: dict) -> dict | None:
    """One /vX financials result → flat dict of typed leaves (None if unkeyable)."""
    period_end = _date_or_none(row.get("end_date"))
    if period_end is None:
        return None  # cannot key the snapshot without a period end
    fin = row.get("financials") or {}
    return {
        "period_end": period_end,
        "fiscal_period": row.get("fiscal_period"),
        "filing_date": _date_or_none(row.get("filing_date")),
        "revenue": _leaf(fin, "income_statement", "revenues"),
        "gross_profit": _leaf(fin, "income_statement", "gross_profit"),
        "operating_income": _leaf(fin, "income_statement", "operating_income_loss"),
        "net_income": _leaf(fin, "income_statement", "net_income_loss"),
        "total_assets": _leaf(fin, "balance_sheet", "assets"),
        "total_debt": _leaf(fin, "balance_sheet", "long_term_debt"),
        "shareholders_equity": _leaf(fin, "balance_sheet", "equity"),
        "diluted_shares": _leaf(fin, "income_statement", "diluted_average_shares"),
        "operating_cash_flow": _leaf(
            fin, "cash_flow_statement", "net_cash_flow_from_operating_activities"
        ),
        "investing_cash_flow": _leaf(
            fin, "cash_flow_statement", "net_cash_flow_from_investing_activities"
        ),
        "raw": row,
    }
