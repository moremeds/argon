"""Immutable point-in-time macro artifact and observation persistence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)


#: The availability bound an artifact imposes on its own observations at READ time.
#:
#: A release gates the facts it carries: the FOMC statement became knowable when it went
#: up, so nothing parsed out of it was knowable earlier.  A vintage-bearing artifact
#: inverts that, exactly as migration 124 says on the write side -- an ALFRED payload
#: fetched today REPORTS that January 2024 CPI was first published on 2024-02-13; it is
#: not that publication.  Gating those rows on when we happened to fetch them re-imposes
#: the rule 124 removed, and does it silently: every historical replay returns zero rows
#: and the state abstains, which reads as missing data rather than as a broken query.
#:
#: The point-in-time gate does not weaken -- ``o.available_at <= as_of`` still applies to
#: every row, and that column IS the vintage.  What is dropped is a second bound that
#: only ever measured our fetch schedule.  Quality still gates unconditionally: a
#: quarantined artifact takes its observations out of service however it was obtained.
_ARTIFACT_AVAILABLE = "(a.vintage_bearing OR a.available_at <= %s)"


class _MacroContextMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_macro_artifact(
        self,
        *,
        source: str,
        source_kind: str,
        source_record_id: str,
        source_url: str | None,
        published_at: datetime | None,
        available_at: datetime,
        retrieved_at: datetime,
        content_hash: str,
        parser_version: str,
        quality_status: str,
        cost_class: str,
        media_type: str,
        content_length: int,
        vintage_bearing: bool = False,
        raw_json: dict[str, Any] | list[Any] | None = None,
        raw_text: str | None = None,
        raw_bytes: bytes | None = None,
    ) -> int:
        _require_aware("published_at", published_at, optional=True)
        _require_aware("available_at", available_at)
        _require_aware("retrieved_at", retrieved_at)
        _require_sha256(content_hash)
        actual_hash, actual_length = macro_artifact_content_identity(
            raw_json=raw_json,
            raw_text=raw_text,
            raw_bytes=raw_bytes,
        )
        if content_hash != actual_hash:
            raise ValueError("artifact content_hash does not match raw payload")
        if content_length != actual_length:
            raise ValueError("artifact content_length does not match raw payload")
        with self._conn.cursor() as cur:
            available_at = _revision_available_at(
                cur,
                self._schema,
                source=source,
                source_record_id=source_record_id,
                content_hash=content_hash,
                available_at=available_at,
                retrieved_at=retrieved_at,
            )
            cur.execute(
                f"""
                INSERT INTO {self._schema}.macro_source_artifacts (
                  source, source_kind, source_record_id, source_url,
                  published_at, available_at, retrieved_at, last_seen_at,
                  content_hash, parser_version, quality_status, cost_class,
                  media_type, content_length, vintage_bearing,
                  raw_jsonb, raw_text, raw_bytes
                )
                VALUES (
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (source, source_record_id, content_hash)
                DO UPDATE SET
                  retrieved_at = LEAST(
                    {self._schema}.macro_source_artifacts.retrieved_at,
                    EXCLUDED.retrieved_at
                  ),
                  last_seen_at = GREATEST(
                    {self._schema}.macro_source_artifacts.last_seen_at,
                    EXCLUDED.last_seen_at
                  ),
                  -- A NULL instant is a known-unknown, not a publisher fact, so a
                  -- later parser that can read it may resolve it exactly once.
                  -- COALESCE keeps a resolved instant immutable thereafter.
                  published_at = COALESCE(
                    {self._schema}.macro_source_artifacts.published_at,
                    EXCLUDED.published_at
                  ),
                  available_at = CASE
                    WHEN {self._schema}.macro_source_artifacts.published_at IS NULL
                      AND EXCLUDED.published_at IS NOT NULL
                    THEN EXCLUDED.published_at
                    ELSE {self._schema}.macro_source_artifacts.available_at
                  END
                WHERE
                  {self._schema}.macro_source_artifacts.source_kind
                    IS NOT DISTINCT FROM EXCLUDED.source_kind
                  AND {self._schema}.macro_source_artifacts.source_url
                    IS NOT DISTINCT FROM EXCLUDED.source_url
                  AND (
                    {self._schema}.macro_source_artifacts.published_at
                      IS NOT DISTINCT FROM EXCLUDED.published_at
                    OR {self._schema}.macro_source_artifacts.published_at IS NULL
                  )
                  AND (
                    {self._schema}.macro_source_artifacts.available_at
                      IS NOT DISTINCT FROM EXCLUDED.available_at
                    OR (
                      {self._schema}.macro_source_artifacts.published_at IS NULL
                      AND EXCLUDED.published_at IS NULL
                      AND {self._schema}.macro_source_artifacts.available_at
                        <= EXCLUDED.available_at
                    )
                    OR (
                      {self._schema}.macro_source_artifacts.published_at IS NULL
                      AND EXCLUDED.published_at IS NOT NULL
                    )
                  )
                  AND {self._schema}.macro_source_artifacts.parser_version
                    IS NOT DISTINCT FROM EXCLUDED.parser_version
                  AND {self._schema}.macro_source_artifacts.quality_status
                    IS NOT DISTINCT FROM EXCLUDED.quality_status
                  AND {self._schema}.macro_source_artifacts.cost_class
                    IS NOT DISTINCT FROM EXCLUDED.cost_class
                  AND {self._schema}.macro_source_artifacts.media_type
                    IS NOT DISTINCT FROM EXCLUDED.media_type
                  AND {self._schema}.macro_source_artifacts.content_length
                    IS NOT DISTINCT FROM EXCLUDED.content_length
                  AND {self._schema}.macro_source_artifacts.vintage_bearing
                    IS NOT DISTINCT FROM EXCLUDED.vintage_bearing
                  AND {self._schema}.macro_source_artifacts.raw_jsonb
                    IS NOT DISTINCT FROM EXCLUDED.raw_jsonb
                  AND {self._schema}.macro_source_artifacts.raw_text
                    IS NOT DISTINCT FROM EXCLUDED.raw_text
                  AND {self._schema}.macro_source_artifacts.raw_bytes
                    IS NOT DISTINCT FROM EXCLUDED.raw_bytes
                RETURNING artifact_id
                """,
                (
                    source,
                    source_kind,
                    source_record_id,
                    source_url,
                    published_at,
                    available_at,
                    retrieved_at,
                    retrieved_at,
                    content_hash,
                    parser_version,
                    quality_status,
                    cost_class,
                    media_type,
                    content_length,
                    vintage_bearing,
                    Jsonb(raw_json) if raw_json is not None else None,
                    raw_text,
                    raw_bytes,
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError(
                "artifact identity collision: immutable metadata differs for "
                f"({source}, {source_record_id}, {content_hash})"
            )
        return int(row[0])

    def fetch_macro_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {self._schema}.macro_source_artifacts
                WHERE artifact_id = %s
                """,
                (artifact_id,),
            )
            return cur.fetchone()

    def insert_macro_observations(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        seen_at: datetime,
    ) -> int:
        _require_aware("seen_at", seen_at)
        materialized_rows = list(rows)
        for row in materialized_rows:
            _require_aware("published_at", row.get("published_at"), optional=True)
            _require_aware("available_at", row.get("available_at"))
            _require_sha256(row.get("content_hash"))
            if row["content_hash"] != macro_observation_content_hash(row):
                raise ValueError(
                    "observation content_hash does not match normalized record"
                )
        values = [
            (
                row["artifact_id"],
                row["domain"],
                row["series_id"],
                row["period_end"],
                row["frequency"],
                row["unit"],
                row.get("value_numeric"),
                row.get("value_text"),
                Jsonb(row["value_json"]) if row.get("value_json") is not None else None,
                row["source"],
                row["source_record_id"],
                row.get("published_at"),
                row["available_at"],
                seen_at,
                seen_at,
                row["content_hash"],
                row["parser_version"],
                row["quality_status"],
                row["cost_class"],
            )
            for row in materialized_rows
        ]
        if not values:
            return 0
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                _validate_artifact_bounds(cur, self._schema, materialized_rows)
                cur.executemany(
                    f"""
                    INSERT INTO {self._schema}.macro_observations (
                      artifact_id, domain, series_id, period_end, frequency, unit,
                      value_numeric, value_text, value_jsonb,
                      source, source_record_id, published_at, available_at,
                      first_observed_at, last_seen_at,
                      content_hash, parser_version, quality_status, cost_class
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s,
                      %s, %s, %s, %s
                    )
                    ON CONFLICT (
                      source, series_id, period_end, available_at, content_hash
                    )
                    DO UPDATE SET last_seen_at =
                      GREATEST(
                        {self._schema}.macro_observations.last_seen_at,
                        EXCLUDED.last_seen_at
                      )
                    WHERE
                      {self._schema}.macro_observations.artifact_id
                        IS NOT DISTINCT FROM EXCLUDED.artifact_id
                      AND {self._schema}.macro_observations.domain
                        IS NOT DISTINCT FROM EXCLUDED.domain
                      AND {self._schema}.macro_observations.frequency
                        IS NOT DISTINCT FROM EXCLUDED.frequency
                      AND {self._schema}.macro_observations.unit
                        IS NOT DISTINCT FROM EXCLUDED.unit
                      AND {self._schema}.macro_observations.value_numeric
                        IS NOT DISTINCT FROM EXCLUDED.value_numeric
                      AND {self._schema}.macro_observations.value_text
                        IS NOT DISTINCT FROM EXCLUDED.value_text
                      AND {self._schema}.macro_observations.value_jsonb
                        IS NOT DISTINCT FROM EXCLUDED.value_jsonb
                      AND {self._schema}.macro_observations.source_record_id
                        IS NOT DISTINCT FROM EXCLUDED.source_record_id
                      AND {self._schema}.macro_observations.published_at
                        IS NOT DISTINCT FROM EXCLUDED.published_at
                      AND {self._schema}.macro_observations.parser_version
                        IS NOT DISTINCT FROM EXCLUDED.parser_version
                      AND {self._schema}.macro_observations.quality_status
                        IS NOT DISTINCT FROM EXCLUDED.quality_status
                      AND {self._schema}.macro_observations.cost_class
                        IS NOT DISTINCT FROM EXCLUDED.cost_class
                    """,
                    values,
                )
                if cur.rowcount != len(values):
                    raise ValueError(
                        "observation identity collision: immutable metadata differs"
                    )
        return len(values)

    def fetch_macro_observation_as_of(
        self,
        series_id: str,
        period_end: date,
        as_of: datetime,
        *,
        preferred_sources: Sequence[str],
    ) -> dict[str, Any] | None:
        _require_aware("as_of", as_of)
        rank_sql, rank_params = _source_rank_sql(preferred_sources)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT o.*, a.source_url, a.source_kind, a.media_type
                FROM {self._schema}.macro_observations o
                JOIN {self._schema}.macro_source_artifacts a
                  ON a.artifact_id = o.artifact_id
                WHERE o.series_id = %s
                  AND o.period_end = %s
                  AND o.available_at <= %s
                  AND o.quality_status IN ('valid', 'partial')
                  AND {_ARTIFACT_AVAILABLE}
                  AND a.quality_status IN ('valid', 'partial')
                ORDER BY {rank_sql}, o.available_at DESC,
                         o.first_observed_at DESC, o.obs_id DESC
                LIMIT 1
                """,
                (series_id, period_end, as_of, as_of, *rank_params),
            )
            return cur.fetchone()

    def fetch_macro_series_as_of(
        self,
        series_id: str,
        as_of: datetime,
        *,
        from_date: date | None = None,
        preferred_sources: Sequence[str],
    ) -> list[dict[str, Any]]:
        _require_aware("as_of", as_of)
        clauses = [
            "o.series_id = %s",
            "o.available_at <= %s",
            "o.quality_status IN ('valid', 'partial')",
            _ARTIFACT_AVAILABLE,
            "a.quality_status IN ('valid', 'partial')",
        ]
        params: list[Any] = [series_id, as_of, as_of]
        if from_date is not None:
            clauses.append("o.period_end >= %s")
            params.append(from_date)
        rank_sql, rank_params = _source_rank_sql(preferred_sources)
        params.extend(rank_params)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (o.period_end)
                  o.*, a.source_url, a.source_kind, a.media_type
                FROM {self._schema}.macro_observations o
                JOIN {self._schema}.macro_source_artifacts a
                  ON a.artifact_id = o.artifact_id
                WHERE {" AND ".join(clauses)}
                ORDER BY o.period_end ASC, {rank_sql}, o.available_at DESC,
                         o.first_observed_at DESC, o.obs_id DESC
                """,
                params,
            )
            return list(cur.fetchall())

    def fetch_latest_macro_observation_as_of(
        self,
        series_id: str,
        as_of: datetime,
        *,
        preferred_sources: Sequence[str],
    ) -> dict[str, Any] | None:
        """The newest PERIOD available by ``as_of``, at its newest vintage.

        Period first, vintage second.  Sorting by ``available_at`` first answers
        "what did we most recently write", which is a fact about our own fetch
        schedule: backfilling a publisher's archive out of order then makes the
        last file downloaded the current release, and a revision to a two-year-old
        period outranks this month's reading.  Ordering by ``period_end`` first
        asks the question the caller means -- what is the latest reading -- and
        ``available_at DESC`` still picks the newest vintage OF that period, which
        is the part that must stay point-in-time.
        """
        _require_aware("as_of", as_of)
        rank_sql, rank_params = _source_rank_sql(preferred_sources)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT o.*, a.source_url, a.source_kind, a.media_type
                FROM {self._schema}.macro_observations o
                JOIN {self._schema}.macro_source_artifacts a
                  ON a.artifact_id = o.artifact_id
                WHERE o.series_id = %s
                  AND o.available_at <= %s
                  AND o.quality_status IN ('valid', 'partial')
                  AND {_ARTIFACT_AVAILABLE}
                  AND a.quality_status IN ('valid', 'partial')
                ORDER BY {rank_sql}, o.period_end DESC,
                         o.available_at DESC, o.first_observed_at DESC,
                         o.obs_id DESC
                LIMIT 1
                """,
                (series_id, as_of, as_of, *rank_params),
            )
            return cur.fetchone()

    def fetch_recent_macro_observations_as_of(
        self,
        series_id: str,
        as_of: datetime,
        *,
        preferred_sources: Sequence[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """The most recent distinct RELEASES of a series, newest first.

        Not "the newest N rows".  A release that was corrected has more than one
        row, and taking rows would spend the caller's budget re-reading one survey
        as though it were several -- so the newest surviving row per
        ``release_key`` is picked first, and only then are releases ranked.

        Same point-in-time gate as every other read here: ``available_at <=
        as_of`` on the observation, and on the artifact unless it is
        vintage-bearing.  A caller asking for prior releases as of a past instant
        gets what was published by then, never what we know now.
        """
        _require_aware("as_of", as_of)
        if limit < 1:
            raise ValueError("limit must be positive")
        rank_sql, rank_params = _source_rank_sql(preferred_sources)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT * FROM (
                    SELECT DISTINCT ON (o.release_key)
                           o.*, a.source_url, a.source_kind, a.media_type
                    FROM {self._schema}.macro_observations o
                    JOIN {self._schema}.macro_source_artifacts a
                      ON a.artifact_id = o.artifact_id
                    WHERE o.series_id = %s
                      AND o.available_at <= %s
                      AND o.quality_status IN ('valid', 'partial')
                      AND {_ARTIFACT_AVAILABLE}
                      AND a.quality_status IN ('valid', 'partial')
                    ORDER BY o.release_key, {rank_sql}, o.available_at DESC,
                             o.first_observed_at DESC, o.obs_id DESC
                ) AS releases
                ORDER BY period_end DESC, available_at DESC, obs_id DESC
                LIMIT %s
                """,
                (series_id, as_of, as_of, *rank_params, limit),
            )
            return list(cur.fetchall())

    def fetch_macro_observation_history(
        self,
        series_id: str,
        period_end: date,
    ) -> list[dict[str, Any]]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT o.*, a.source_url, a.source_kind, a.media_type
                FROM {self._schema}.macro_observations o
                JOIN {self._schema}.macro_source_artifacts a
                  ON a.artifact_id = o.artifact_id
                WHERE o.series_id = %s AND o.period_end = %s
                ORDER BY o.available_at DESC, o.first_observed_at DESC,
                         o.source, o.obs_id DESC
                """,
                (series_id, period_end),
            )
            return list(cur.fetchall())

    def upsert_macro_source_status(
        self,
        source: str,
        *,
        status: str,
        attempted_at: datetime,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        _require_aware("attempted_at", attempted_at)
        if status not in {"ok", "degraded"}:
            raise ValueError("macro source status must be ok or degraded")
        if status == "ok" and (error_type is not None or error_message is not None):
            raise ValueError("successful macro source status cannot carry an error")
        if status == "degraded" and not error_type:
            raise ValueError("degraded macro source status requires error_type")
        safe_type = error_type[:200] if error_type is not None else None
        safe_message = error_message[:1000] if error_message is not None else None
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.macro_source_status (
                  source, status, last_attempt_at, last_success_at,
                  consecutive_failures, error_type, error_message, updated_at
                )
                VALUES (
                  %s, %s, %s,
                  CASE WHEN %s = 'ok' THEN %s ELSE NULL END,
                  CASE WHEN %s = 'ok' THEN 0 ELSE 1 END,
                  %s, %s, %s
                )
                ON CONFLICT (source) DO UPDATE SET
                  status = EXCLUDED.status,
                  last_attempt_at = EXCLUDED.last_attempt_at,
                  last_success_at = CASE
                    WHEN EXCLUDED.status = 'ok' THEN EXCLUDED.last_attempt_at
                    ELSE {self._schema}.macro_source_status.last_success_at
                  END,
                  consecutive_failures = CASE
                    WHEN EXCLUDED.status = 'ok' THEN 0
                    ELSE {self._schema}.macro_source_status.consecutive_failures + 1
                  END,
                  error_type = EXCLUDED.error_type,
                  error_message = EXCLUDED.error_message,
                  updated_at = EXCLUDED.updated_at
                """,
                (
                    source,
                    status,
                    attempted_at,
                    status,
                    attempted_at,
                    status,
                    safe_type,
                    safe_message,
                    attempted_at,
                ),
            )

    def fetch_macro_source_status(self, source: str) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {self._schema}.macro_source_status
                WHERE source = %s
                """,
                (source,),
            )
            return cur.fetchone()

    def fetch_macro_source_statuses(
        self, sources: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        if not sources:
            return {}
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {self._schema}.macro_source_status
                WHERE source = ANY(%s)
                """,
                (list(sources),),
            )
            return {row["source"]: row for row in cur.fetchall()}


