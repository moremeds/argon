"""Per-release operational catalog for macro policy sources.

Deliberately separate from :mod:`uw_scan.storage.macro_context`, which owns
immutable release evidence.  This module owns mutable liveness: what happened
the last time we tried to ingest one specific release.

The source-level `macro_source_status` cannot answer that.  One malformed
release degrades the whole source there, which hides the other 24 and makes
"is the SEP feed healthy?" unanswerable at the granularity a backfill needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Final

from psycopg.rows import dict_row

RELEASE_TYPES: Final = frozenset({"statement", "sep"})
RELEASE_STATUSES: Final = frozenset({"discovered", "artifact_only", "ok", "failed"})
STATEMENT_EVENT_CLASSES: Final = frozenset(
    {"scheduled_meeting", "unscheduled_meeting", "notation_vote"}
)
ERROR_TYPE_MAX: Final = 200
ERROR_MESSAGE_MAX: Final = 1000


class _MacroReleaseStatusMixin:
    """Read/write the per-release ingest catalog."""

    def upsert_macro_release_status(
        self,
        *,
        source: str,
        release_key: str,
        release_type: str,
        status: str,
        event_date: date,
        discovery_url: str,
        parser_version: str,
        last_attempt_at: datetime,
        event_class: str | None = None,
        artifact_source_record_id: str | None = None,
        latest_artifact_id: int | None = None,
        success_artifact_id: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record this attempt's outcome for one release.

        ``success_artifact_id`` names the artifact a successful parse read, and
        is only consulted when ``status`` is ``ok``.  A later failure keeps the
        stored ``last_success_at``/``last_success_artifact_id``: an outage must
        not erase the evidence that the release once ingested cleanly.
        """
        _validate_release_status(
            release_type=release_type,
            status=status,
            event_class=event_class,
            latest_artifact_id=latest_artifact_id,
            success_artifact_id=success_artifact_id,
            error_type=error_type,
            last_attempt_at=last_attempt_at,
        )
        safe_type = error_type[:ERROR_TYPE_MAX] if error_type is not None else None
        safe_message = (
            error_message[:ERROR_MESSAGE_MAX] if error_message is not None else None
        )
        is_ok = status == "ok"
        # Decided here rather than as a SQL CASE: an untyped parameter in the
        # NULL branch gives Postgres no type to infer for the column.
        success_id = success_artifact_id if is_ok else None
        success_at = last_attempt_at if is_ok else None
        table = f"{self._schema}.macro_release_ingest_status"
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (
                  source, release_key, release_type, status, event_date,
                  event_class, discovery_url, artifact_source_record_id,
                  latest_artifact_id, last_success_artifact_id, parser_version,
                  last_attempt_at, last_success_at, error_type, error_message
                )
                VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, %s,
                  %s, %s,
                  %s, %s
                )
                ON CONFLICT (source, release_key) DO UPDATE SET
                  release_type = EXCLUDED.release_type,
                  status = EXCLUDED.status,
                  event_date = EXCLUDED.event_date,
                  event_class = EXCLUDED.event_class,
                  discovery_url = EXCLUDED.discovery_url,
                  artifact_source_record_id = COALESCE(
                    EXCLUDED.artifact_source_record_id,
                    {table}.artifact_source_record_id
                  ),
                  latest_artifact_id = COALESCE(
                    EXCLUDED.latest_artifact_id, {table}.latest_artifact_id
                  ),
                  -- A failure never clears a past success.
                  last_success_artifact_id = COALESCE(
                    EXCLUDED.last_success_artifact_id,
                    {table}.last_success_artifact_id
                  ),
                  parser_version = EXCLUDED.parser_version,
                  last_attempt_at = EXCLUDED.last_attempt_at,
                  last_success_at = COALESCE(
                    EXCLUDED.last_success_at, {table}.last_success_at
                  ),
                  error_type = EXCLUDED.error_type,
                  error_message = EXCLUDED.error_message
                """,
                (
                    source,
                    release_key,
                    release_type,
                    status,
                    event_date,
                    event_class,
                    discovery_url,
                    artifact_source_record_id,
                    latest_artifact_id,
                    success_id,
                    parser_version,
                    last_attempt_at,
                    success_at,
                    safe_type,
                    safe_message,
                ),
            )

    def fetch_macro_release_status(
        self, *, source: str, release_key: str
    ) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {self._schema}.macro_release_ingest_status
                WHERE source = %s AND release_key = %s
                """,
                (source, release_key),
            )
            return cur.fetchone()

    def fetch_macro_release_statuses(
        self,
        *,
        sources: Sequence[str],
        release_type: str | None = None,
        statuses: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not sources:
            return []
        if release_type is not None and release_type not in RELEASE_TYPES:
            raise ValueError(f"unknown macro release_type {release_type!r}")
        clauses = ["source = ANY(%s)"]
        params: list[Any] = [list(sources)]
        if release_type is not None:
            clauses.append("release_type = %s")
            params.append(release_type)
        if statuses:
            unknown = set(statuses) - RELEASE_STATUSES
            if unknown:
                raise ValueError(f"unknown macro release status {sorted(unknown)}")
            clauses.append("status = ANY(%s)")
            params.append(list(statuses))
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {self._schema}.macro_release_ingest_status
                WHERE {" AND ".join(clauses)}
                ORDER BY source, event_date DESC, release_key
                """,
                params,
            )
            return list(cur.fetchall())


def _validate_release_status(
    *,
    release_type: str,
    status: str,
    event_class: str | None,
    latest_artifact_id: int | None,
    success_artifact_id: int | None,
    error_type: str | None,
    last_attempt_at: datetime,
) -> None:
    """Mirror the SQL constraints in Python so a bad call fails at the caller.

    The database checks are the authority -- these exist so a mistake surfaces
    with the offending argument named, rather than as a CheckViolation on a
    statement whose parameters have already been flattened.
    """
    if last_attempt_at.tzinfo is None or last_attempt_at.utcoffset() is None:
        raise ValueError("last_attempt_at must be timezone-aware")
    if release_type not in RELEASE_TYPES:
        raise ValueError(f"unknown macro release_type {release_type!r}")
    if status not in RELEASE_STATUSES:
        raise ValueError(f"unknown macro release status {status!r}")
    if release_type == "statement":
        if event_class not in STATEMENT_EVENT_CLASSES:
            raise ValueError(
                f"statement release requires a known event_class, got {event_class!r}"
            )
    elif event_class is not None:
        raise ValueError("SEP releases have no event_class")
    if status == "ok":
        if success_artifact_id is None:
            raise ValueError("an ok release status requires success_artifact_id")
        if error_type is not None:
            raise ValueError("an ok release status cannot carry an error")
    if status == "failed" and not error_type:
        raise ValueError("a failed release status requires error_type")
    if status == "artifact_only" and latest_artifact_id is None:
        raise ValueError("an artifact_only release status requires latest_artifact_id")
