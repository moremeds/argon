"""Pure-utility helpers used by Repository methods.

Three of these are externally importable from `uw_scan.storage.repository`
(provider_day_bounds, status_family_for, redact_params) and stay re-exported
there for backward compat with callers in sources/, api/, and tests/.
Internal-only helpers (_d, _nullable_int, _nullable_float) live here too for
cohesion.

Moved from repository.py during the PR-1 split. Cockpit-specific helpers
(_pin_candidate, _vanna_conditional_reading, _charm_regime, etc.) stay in
repository.py for PR-1 and will move with their domain modules in PR-2.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

_PROVIDER_DAY_TZ = ZoneInfo("America/New_York")

_REDACTED_PARAM_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "token",
}


def _d(value: Decimal | None) -> Any:
    """psycopg handles Decimal natively; keep this for symmetry with other casters."""
    return value


def provider_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(tz=_PROVIDER_DAY_TZ)
    local = current.astimezone(_PROVIDER_DAY_TZ)
    reset = local.replace(hour=20, minute=0, second=0, microsecond=0)
    if local < reset:
        reset -= timedelta(days=1)
    return reset, reset + timedelta(days=1)


def status_family_for(status_code: int | None, *, transport_error: bool = False) -> str:
    if transport_error:
        return "transport_error"
    if status_code is None:
        return "transport_error"
    if 200 <= status_code <= 299:
        return "2xx"
    if 300 <= status_code <= 399:
        return "3xx"
    if 400 <= status_code <= 499:
        return "4xx"
    if 500 <= status_code <= 599:
        return "5xx"
    return "transport_error"


def redact_params(params: dict[str, object] | None) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in (params or {}).items():
        if key.lower() in _REDACTED_PARAM_KEYS:
            continue
        if isinstance(value, str) and len(value) > 256:
            redacted[key] = value[:253] + "..."
        else:
            redacted[key] = value
    return redacted


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