def _source_rank_sql(preferred_sources: Sequence[str]) -> tuple[str, list[str]]:
    if not preferred_sources:
        raise ValueError("preferred_sources must not be empty")
    if any(not source.strip() for source in preferred_sources):
        raise ValueError("preferred_sources must contain non-empty source names")
    if len(set(preferred_sources)) != len(preferred_sources):
        raise ValueError("preferred_sources must not contain duplicates")
    clauses = [f"WHEN %s THEN {rank}" for rank, _ in enumerate(preferred_sources)]
    return f"CASE o.source {' '.join(clauses)} ELSE {len(clauses)} END", list(
        preferred_sources
    )


def _revision_available_at(
    cur: psycopg.Cursor,
    schema: str,
    *,
    source: str,
    source_record_id: str,
    content_hash: str,
    available_at: datetime,
    retrieved_at: datetime,
) -> datetime:
    """Availability of these exact bytes, never the release's original instant.

    The publisher's declared release instant is honest evidence for the FIRST
    bytes we saw under a record.  It is not evidence for a correction: those
    bytes did not exist at that instant, and dating them there is a look-ahead
    leak in the dangerous direction -- a replay would read a value nobody could
    have seen for weeks.  A later revision can only justify ``retrieved_at``.

    Re-inserting bytes we already hold returns their stored instant unchanged,
    so a rerun neither moves availability nor trips the upsert's equality guard.
    """
    cur.execute(
        f"""
        SELECT
          max(available_at) FILTER (WHERE content_hash = %s) AS same_bytes,
          bool_or(content_hash <> %s) AS other_bytes
        FROM {schema}.macro_source_artifacts
        WHERE source = %s AND source_record_id = %s
        """,
        (content_hash, content_hash, source, source_record_id),
    )
    row = cur.fetchone()
    same_bytes, other_bytes = (row[0], row[1]) if row is not None else (None, False)
    if same_bytes is not None:
        return same_bytes
    if other_bytes:
        return max(available_at, retrieved_at)
    return available_at


