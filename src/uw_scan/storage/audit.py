"""Audit + raw payload writes.

API/worker fetchers call insert_audit_row immediately before any UW HTTP
request (so even failures leave a row), then insert_raw_payload with the
response body. The two-step shape lets us trace any UW call back to its
HTTP request even when normalization fails."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class _AuditMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_audit_row(
        self,
        run_id: int,
        endpoint_slug: str,
        endpoint_path: str,
        params: dict[str, Any],
        status_code: int,
        started_at: datetime,
        finished_at: datetime,
        daily_req_count: int | None,
        minute_req_remaining: int | None,
        minute_req_reset: str | None,
        error_message: str | None = None,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.api_request_audit ("
            "run_id, endpoint_slug, endpoint_path, params_json, status_code, "
            "request_started_at, request_finished_at, daily_req_count, "
            "minute_req_remaining, minute_req_reset, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING audit_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    endpoint_slug,
                    endpoint_path,
                    Jsonb(params),
                    status_code,
                    started_at,
                    finished_at,
                    daily_req_count,
                    minute_req_remaining,
                    minute_req_reset,
                    error_message,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def insert_raw_payload(self, audit_id: int, payload: dict | list) -> int:
        sql = (
            f"INSERT INTO {self._schema}.raw_payloads (audit_id, payload_jsonb) "
            "VALUES (%s, %s) RETURNING payload_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (audit_id, Jsonb(payload)))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])
