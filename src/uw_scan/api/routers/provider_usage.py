from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from uw_scan.api.deps import get_repo
from uw_scan.storage.repository import Repository, provider_day_bounds

router = APIRouter()

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


def _provider_filter(provider: ProviderParam) -> str | None:
    return None if provider == "all" else provider


@router.get(
    "/provider-usage/summary",
    response_model=ProviderUsageSummaryResponse,
)
def provider_usage_summary(
    provider: ProviderParam = "all",
    repo: Repository = Depends(get_repo),
) -> ProviderUsageSummaryResponse:
    start, end = provider_day_bounds()
    summary = repo.get_external_api_usage_summary(_provider_filter(provider), start, end)
    return ProviderUsageSummaryResponse(
        provider_day_start=start,
        provider_day_end=end,
        total_requests=summary.total_requests,
        http_2xx=summary.http_2xx,
        http_3xx=summary.http_3xx,
        http_4xx=summary.http_4xx,
        http_5xx=summary.http_5xx,
        transport_errors=summary.transport_errors,
        latency_p95_ms=summary.latency_p95_ms,
        uw_latest_daily_count=summary.uw_latest_daily_count,
        uw_latest_daily_limit=summary.uw_latest_daily_limit,
    )


@router.get(
    "/provider-usage/endpoints",
    response_model=ProviderUsageBreakdownResponse,
)
def provider_usage_endpoints(
    provider: ProviderParam = "all",
    repo: Repository = Depends(get_repo),
) -> ProviderUsageBreakdownResponse:
    start, end = provider_day_bounds()
    rows = repo.list_external_api_endpoint_usage(_provider_filter(provider), start, end)
    return ProviderUsageBreakdownResponse(
        provider_day_start=start,
        provider_day_end=end,
        rows=[ProviderUsageBreakdownRow(**row.__dict__) for row in rows],
    )


@router.get(
    "/provider-usage/tickers",
    response_model=ProviderUsageBreakdownResponse,
)
def provider_usage_tickers(
    provider: ProviderParam = "all",
    repo: Repository = Depends(get_repo),
) -> ProviderUsageBreakdownResponse:
    start, end = provider_day_bounds()
    rows = repo.list_external_api_ticker_usage(_provider_filter(provider), start, end)
    return ProviderUsageBreakdownResponse(
        provider_day_start=start,
        provider_day_end=end,
        rows=[ProviderUsageBreakdownRow(**row.__dict__) for row in rows],
    )


@router.get(
    "/provider-usage/requests",
    response_model=ProviderUsageRequestsResponse,
)
def provider_usage_requests(
    provider: ProviderParam = "all",
    ticker: str | None = None,
    status_family: StatusFamilyParam | None = None,
    limit: Annotated[int, Query(ge=1)] = 100,
    repo: Repository = Depends(get_repo),
) -> ProviderUsageRequestsResponse:
    start, end = provider_day_bounds()
    rows = repo.list_external_api_requests(
        provider=_provider_filter(provider),
        start=start,
        end=end,
        ticker=ticker,
        status_family=status_family,
        limit=limit,
    )
    return ProviderUsageRequestsResponse(
        provider_day_start=start,
        provider_day_end=end,
        limit=max(1, min(limit, 500)),
        rows=[ProviderUsageRequestRow(**row.__dict__) for row in rows],
    )
