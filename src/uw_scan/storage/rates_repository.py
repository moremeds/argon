"""US rates mirror persistence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class _RatesMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_rates_observation_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        seen_at: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["series_id"],
                row["obs_date"],
                row["value"],
                row["realtime_start"],
                row["realtime_end"],
                seen_at,
                seen_at,
                row.get("release_date"),
                source,
                row.get("source_url"),
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_observations
                  (
                    series_id,
                    obs_date,
                    value,
                    realtime_start,
                    realtime_end,
                    first_seen_at,
                    last_seen_at,
                    release_date,
                    source,
                    source_url
                  )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_date, realtime_start, realtime_end, source)
                DO UPDATE SET
                  value = EXCLUDED.value,
                  last_seen_at = EXCLUDED.last_seen_at,
                  release_date = EXCLUDED.release_date,
                  source_url = EXCLUDED.source_url
                """,
                values,
            )
        return len(values)

    def fetch_rates_series(
        self,
        series_id: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        realtime_start_max: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if from_date is not None:
            clauses.append("obs_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s")
            params.append(to_date)
        if realtime_start_max is not None:
            clauses.append("realtime_start <= %s")
            params.append(realtime_start_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  series_id,
                  obs_date,
                  value,
                  realtime_start,
                  realtime_end,
                  first_seen_at,
                  last_seen_at,
                  release_date,
                  source,
                  source_url
                FROM {self._schema}.rates_observations
                WHERE {where}
                ORDER BY obs_date ASC, realtime_start DESC, last_seen_at DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def fetch_latest_rates_values(
        self,
        series_ids: Iterable[str],
        *,
        realtime_start_max: _date | None = None,
    ) -> dict[str, dict[str, Any]]:
        ids = list(series_ids)
        if not ids:
            return {}
        clauses = ["series_id = ANY(%s)"]
        params: list[Any] = [ids]
        if realtime_start_max is not None:
            clauses.append("realtime_start <= %s")
            params.append(realtime_start_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (series_id)
                  series_id,
                  obs_date,
                  value,
                  realtime_start,
                  realtime_end,
                  first_seen_at,
                  last_seen_at,
                  release_date,
                  source,
                  source_url
                FROM {self._schema}.rates_observations
                WHERE {where}
                ORDER BY series_id, obs_date DESC, realtime_start DESC, last_seen_at DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return {
                row_dict["series_id"]: row_dict
                for row_dict in [
                    dict(zip(cols, row, strict=True)) for row in cur.fetchall()
                ]
            }

    def insert_rates_snapshot(
        self,
        *,
        snapshot_date: _date,
        computed_at: datetime,
        payload: dict[str, Any],
        source_freshness: list[dict[str, Any]],
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.rates_snapshots
                  (snapshot_date, computed_at, payload, source_freshness)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (snapshot_date, computed_at)
                DO UPDATE SET
                  payload = EXCLUDED.payload,
                  source_freshness = EXCLUDED.source_freshness
                """,
                (
                    snapshot_date,
                    computed_at,
                    Jsonb(payload),
                    Jsonb(source_freshness),
                ),
            )

    def fetch_latest_rates_snapshot(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT snapshot_date, computed_at, payload, source_freshness
                FROM {self._schema}.rates_snapshots
                ORDER BY computed_at DESC, snapshot_date DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))
