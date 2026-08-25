"""The fundamental run ledger (migration 135). Standalone repository.

Records the QUESTION — scope, as-of, evidence policy, method version, mode — that
`fundamental_scores` only ever records the ANSWER to. Every later product (the
Radar's freshness, the report's "assembled from run N", the delta against a prior
version) reads from here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
TERMINAL = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED})

MODE_COMPUTE = "compute"
MODE_REUSE = "reuse"
MODE_REFRESH = "refresh"

STAGE_PANEL = "panel"
STAGE_FEATURES = "features"
STAGE_SCORING = "scoring"
STAGE_ANCHORS = "anchors"
STAGES = (STAGE_PANEL, STAGE_FEATURES, STAGE_SCORING, STAGE_ANCHORS)


def request_hash(
    *,
    scope_kind: str,
    scope: Mapping[str, Any],
    as_of: date | None,
    evidence_policy: str,
    engine_version: str | None,
) -> str:
    """Identity of a REQUEST. Two identical requests are one logical run.

    Deliberately excludes the clock. A run one second later asking the same
    question is the same question; what makes it a different run is a different
    scope, as-of, policy, or engine — each of which changes what the answer
    MEANS, which a timestamp does not.
    """
    blob = json.dumps(
        {
            "scope_kind": scope_kind,
            "scope": {k: scope[k] for k in sorted(scope)},
            "as_of": as_of.isoformat() if as_of else None,
            "evidence_policy": evidence_policy,
            "engine_version": engine_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class FundamentalRunsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- runs ----------------

    def enqueue(
        self,
        *,
        scope_kind: str,
        scope: Mapping[str, Any],
        evidence_policy: str,
        as_of: date | None = None,
        engine_version: str | None = None,
        mode: str = MODE_COMPUTE,
    ) -> tuple[int, bool]:
        """(run_id, created). Returns the EXISTING active run if one matches.

        Not an error when a run is already in flight — the caller asked a
        question that is already being answered, and handing back that run is
        the useful reply. Raising would push every caller into the same
        catch-and-look-up dance.
        """
        rhash = request_hash(
            scope_kind=scope_kind,
            scope=scope,
            as_of=as_of,
            evidence_policy=evidence_policy,
            engine_version=engine_version,
        )
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT run_id FROM {self._schema}.fundamental_runs
                     WHERE request_hash = %s AND status IN ('queued','running')""",
                (rhash,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0]), False
            cur.execute(
                f"""INSERT INTO {self._schema}.fundamental_runs
                            (request_hash, scope_kind, scope_jsonb, as_of,
                             evidence_policy, engine_version, mode)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)
                  RETURNING run_id""",
                (
                    rhash,
                    scope_kind,
                    Jsonb(dict(scope)),
                    as_of,
                    evidence_policy,
                    engine_version,
                    mode,
                ),
            )
            run_id = int(cur.fetchone()[0])
        self.conn.commit()
        return run_id, True

    def start(self, run_id: int) -> None:
        self._update(run_id, "status = 'running', started_at = now(), heartbeat_at = now()")

    def heartbeat(self, run_id: int) -> None:
        self._update(run_id, "heartbeat_at = now()")

    def finish(
        self,
        run_id: int,
        *,
        status: str,
        counters: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in TERMINAL:
            raise ValueError(f"{status!r} is not terminal; expected {sorted(TERMINAL)}")
        with self.conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {self._schema}.fundamental_runs
                       SET status = %s, finished_at = now(),
                           counters_jsonb = %s, error = %s
                     WHERE run_id = %s""",
                (status, Jsonb(dict(counters or {})), error, run_id),
            )
        self.conn.commit()

    def _update(self, run_id: int, setexpr: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.fundamental_runs SET {setexpr} "
                f"WHERE run_id = %s",
                (run_id,),
            )
        self.conn.commit()

    def get(self, run_id: int) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.fundamental_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            out = dict(zip(cols, row, strict=True))
        out["stages"] = self.stages(run_id)
        return out

    def latest_succeeded(
        self,
        *,
        scope_kind: str,
        scope: Mapping[str, Any],
        evidence_policy: str,
        as_of: date | None = None,
        engine_version: str | None = None,
    ) -> dict[str, Any] | None:
        """The most recent successful run answering exactly this question.

        This is what `mode='reuse'` consults. Matching on `request_hash` rather
        than on a fuzzy "close enough" comparison is deliberate: a reuse that
        silently accepted a different as-of or policy would answer the operator's
        question with someone else's.
        """
        rhash = request_hash(
            scope_kind=scope_kind,
            scope=scope,
            as_of=as_of,
            evidence_policy=evidence_policy,
            engine_version=engine_version,
        )
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT run_id FROM {self._schema}.fundamental_runs
                     WHERE request_hash = %s AND status = 'succeeded'
                     ORDER BY finished_at DESC NULLS LAST LIMIT 1""",
                (rhash,),
            )
            row = cur.fetchone()
        return self.get(int(row[0])) if row else None

    # ---------------- stages ----------------

    def stage_start(
        self, run_id: int, stage: str, *, inputs_hash: str | None = None
    ) -> int:
        """Open a stage attempt. Returns stage_id; a retry gets a new attempt."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT coalesce(max(attempt), 0) + 1
                      FROM {self._schema}.fundamental_run_stages
                     WHERE run_id = %s AND stage = %s""",
                (run_id, stage),
            )
            attempt = int(cur.fetchone()[0])
            cur.execute(
                f"""INSERT INTO {self._schema}.fundamental_run_stages
                            (run_id, stage, attempt, status, inputs_hash, started_at)
                     VALUES (%s, %s, %s, 'running', %s, now())
                  RETURNING stage_id""",
                (run_id, stage, attempt, inputs_hash),
            )
            stage_id = int(cur.fetchone()[0])
        self.conn.commit()
        return stage_id

    def stage_finish(
        self,
        stage_id: int,
        *,
        status: str,
        counters: Mapping[str, Any] | None = None,
        outputs_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {self._schema}.fundamental_run_stages
                       SET status = %s, finished_at = now(),
                           counters_jsonb = %s, outputs_hash = %s, error = %s
                     WHERE stage_id = %s""",
                (status, Jsonb(dict(counters or {})), outputs_hash, error, stage_id),
            )
        self.conn.commit()

    def stages(self, run_id: int) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT stage, attempt, status, inputs_hash, outputs_hash,
                           counters_jsonb, error, started_at, finished_at
                      FROM {self._schema}.fundamental_run_stages
                     WHERE run_id = %s
                     ORDER BY stage_id""",
                (run_id,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---------------- telemetry ----------------

    def queue_health(self, stale_seconds: int = 900) -> dict[str, Any]:
        """Depth, age, and how many 'running' rows are actually corpses.

        A stalled run reports `running` forever; without the heartbeat age, queue
        depth alone reads as busy rather than wedged.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*) FILTER (WHERE status = 'queued'),
                       count(*) FILTER (WHERE status = 'running'),
                       count(*) FILTER (WHERE status = 'running'
                                          AND (heartbeat_at IS NULL
                                           OR heartbeat_at < now()
                                              - make_interval(secs => %s))),
                       extract(epoch FROM now()
                         - min(requested_at) FILTER (WHERE status = 'queued'))
                  FROM {self._schema}.fundamental_runs
                """,
                (stale_seconds,),
            )
            queued, running, stalled, oldest = cur.fetchone()
        return {
            "queued": int(queued),
            "running": int(running),
            "stalled": int(stalled),
            "oldest_queued_seconds": float(oldest) if oldest is not None else None,
        }

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT run_id, scope_kind, as_of, evidence_policy,
                           engine_version, status, mode, counters_jsonb,
                           requested_at, finished_at
                      FROM {self._schema}.fundamental_runs
                     ORDER BY requested_at DESC LIMIT %s""",
                (limit,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def cancel_stale(self, stale_seconds: int = 900) -> int:
        """Mark heartbeat-dead runs cancelled. Returns how many.

        A proven corpse must be cleared, or its request_hash blocks every future
        run of the same question through the active-run unique index.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {self._schema}.fundamental_runs
                       SET status = 'cancelled', finished_at = now(),
                           error = 'heartbeat expired'
                     WHERE status IN ('queued', 'running')
                       AND (heartbeat_at IS NULL OR heartbeat_at < now()
                            - make_interval(secs => %s))
                       AND requested_at < now() - make_interval(secs => %s)
                  RETURNING run_id""",
                (stale_seconds, stale_seconds),
            )
            n = len(cur.fetchall())
        self.conn.commit()
        return n

    def scores_for_run(self, run_id: int) -> Sequence[int]:
        """Result ids a run produced, via the stage counters it recorded."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT counters_jsonb -> 'result_ids'
                      FROM {self._schema}.fundamental_run_stages
                     WHERE run_id = %s AND stage = %s AND status = 'succeeded'""",
                (run_id, STAGE_SCORING),
            )
            out: list[int] = []
            for (ids,) in cur.fetchall():
                if ids:
                    out.extend(int(i) for i in ids)
        return out
