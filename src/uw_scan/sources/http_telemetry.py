"""Shared GET-with-telemetry for the simple external provider clients.

``CftcCotProvider``, ``CftcTffProvider``, ``ComexProvider``, ``GprProvider``
and ``LbmaProvider`` each keep a thin ``_get_with_telemetry`` method — the
seam tests and callers patch — that delegates here. The GET, the one-event
per-request recording rule, and event construction live in one place.

Recording rules preserved from the per-client copies: exactly one event per
request — a transport ``httpx.HTTPError`` is recorded with
``status_code=None``/``error_message=repr(exc)[:1000]`` and re-raised (any
other exception propagates unrecorded); an HTTP response is recorded with its
status and a body excerpt on >=400, then returned for the caller's
``raise_for_status``. A raising ``record_request`` callback propagates.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

RecordEvent = Callable[[ExternalApiRequestEvent], None]


def get_with_telemetry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    *,
    provider: str,
    endpoint_key: str,
    endpoint_path: str,
    record_request: RecordEvent,
    job_name: str | None = None,
) -> httpx.Response:
    started_at = datetime.now(UTC)
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        finished_at = datetime.now(UTC)
        record_request(
            build_get_event(
                provider=provider,
                endpoint_key=endpoint_key,
                endpoint_path=endpoint_path,
                params=params,
                started_at=started_at,
                finished_at=finished_at,
                status_code=None,
                error_message=repr(exc)[:1000],
                job_name=job_name,
            )
        )
        raise
    finished_at = datetime.now(UTC)
    record_request(
        build_get_event(
            provider=provider,
            endpoint_key=endpoint_key,
            endpoint_path=endpoint_path,
            params=params,
            started_at=started_at,
            finished_at=finished_at,
            status_code=response.status_code,
            error_message=(
                response.text[:1000] if response.status_code >= 400 else None
            ),
            job_name=job_name,
        )
    )
    return response


def build_get_event(
    *,
    provider: str,
    endpoint_key: str,
    endpoint_path: str,
    params: dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
    status_code: int | None,
    error_message: str | None,
    job_name: str | None = None,
) -> ExternalApiRequestEvent:
    return ExternalApiRequestEvent(
        provider=provider,
        endpoint_key=endpoint_key,
        method="GET",
        path=endpoint_path,
        path_template=endpoint_path,
        params=redact_params(params),
        status_code=status_code,
        status_family=status_family_for(
            status_code, transport_error=status_code is None
        ),
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
        error_message=error_message,
        job_name=job_name,
    )
