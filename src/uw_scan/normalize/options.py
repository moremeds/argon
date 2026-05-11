from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from uw_scan.models import OiByExpiryRow, OptionContractSnapshot


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(Decimal(str(value)))


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_option_contract_snapshot(
    *, run_id: str, market_date: str, fetched_at_utc: str, payload: dict[str, Any]
) -> OptionContractSnapshot:
    bid = parse_decimal(payload.get("bid"))
    ask = parse_decimal(payload.get("ask"))
    mid = (bid + ask) / Decimal("2") if bid is not None and ask is not None else None
    return OptionContractSnapshot(
        run_id=run_id,
        option_symbol=str(payload["option_symbol"]),
        ticker=str(payload["ticker"]).upper(),
        market_date=parse_date(market_date),
        fetched_at_utc=parse_datetime(fetched_at_utc),
        expiry=parse_date(str(payload["expiry"])),
        strike=parse_decimal(payload["strike"]) or Decimal("0"),
        option_type=str(payload["option_type"]).lower(),
        implied_volatility=parse_decimal(payload.get("implied_volatility")),
        open_interest=parse_int(payload.get("open_interest")),
        previous_open_interest=parse_int(payload.get("prev_oi") or payload.get("previous_open_interest")),
        volume=parse_int(payload.get("volume")),
        premium=parse_decimal(payload.get("premium")),
        bid=bid,
        ask=ask,
        mid=mid,
    )


def normalize_oi_by_expiry(
    *, run_id: str, ticker: str, market_date: str, fetched_at_utc: str, payload: dict[str, Any]
) -> OiByExpiryRow:
    return OiByExpiryRow(
        run_id=run_id,
        ticker=ticker.upper(),
        market_date=parse_date(market_date),
        fetched_at_utc=parse_datetime(fetched_at_utc),
        expiry=parse_date(str(payload["expiry"])),
        call_open_interest=parse_int(payload.get("call_oi") or payload.get("call_open_interest")),
        put_open_interest=parse_int(payload.get("put_oi") or payload.get("put_open_interest")),
    )
