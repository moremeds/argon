"""Durable external provider request telemetry recording."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalApiRequestEvent:
    provider: str
    endpoint_key: str
    method: str
    path: str
    status_family: str
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    path_template: str | None = None
    ticker: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    status_code: int | None = None
    attempt: int = 0
    run_id: int | None = None
    job_name: str | None = None
    provider_request_id: str | None = None
    official_daily_count: int | None = None
    official_daily_limit: int | None = None
    official_minute_remaining: int | None = None
    official_minute_reset: str | None = None
    error_message: str | None = None


class ExternalApiRequestRecorder:
    """Write request telemetry outside scan transactions.

    The recorder owns an autocommit connection so provider telemetry survives
    rollbacks in the main scan/pipeline connection.
    """

    def __init__(self, dsn: str, *, schema: str = "uw_scan") -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._repo = Repository(self._conn, schema=schema)

    def record(self, event: ExternalApiRequestEvent) -> None:
        try:
            self._repo.insert_external_api_request(
                provider=event.provider,
                endpoint_key=event.endpoint_key,
                method=event.method,
                path_template=event.path_template,
                path=event.path,
                ticker=event.ticker,
                params=event.params,
                status_code=event.status_code,
                status_family=event.status_family,
                started_at=event.started_at,
                finished_at=event.finished_at,
                latency_ms=event.latency_ms,
                attempt=event.attempt,
                run_id=event.run_id,
                job_name=event.job_name,
                provider_request_id=event.provider_request_id,
                official_daily_count=event.official_daily_count,
                official_daily_limit=event.official_daily_limit,
                official_minute_remaining=event.official_minute_remaining,
                official_minute_reset=event.official_minute_reset,
                error_message=event.error_message,
            )
        except Exception as exc:
            logger.exception(
                "failed to record external API request telemetry: %s",
                repr(exc),
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ExternalApiRequestRecorder":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
