from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.models.provider_usage import (
    ProviderParam,
    ProviderUsageBreakdownResponse,
    ProviderUsageBreakdownRow,
    ProviderUsageRequestsResponse,
    ProviderUsageRequestRow,
    ProviderUsageSummaryResponse,
    StatusFamilyParam,
)
from uw_scan.storage._helpers import provider_day_bounds
from uw_scan.storage.repository import Repository

router = APIRouter()


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
    "/provider-usage/jobs",
    response_model=ProviderUsageBreakdownResponse,
)
def provider_usage_jobs(
    provider: ProviderParam = "all",
    repo: Repository = Depends(get_repo),
) -> ProviderUsageBreakdownResponse:
    start, end = provider_day_bounds()
    rows = repo.list_external_api_job_usage(_provider_filter(provider), start, end)
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
