"""Generic agent-run store (migration 148). Standalone repository.

This module is the ONLY thing in argon that touches `uw_scan.agent_runs`, and
it is deliberately blind to what a run contains. `kind` is an opaque label the
writer chose and `view` is a document this layer never inspects — typing either
one would make a new writer a schema change instead of an insert.

Every method is keyword-only and takes `tenant` explicitly. There is no default
and no ambient current tenant, so a caller cannot read another tenant's rows by
forgetting an argument.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# Columns of the index view: everything a navigation surface needs and not the
# document. An index that carried every view would ship megabytes to draw a
# handful of cards.
_INDEX_COLUMNS = (
    "run_day, kind, run_id, version_no, outcome, headline, "
    "code_sha, schema_version, created_at"
)


def iso_week_key(day: date) -> str:
    """`2026-09-03` -> `2026-W36`, on the ISO year rather than the calendar one.

    Only a fallback: the writer normally sends `week_key`, because only the
    writer knows a run is backward-looking (a Monday review of the week that
    just ended belongs to that earlier week).
    """
    iso_year, iso_week, _ = day.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


class AgentRunsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def ingest(
        self,
        *,
        tenant: str,
        kind: str,
        run_day: date,
        run_id: str,
        code_sha: str,
        schema_version: int,
        outcome: str,
        headline: str = "",
        view: Mapping[str, Any],
        report: Mapping[str, Any] | None = None,
        week_key: str | None = None,
    ) -> tuple[int, bool]:
        """Store one run. Returns `(version_no, created)`.

        `created=False` means this `run_id` was already stored — the answer to a
        blind retry, not an error. Publishing a second row would show the reader
        a run that never happened twice.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT version_no FROM {self._schema}.agent_runs
                     WHERE tenant = %s AND run_id = %s""",
                (tenant, run_id),
            )
            existing = cur.fetchone()
            if existing is not None:
                return int(existing[0]), False

            cur.execute(
                f"""INSERT INTO {self._schema}.agent_runs
                            (tenant, kind, run_day, week_key, run_id, version_no,
                             code_sha, schema_version, outcome, headline,
                             view_jsonb, report_jsonb)
                     SELECT %s, %s, %s, %s, %s,
                            COALESCE(MAX(version_no), 0) + 1,
                            %s, %s, %s, %s, %s, %s
                       FROM {self._schema}.agent_runs
                      WHERE tenant = %s AND kind = %s AND run_day = %s
                  RETURNING version_no""",
                (
                    tenant,
                    kind,
                    run_day,
                    week_key or iso_week_key(run_day),
                    run_id,
                    code_sha,
                    schema_version,
                    outcome,
                    headline,
                    Jsonb(dict(view)),
                    Jsonb(dict(report or {})),
                    tenant,
                    kind,
                    run_day,
                ),
            )
            version_no = int(cur.fetchone()[0])
        self.conn.commit()
        return version_no, True

    def weeks(self, *, tenant: str, limit: int = 52) -> list[dict[str, Any]]:
        """Recorded weeks, newest first.

        Only weeks that have a run: a week with no rows is not a navigation
        destination, and offering it as one would promise a page that is empty
        by construction.
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""SELECT week_key,
                           MIN(run_day) AS first_day,
                           MAX(run_day) AS last_day,
                           COUNT(*)                AS run_count,
                           COUNT(DISTINCT run_day) AS day_count
                      FROM {self._schema}.agent_runs
                     WHERE tenant = %s
                  GROUP BY week_key
                  ORDER BY week_key DESC
                     LIMIT %s""",
                (tenant, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def week(self, *, tenant: str, week_key: str) -> list[dict[str, Any]]:
        """The week's index: newest version per (run_day, kind). No documents."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (run_day, kind) {_INDEX_COLUMNS}
                      FROM {self._schema}.agent_runs
                     WHERE tenant = %s AND week_key = %s
                  ORDER BY run_day, kind, version_no DESC""",
                (tenant, week_key),
            )
            return [dict(r) for r in cur.fetchall()]

    def run(
        self,
        *,
        tenant: str,
        kind: str,
        run_day: date,
        version_no: int | None = None,
    ) -> dict[str, Any] | None:
        """One run with its document. Newest version unless one is named."""
        params: list[Any] = [tenant, kind, run_day]
        version_clause = ""
        if version_no is not None:
            version_clause = " AND version_no = %s"
            params.append(version_no)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""SELECT {_INDEX_COLUMNS}, week_key,
                           view_jsonb AS view, report_jsonb AS report
                      FROM {self._schema}.agent_runs
                     WHERE tenant = %s AND kind = %s AND run_day = %s
                           {version_clause}
                  ORDER BY version_no DESC
                     LIMIT 1""",
                params,
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def latest(self, *, tenant: str, kind: str | None = None) -> dict[str, Any] | None:
        """The newest run for this tenant, optionally within one kind."""
        params: list[Any] = [tenant]
        kind_clause = ""
        if kind is not None:
            kind_clause = " AND kind = %s"
            params.append(kind)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""SELECT {_INDEX_COLUMNS}, week_key,
                           view_jsonb AS view, report_jsonb AS report
                      FROM {self._schema}.agent_runs
                     WHERE tenant = %s{kind_clause}
                  ORDER BY run_day DESC, version_no DESC, agent_run_id DESC
                     LIMIT 1""",
                params,
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None
