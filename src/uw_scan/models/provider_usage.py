"""Provider-usage response models for the /api/provider-usage endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ProviderParam = Literal["uw", "massive", "all"]
StatusFamilyParam = Literal["2xx", "3xx", "4xx", "5xx", "transport_error"]


class ProviderUsageSummaryResponse(BaseModel):
    provider_day_start: datetime
    provider_day_end: datetime
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None
    uw_latest_daily_count: int | None
    uw_latest_daily_limit: int | None


class ProviderUsageBreakdownRow(BaseModel):
    key: str | None
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None


class ProviderUsageBreakdownResponse(BaseModel):
    provider_day_start: datetime
    provider_day_end: datetime
    rows: list[ProviderUsageBreakdownRow]


class ProviderUsageRequestRow(BaseModel):
    request_id: int
    provider: str
    endpoint_key: str
    method: str
    path: str
    ticker: str | None
    params: dict[str, object]
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


class ProviderUsageRequestsResponse(BaseModel):
    provider_day_start: datetime
    provider_day_end: datetime
    limit: int
    rows: list[ProviderUsageRequestRow]
