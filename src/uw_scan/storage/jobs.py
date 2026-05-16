"""Rescan jobs queue: enqueue/claim/requeue/mark + summary.

Owns the claim-token race-protection logic from the 2026-05-16 review (B1).
mark_job_done and mark_job_failed gate UPDATE on (id, claim_token) so a
worker whose token was cleared by requeue_stale_running_jobs can't clobber
a fresh claim from a different worker."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import psycopg

from .rows import JobRow, RescanQueueSummaryRow

logger = logging.getLogger(__name__)


class _JobsMixin:
    _conn: psycopg.Connection
    _schema: str

    def enqueue_rescan_job(self, ticker: str, *, priority: int = 0) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.jobs (ticker, status, priority)
                VALUES (%s, 'queued', %s)
                ON CONFLICT (ticker) WHERE status IN ('queued', 'running')
                DO UPDATE SET
                    priority = GREATEST(
                        {self._schema}.jobs.priority,
                        EXCLUDED.priority
                    ),
                    requested_at = EXCLUDED.requested_at
                RETURNING id
                """,
                (ticker, priority),
            )
            row = cur.fetchone()
            assert row is not None
            job_id = row[0]
        self._conn.commit()
        return str(job_id)

    def claim_next_queued_job(self) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='running',
                    started_at=NOW(),
                    claim_token=gen_random_uuid()
                WHERE id = (
                  SELECT id FROM {self._schema}.jobs
                  WHERE status='queued'
                  ORDER BY priority DESC, requested_at ASC, id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error,
                          requested_at, started_at, finished_at, claim_token
                """
            )
            row = cur.fetchone()
        self._conn.commit()
        return JobRow(*row) if row else None

    def requeue_stale_running_jobs(self, older_than: timedelta) -> int:
        # Clear claim_token so the original worker's stored token will not
        # match anything if/when it tries mark_job_done later (review
        # 2026-05-16, B1; claim-token approach per codex review).
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='queued',
                    started_at=NULL,
                    error=NULL,
                    claim_token=NULL
                WHERE status='running'
                  AND started_at < NOW() - %s
                """,
                (older_than,),
            )
            count = cur.rowcount
        self._conn.commit()
        return count

    def mark_job_done(self, job_id: str, run_id: int, claim_token: Any) -> None:
        # Claim-token guard against the requeue race (review 2026-05-16, B1):
        # if requeue_stale_running_jobs cleared our token, or another worker
        # has since reclaimed (with a fresh token), our update must be rejected.
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='done', run_id=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (run_id, job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_done lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()

    def mark_job_failed(self, job_id: str, error: str, claim_token: Any) -> None:
        # Claim-token guard (review 2026-05-16, B1).
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='failed', error=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (error[:2000], job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_failed lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()

    def get_rescan_queue_summary(self) -> RescanQueueSummaryRow:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  count(*) FILTER (WHERE status IN ('queued', 'running')) AS total,
                  count(*) FILTER (WHERE status = 'queued') AS queued,
                  count(*) FILTER (WHERE status = 'running') AS running,
                  min(requested_at) FILTER (
                    WHERE status IN ('queued', 'running')
                  ) AS oldest_requested_at
                FROM {self._schema}.jobs
                """
            )
            row = cur.fetchone()
        assert row is not None
        return RescanQueueSummaryRow(
            total=row[0],
            queued=row[1],
            running=row[2],
            oldest_requested_at=row[3],
        )

    def get_job(self, job_id: str) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, status, run_id, error,
                       requested_at, started_at, finished_at, claim_token
                FROM {self._schema}.jobs WHERE id=%s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return JobRow(*row) if row else None
