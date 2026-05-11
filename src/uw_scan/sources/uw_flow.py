from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.models import FlowRow
from uw_scan.normalize.options import parse_decimal, parse_int


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "rows", "flow_alerts"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _option_symbol(row: dict[str, Any], ticker: str, expiry: str, strike: Decimal, option_type: str) -> str:
    explicit = _first(row, "option_symbol", "contract", "contract_symbol", "symbol")
    if explicit:
        return str(explicit).upper()
    compact_expiry = expiry.replace("-", "")[2:]
    type_code = "C" if option_type.lower().startswith("c") else "P"
    return f"{ticker}{compact_expiry}{type_code}{int(strike * 1000):08d}"


def flow_rows_from_payload(payload: Any, *, source_label: str, limit: int | None = None) -> list[FlowRow]:
    rows: list[FlowRow] = []
    for record in _records(payload):
        ticker = str(_first(record, "ticker", "underlying_symbol", "underlying", "root") or "").upper()
        expiry_raw = _first(record, "expiry", "expiration", "expiry_date", "expiration_date")
        strike = parse_decimal(_first(record, "strike", "strike_price"))
        if not ticker or not expiry_raw or strike is None:
            continue
        expiry = date.fromisoformat(str(expiry_raw)[:10])
        option_type = str(_first(record, "option_type", "type", "put_call", "call_put") or "call").lower()
        premium = parse_decimal(_first(record, "premium", "total_premium", "cost_basis", "notional")) or Decimal("0")
        volume = parse_int(_first(record, "volume", "total_volume", "size", "volume_oi_ratio")) or 0
        open_interest = parse_int(_first(record, "open_interest", "oi", "open_int"))
        dte = parse_int(_first(record, "dte", "days_to_expiry")) or max((expiry - date.today()).days, 0)
        rows.append(
            FlowRow(
                ticker=ticker,
                option_symbol=_option_symbol(record, ticker, str(expiry), strike, option_type),
                expiry=expiry,
                strike=strike,
                option_type="put" if option_type.startswith("p") else "call",
                premium=premium,
                volume=volume,
                open_interest=open_interest,
                side=str(_first(record, "side", "ask_bid", "sentiment") or "unknown").lower(),
                dte=dte,
                source_label=source_label,
            )
        )
        if limit is not None and len(rows) >= limit:
            break
    return rows
