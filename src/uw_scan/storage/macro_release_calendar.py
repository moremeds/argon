"""Weekly economic-release calendar store. See migration 149.

Standalone repository (storage/CLAUDE.md's preferred shape for a new
domain) -- not composed into `Repository`.

Two disjoint write paths on the same row:

- `upsert_captured_rows` (the UW capture job) owns event/type/reported_period/
  forecast/prior -- UW's own fields, safe to overwrite on every capture since
  UW may correct a forecast before the print.
- `fill_actual` (the FRED enrichment job) owns series_id/actual/
  actual_first_seen/revision/published_at exclusively. A capture replay must
  never touch these -- there is no re-derivation of a published actual from a
  forecast row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg


class MacroReleaseCalendarRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_captured_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-refresh UW's own fields for each (event, scheduled_at).
        Returns rows genuinely NEW (via `xmax = 0`), not `len(rows)` -- a
        same-window replay of an unchanged calendar reports zero new rows."""
        if not rows:
            return 0
        table = f"{self._schema}.macro_release_calendar"
        sql = f"""
            INSERT INTO {table}
                        (event, scheduled_at, type, reported_period, forecast, prior)
                 VALUES (%(event)s, %(scheduled_at)s, %(type)s, %(reported_period)s,
                         %(forecast)s, %(prior)s)
            ON CONFLICT (event, scheduled_at) DO UPDATE SET
                 type            = EXCLUDED.type,
                 reported_period = EXCLUDED.reported_period,
                 forecast        = EXCLUDED.forecast,
                 prior           = EXCLUDED.prior,
                 captured_at     = now()
              RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        with self.conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, row)
                if cur.fetchone()[0]:
                    inserted += 1
        self.conn.commit()
        return inserted

    def unfilled_mapped(
        self, *, series_ids: dict[str, str], before: datetime
    ) -> list[dict[str, Any]]:
        """Rows scheduled before `before` whose event maps to a known FRED
        series (`series_ids`: lowercased event -> series_id) and that have
        never had `series_id` recorded -- the fill job's work queue. Once a
        row has a series_id, only `fill_actual` touches it again (a revision
        re-fill re-derives revision from `actual_first_seen`, not from this
        query, so an already-filled row correctly drops out here)."""
        if not series_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT event, scheduled_at, reported_period
                      FROM {self._schema}.macro_release_calendar
                     WHERE scheduled_at < %s AND series_id IS NULL
                     ORDER BY scheduled_at""",
                (before,),
            )
            out = []
            for event, scheduled_at, reported_period in cur.fetchall():
                series_id = series_ids.get(event.strip().lower())
                if series_id is not None:
                    out.append(
                        {
                            "event": event,
                            "scheduled_at": scheduled_at,
                            "reported_period": reported_period,
                            "series_id": series_id,
                        }
                    )
            return out

    def fill_actual(
        self,
        *,
        event: str,
        scheduled_at: datetime,
        series_id: str,
        actual: Decimal,
        published_at: datetime,
    ) -> None:
        """Record the FRED actual for one release. `revision` is set by
        comparing to `actual_first_seen`, which this call establishes on the
        first fill and never overwrites after."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {self._schema}.macro_release_calendar
                       SET series_id         = %(series_id)s,
                           actual            = %(actual)s,
                           actual_first_seen = COALESCE(actual_first_seen, %(actual)s),
                           published_at      = %(published_at)s,
                           revision = (COALESCE(actual_first_seen, %(actual)s) <> %(actual)s)
                     WHERE event = %(event)s AND scheduled_at = %(scheduled_at)s""",
                {
                    "event": event,
                    "scheduled_at": scheduled_at,
                    "series_id": series_id,
                    "actual": actual,
                    "published_at": published_at,
                },
            )
        self.conn.commit()

    def week(self, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Every release scheduled in [start, end), earliest first."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT event, type, reported_period, scheduled_at, forecast,
                           prior, series_id, actual, revision, published_at
                      FROM {self._schema}.macro_release_calendar
                     WHERE scheduled_at >= %s AND scheduled_at < %s
                     ORDER BY scheduled_at""",
                (start, end),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
