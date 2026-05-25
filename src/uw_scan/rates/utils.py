"""Shared internal helpers for rates snapshot assembly."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


def latest_float(
    observations: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
    *,
    divisor: Decimal | int = 1,
    quantum: str = "0.01",
) -> float | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    decimal_value = decimal_value / Decimal(str(divisor))
    return float(decimal_value.quantize(Decimal(quantum)))
