"""Frozen dataclasses + WatchlistCardRow used by the Repository methods.

Moved from repository.py during the PR-1 split (see
docs/superpowers/plans/2026-05-16-repository-split-pr1.md). All row types
are re-exported from repository.py for backward compat with existing callers
(`from uw_scan.storage.repository import JobRow` still works).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class WatchlistRow:
    ticker: str
    sector: str
    notes: str | None
    pinned: bool
    sort_rank: int
    added_at: datetime
    removed_at: datetime | None


@dataclass(frozen=True)
class DailyOhlcRow:
    ticker: str
    date: _date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class IntradayQuoteRow:
    ticker: str
    price: Decimal
    quoted_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class PcrHistoryRow:
    ticker: str
    snapshot_date: _date
    pcr_oi: Decimal | None
    pcr_vol: Decimal | None


@dataclass(frozen=True)
class JobRow:
    id: Any
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    claim_token: Any = None  # UUID, set on claim, gates mark_job_done/failed


@dataclass(frozen=True)
class RescanQueueSummaryRow:
    total: int
    queued: int
    running: int
    oldest_requested_at: datetime | None


@dataclass(frozen=True)
class ExternalApiUsageSummary:
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None
    uw_latest_daily_count: int | None
    uw_latest_daily_limit: int | None


@dataclass(frozen=True)
class ExternalApiBreakdownRow:
    key: str | None
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None


@dataclass(frozen=True)
class ThroughputSummaryRow:
    window_minutes: float
    requests_per_minute: float
    http_429: int
    avg_scan_duration_seconds: float | None
    queue_drain_rate_per_minute: float | None


@dataclass(frozen=True)
class ExternalApiRequestRow:
    request_id: int
    provider: str
    endpoint_key: str
    method: str
    path: str
    ticker: str | None
    params: dict[str, Any]
    status_code: int | None
    status_family: str
    request_started_at: datetime
    request_finished_at: datetime
    latency_ms: int
    attempt: int
    run_id: int | None
    job_name: str | None
    provider_request_id: str | None
    official_daily_count: int | None
    official_daily_limit: int | None
    official_minute_remaining: int | None
    official_minute_reset: str | None
    error_message: str | None


@dataclass(frozen=True)
class RecordHealthRow:
    table: str
    window_start: datetime
    expected_tickers: int
    expected_min_tickers: int
    actual_tickers: int
    expected_min_rows: int
    actual_rows: int
    latest_at: datetime | None
    ok: bool


class WatchlistCardRow:
    """Variable-shaped: 37 fields in the list shape, fewer in single-row shape.

    Two constructors:
      - from_list_row(row, desc) — strict, validates against _LIST_FIELDS.
        Use this in list_watchlist_cards so SELECT-alias typos fail loudly.
      - from_db(row, desc) — lenient, accepts any column set.
        Use this in get_watchlist_card which does SELECT * FROM watchlist_card
        and returns a different column shape (no watchlist fields, has updated_at).
    """

    # Canonical column list returned by list_watchlist_cards. Keep in sync
    # with the SELECT projection in that method — drift is caught at the
    # first /api/watchlist request thanks to from_list_row's validation.
    _LIST_FIELDS: frozenset[str] = frozenset(
        {
            # watchlist
            "ticker",
            "sector",
            "pinned",
            "sort_rank",
            # card metadata
            "run_id",
            "scanned_at",
            "spot",
            "spot_quoted_at",
            "spot_source",
            "iv_atm",
            "iv_rank",
            "setup_type",
            "setup_direction",
            "setup_score",
            "aggression_pct",
            "ret_1d",
            "ret_1w",
            "ret_30d",
            "market_cap",
            "aum",
            "gex_flip_distance",
            "gex_flip_price",
            "gex_per_1pct_move",
            "max_gex_strike",
            "gex_expiring_pct",
            "gex_expiring_date",
            "skew_25d_30dte",
            "call_oi_total",
            "put_oi_total",
            "pcr_oi",
            "pcr_vol",
            "pcr_delta_30d",
            # active job columns (LEFT JOIN — all nullable)
            "active_job_id",
            "active_job_status",
            "active_job_queue_position",
            "active_job_requested_at",
            "active_job_started_at",
        }
    )

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str):
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError as e:
            raise AttributeError(name) from e
        if name in data:
            return data[name]
        raise AttributeError(name)

    @classmethod
    def from_db(cls, row: tuple, description) -> "WatchlistCardRow":
        """Lenient: accept whatever columns the cursor returned. Used by
        get_watchlist_card (SELECT *)."""
        return cls({col.name: val for col, val in zip(description, row, strict=False)})

    @classmethod
    def from_list_row(cls, row: tuple, description) -> "WatchlistCardRow":
        """Strict: validate against _LIST_FIELDS. Use only for the
        list_watchlist_cards projection so SELECT-alias typos fail loudly."""
        names = [col.name for col in description]
        if len(set(names)) != len(names):
            raise ValueError(
                f"WatchlistCardRow.from_list_row got duplicate column(s) in description: {names}"
            )
        seen = set(names)
        unknown = seen - cls._LIST_FIELDS
        if unknown:
            raise ValueError(
                f"WatchlistCardRow.from_list_row got unknown column(s): {sorted(unknown)}. "
                f"Add to _LIST_FIELDS if the SELECT was intentionally extended."
            )
        missing = cls._LIST_FIELDS - seen
        if missing:
            raise ValueError(
                f"WatchlistCardRow.from_list_row missing column(s): {sorted(missing)}. "
                f"Either restore them to the SELECT or remove from _LIST_FIELDS."
            )
        return cls({name: val for name, val in zip(names, row, strict=False)})

    def to_dict(self) -> dict:
        return dict(self._data)
