"""Typed provenance for derived fundamental results (migration 135).

`fundamental_scores.source_obs_ids` says which observations a score was computed
from. It cannot say which were considered and EXCLUDED, which content version
LOST canonical selection, or which stage consumed what — and nothing enforces
that an id in it names a real observation. This module owns the table that does.

The compatibility contract is deliberate: v1 score rows are NOT backfilled, so a
result with no rows here reads as *legacy*, which is different from *typed
provenance was recorded and it lists nothing*. The second would be a bug.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

ROLE_USED = "used"
ROLE_EXCLUDED = "excluded"
ROLE_SUPERSEDED = "superseded"

STAGE_PANEL = "panel"
STAGE_FEATURES = "features"
STAGE_SCORING = "scoring"

#: A result whose provenance predates migration 135. Not an error state.
STATE_LEGACY = "legacy"
STATE_TYPED = "typed"


class FundamentalProvenanceRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def record(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert provenance rows. Returns how many were genuinely new.

        `ON CONFLICT DO NOTHING` on `(result_id, obs_id, role, stage)`: a rerun
        of the same scoring pass re-derives the same links, and re-recording them
        is a no-op rather than a duplicate.
        """
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.fundamental_result_provenance
                        (result_id, obs_id, role, stage, detail_jsonb)
                 VALUES (%(result_id)s, %(obs_id)s, %(role)s, %(stage)s,
                         %(detail_jsonb)s)
            ON CONFLICT (result_id, obs_id, role, stage) DO NOTHING
        """
        payload = [
            {
                "result_id": r["result_id"],
                "obs_id": r["obs_id"],
                "role": r["role"],
                "stage": r["stage"],
                "detail_jsonb": Jsonb(r.get("detail") or {}),
            }
            for r in rows
        ]
        before = self._count()
        with self.conn.cursor() as cur:
            cur.executemany(sql, payload)
        self.conn.commit()
        return self._count() - before

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM {self._schema}.fundamental_result_provenance"
            )
            return int(cur.fetchone()[0])

    def for_result(self, result_id: int) -> dict[str, Any]:
        """Everything cited by one result, grouped by role, plus its state.

        `state` is the load-bearing field for a caller rendering an evidence
        drill-down: `legacy` means the result predates typed provenance and its
        `source_obs_ids` array is all there is, which must not be presented as
        "this result used nothing".
        """
        sql = f"""
            SELECT p.role, p.stage, p.obs_id, p.detail_jsonb,
                   o.ticker, o.period_end, o.statement, o.content_hash
              FROM {self._schema}.fundamental_result_provenance p
              JOIN {self._schema}.fundamental_statement_obs o USING (obs_id)
             WHERE p.result_id = %s
             ORDER BY p.role, o.period_end, o.statement
        """
        out: dict[str, list[dict[str, Any]]] = {
            ROLE_USED: [],
            ROLE_EXCLUDED: [],
            ROLE_SUPERSEDED: [],
        }
        with self.conn.cursor() as cur:
            cur.execute(sql, (result_id,))
            for role, stage, obs_id, detail, tkr, per, stmt, chash in cur.fetchall():
                out.setdefault(role, []).append(
                    {
                        "obs_id": obs_id,
                        "stage": stage,
                        "detail": detail or {},
                        "ticker": tkr,
                        "period_end": per,
                        "statement": stmt,
                        "content_hash": chash,
                    }
                )
        total = sum(len(v) for v in out.values())
        legacy_ids = self._legacy_ids(result_id) if total == 0 else []
        return {
            "result_id": result_id,
            "state": STATE_TYPED if total else STATE_LEGACY,
            "legacy_source_obs_ids": legacy_ids,
            **out,
        }

    def _legacy_ids(self, result_id: int) -> list[int]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT source_obs_ids FROM {self._schema}.fundamental_scores
                     WHERE result_id = %s""",
                (result_id,),
            )
            row = cur.fetchone()
            return list(row[0]) if row and row[0] else []

    def counts_by_engine(self) -> dict[str, dict[str, int]]:
        """Coverage: how many results per engine carry typed provenance."""
        sql = f"""
            SELECT s.engine_version,
                   count(DISTINCT s.result_id) AS results,
                   count(DISTINCT p.result_id) AS with_provenance
              FROM {self._schema}.fundamental_scores s
              LEFT JOIN {self._schema}.fundamental_result_provenance p
                     ON p.result_id = s.result_id
             GROUP BY s.engine_version
             ORDER BY s.engine_version
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return {
                eng: {"results": int(n), "with_provenance": int(w)}
                for eng, n, w in cur.fetchall()
            }
