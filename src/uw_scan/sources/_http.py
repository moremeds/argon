"""Request telemetry shared by the hand-rolled source clients (I-56).

Twelve clients (CFTC, Cleveland Fed, ETF holdings, FedWatch path, FRED, GPR, LBMA,
massive OHLC, Treasury, WGC) each carried a copy of the same three helpers: time a
GET, build an ``ExternalApiRequestEvent``, record it or debug-log it. This module is
the one copy of the parts that were IDENTICAL. Everything that differed stays with
the client and is passed in: the provider / endpoint key / path it reports, how it
words an error, and its retry loop.

Frozen by ``tests/unit/sources/test_source_telemetry_golden.py``: every client must
emit exactly the events it emitted before this module existed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from uw_scan.storage._helpers import redact_params, status_family_for
from uw_scan.storage.provider_usage import ExternalApiRequestEvent

logger = logging.getLogger(__name__)

#: Sent by the scrapers whose hosts refuse non-browser clients (SPDR, LBMA, WGC).
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RecordHook = Callable[[Any, ExternalApiRequestEvent], None]


@dataclass(frozen=True)
class RequestOutcome:
    """What one GET produced. ``response`` is None after a transport error."""

    status_code: int | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime
    response: httpx.Response | None


def repr_error(exc: httpx.HTTPError) -> str:
    return repr(exc)[:1000]


def error_body(response: httpx.Response) -> str | None:
    return response.text[:1000] if response.status_code >= 400 else None


def get_with_telemetry(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None,
    record: Callable[[RequestOutcome], None],
    transport_error_text: Callable[[httpx.HTTPError], str | None] = repr_error,
    error_body_text: Callable[[httpx.Response], str | None] = error_body,
) -> httpx.Response:
    """One GET, timed and recorded. Transport errors are recorded, then re-raised;
    an HTTP error status is recorded and returned (each caller decides what a 4xx
    means). No retries here: a client that retries loops around this call."""
    started_at = datetime.now(UTC)
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        record(
            RequestOutcome(
                status_code=None,
                error_message=transport_error_text(exc),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                response=None,
            )
        )
        raise
    record(
        RequestOutcome(
            status_code=response.status_code,
            error_message=error_body_text(response),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            response=response,
        )
    )
    return response


def request_event(
    outcome: RequestOutcome,
    *,
    provider: str,
    endpoint_key: str,
    path: str,
    params: dict[str, Any] | None,
    path_template: str | None = None,
    job_name: str | None = None,
    ticker: str | None = None,
    provider_request_id: str | None = None,
) -> ExternalApiRequestEvent:
    return ExternalApiRequestEvent(
        provider=provider,
        endpoint_key=endpoint_key,
        method="GET",
        path=path,
        path_template=path_template if path_template is not None else path,
        params=redact_params(params),
        status_code=outcome.status_code,
        status_family=status_family_for(outcome.status_code),
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        latency_ms=max(
            0, int((outcome.finished_at - outcome.started_at).total_seconds() * 1000)
        ),
        error_message=outcome.error_message,
        job_name=job_name,
        ticker=ticker,
        provider_request_id=provider_request_id,
    )


def record_or_log(
    hook: RecordHook | None, owner: Any, event: ExternalApiRequestEvent, label: str
) -> None:
    """Hand the event to the client's hook, or debug-log it when none is wired."""
    if hook is not None:
        hook(owner, event)
    else:
        logger.debug("%s telemetry %r", label, event)