def _require_aware(
    name: str,
    value: datetime | None,
    *,
    optional: bool = False,
) -> None:
    if value is None:
        if optional:
            return
        raise ValueError(f"{name} is required")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("content_hash must be lowercase SHA-256 hex")


def _validate_artifact_bounds(
    cur: psycopg.Cursor[Any],
    schema: str,
    rows: Sequence[dict[str, Any]],
) -> None:
    artifact_ids = sorted({int(row["artifact_id"]) for row in rows})
    cur.execute(
        f"""
        SELECT artifact_id, source, source_record_id, available_at, quality_status
        FROM {schema}.macro_source_artifacts
        WHERE artifact_id = ANY(%s)
        FOR KEY SHARE
        """,
        (artifact_ids,),
    )
    artifacts = {int(row[0]): row for row in cur.fetchall()}
    for row in rows:
        artifact_id = int(row["artifact_id"])
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise ValueError(f"macro artifact {artifact_id} does not exist")
        _, source, source_record_id, available_at, quality_status = artifact
        if (row["source"], row["source_record_id"]) != (
            source,
            source_record_id,
        ):
            raise ValueError("observation source identity differs from its artifact")
        if row["available_at"] < available_at:
            raise ValueError("observation available_at precedes artifact available_at")
        if (row["quality_status"] == "valid" and quality_status != "valid") or (
            row["quality_status"] == "partial"
            and quality_status not in {"valid", "partial"}
        ):
            raise ValueError("observation quality exceeds artifact quality")
