"""Versioned research reports (migration 143). Standalone repository."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

STATUS_DRAFT = "draft"
STATUS_PARTIAL = "partial"
STATUS_PUBLISHED = "published"
STATUS_SUPERSEDED = "superseded"
STATUS_STALE = "stale"


def content_hash(blocks: Sequence[Mapping[str, Any]]) -> str:
    """Hash of assembled blocks, stable across runs.

    Sorted keys and a canonical separator so two assemblies of the same content
    hash identically regardless of dict ordering — otherwise the replay gate
    would fail on Python's insertion order rather than on a real difference.
    """
    payload = [
        {
            "ordinal": b["ordinal"],
            "block_kind": b["block_kind"],
            "title": b["title"],
            "payload": b.get("payload") or {},
            "evidence": b.get("evidence") or {},
            "derivation": b.get("derivation"),
            "authority": b.get("authority"),
        }
        for b in sorted(blocks, key=lambda b: b["ordinal"])
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class ResearchReportsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def publish(
        self,
        *,
        report_key: str,
        report_type: str,
        title: str,
        manifest: Mapping[str, Any],
        blocks: Sequence[Mapping[str, Any]],
        status: str = STATUS_PUBLISHED,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        """Publish the next version. Never rewrites a predecessor.

        Returns the new report plus `changed`, which is False when the content
        hash matches the previous version — a refresh that found nothing new
        should say so rather than manufacture a version whose delta is empty.
        """
        chash = content_hash(blocks)
        previous = self.latest(report_key)
        if previous is not None and previous["content_hash"] == chash:
            return {**previous, "changed": False}

        version_no = (previous["version_no"] + 1) if previous else 1
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.research_reports
                            (report_key, report_type, version_no, title,
                             manifest_jsonb, content_hash, status, run_id)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                  RETURNING report_id""",
                (
                    report_key,
                    report_type,
                    version_no,
                    title,
                    Jsonb(dict(manifest)),
                    chash,
                    status,
                    run_id,
                ),
            )
            report_id = int(cur.fetchone()[0])
            cur.executemany(
                f"""INSERT INTO {self._schema}.research_report_blocks
                            (report_id, ordinal, block_kind, title,
                             payload_jsonb, evidence_jsonb, derivation,
                             authority)
                     VALUES (%(r)s, %(o)s, %(k)s, %(t)s, %(p)s, %(e)s, %(d)s,
                             %(a)s)""",
                [
                    {
                        "r": report_id,
                        "o": b["ordinal"],
                        "k": b["block_kind"],
                        "t": b["title"],
                        "p": Jsonb(b.get("payload") or {}),
                        "e": Jsonb(b.get("evidence") or {}),
                        "d": b.get("derivation"),
                        "a": b.get("authority"),
                    }
                    for b in blocks
                ],
            )
            if previous is not None:
                # Supersede, never delete. The predecessor is what a delta is
                # computed against and what a citation of the old report resolves
                # to.
                cur.execute(
                    f"""UPDATE {self._schema}.research_reports
                           SET status = %s, superseded_by = %s
                         WHERE report_id = %s""",
                    (STATUS_SUPERSEDED, report_id, previous["report_id"]),
                )
        self.conn.commit()
        return {**self.get(report_id), "changed": True}

    def latest(self, report_key: str) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT report_id FROM {self._schema}.research_reports
                     WHERE report_key = %s
                     ORDER BY version_no DESC LIMIT 1""",
                (report_key,),
            )
            row = cur.fetchone()
        return self.get(int(row[0])) if row else None

    def get(self, report_id: int) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT report_id, report_key, report_type, version_no, title,
                           manifest_jsonb, content_hash, status, run_id,
                           superseded_by, created_at
                      FROM {self._schema}.research_reports
                     WHERE report_id = %s""",
                (report_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            report = dict(zip(cols, row, strict=True))
        report["blocks"] = self.blocks(report_id)
        return report

    def version(self, report_key: str, version_no: int) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT report_id FROM {self._schema}.research_reports
                     WHERE report_key = %s AND version_no = %s""",
                (report_key, version_no),
            )
            row = cur.fetchone()
        return self.get(int(row[0])) if row else None

    def blocks(self, report_id: int) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ordinal, block_kind, title, payload_jsonb,
                           evidence_jsonb, derivation, authority
                      FROM {self._schema}.research_report_blocks
                     WHERE report_id = %s ORDER BY ordinal""",
                (report_id,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def versions(self, report_key: str) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT report_id, version_no, content_hash, status, created_at
                      FROM {self._schema}.research_reports
                     WHERE report_key = %s ORDER BY version_no DESC""",
                (report_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (report_key)
                           report_id, report_key, report_type, version_no, title,
                           status, created_at
                      FROM {self._schema}.research_reports
                     ORDER BY report_key, version_no DESC""",
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:limit]
