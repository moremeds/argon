"""Typed event and deterministic-risk ledgers (migration 142)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

STATUS_LIVE = "live"
STATUS_KILLED = "killed"
STATUS_PROBATION = "probation"

SEVERITY_INFO = "info"
SEVERITY_WATCH = "watch"
SEVERITY_MATERIAL = "material"


class ResearchEventsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- discovery gate ----------------

    def register_classes(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Record the discovery verdict for each candidate class.

        `DO UPDATE`, unlike the ledgers below: a class's status is a current
        decision that can legitimately change when a source is added, and the
        rationale must move with it or the two disagree.
        """
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.research_event_classes
                        (event_class, status, source_table, rationale,
                         measured_rows, measured_on)
                 VALUES (%(c)s, %(s)s, %(t)s, %(r)s, %(n)s, %(d)s)
            ON CONFLICT (event_class) DO UPDATE
                    SET status = EXCLUDED.status,
                        source_table = EXCLUDED.source_table,
                        rationale = EXCLUDED.rationale,
                        measured_rows = EXCLUDED.measured_rows,
                        measured_on = EXCLUDED.measured_on
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    {
                        "c": r["event_class"],
                        "s": r["status"],
                        "t": r.get("source_table"),
                        "r": r["rationale"],
                        "n": r.get("measured_rows"),
                        "d": r.get("measured_on"),
                    }
                    for r in rows
                ],
            )
        self.conn.commit()
        return len(rows)

    def classes(self) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT event_class, status, source_table, rationale,
                           measured_rows, measured_on
                      FROM {self._schema}.research_event_classes
                     ORDER BY status, event_class"""
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def live_classes(self) -> set[str]:
        return {c["event_class"] for c in self.classes() if c["status"] == STATUS_LIVE}

    # ---------------- events ----------------

    def record_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert events. Returns how many were genuinely new.

        A class that is not `live` is REFUSED rather than silently accepted: an
        event in a killed class is exactly the fabrication the gate exists to
        prevent, and letting it through with a warning would defeat the ledger.
        """
        if not rows:
            return 0
        live = self.live_classes()
        bad = {r["event_class"] for r in rows} - live
        if bad:
            raise ValueError(
                f"event classes not live: {sorted(bad)}. A killed class has no "
                "ingested source; writing to it would fabricate the evidence the "
                "discovery gate refused."
            )
        sql = f"""
            INSERT INTO {self._schema}.research_events
                        (event_class, ticker, occurred_at, first_known_at,
                         title, detail_jsonb, source_kind, source_ref)
                 VALUES (%(cls)s, %(ticker)s, %(occ)s, %(known)s, %(title)s,
                         %(detail)s, %(kind)s, %(ref)s)
            ON CONFLICT (event_class, ticker, occurred_at, source_ref)
                 DO NOTHING
        """
        payload = [
            {
                "cls": r["event_class"],
                "ticker": r["ticker"].upper(),
                "occ": r["occurred_at"],
                "known": r.get("first_known_at") or r["occurred_at"],
                "title": r["title"],
                "detail": Jsonb(r.get("detail") or {}),
                "kind": r["source_kind"],
                "ref": r.get("source_ref"),
            }
            for r in rows
        ]
        before = self._count("research_events")
        with self.conn.cursor() as cur:
            cur.executemany(sql, payload)
        self.conn.commit()
        return self._count("research_events") - before

    def _count(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._schema}.{table}")
            return int(cur.fetchone()[0])

    def events_for(
        self,
        ticker: str,
        *,
        known_by: date | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Events for one name, optionally as they stood at `known_by`.

        Predicates on `first_known_at`, never on `occurred_at`: a replay that
        filtered on when things HAPPENED would see events before Argon could
        know them, which is the look-ahead migration 132 exists to prevent.
        """
        where = "ticker = %s"
        params: list[Any] = [ticker.upper()]
        if known_by is not None:
            where += " AND first_known_at <= %s"
            params.append(known_by)
        params.append(limit)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT event_id, event_class, occurred_at, first_known_at,
                           title, detail_jsonb, source_kind, source_ref,
                           superseded_by
                      FROM {self._schema}.research_events
                     WHERE {where}
                     ORDER BY first_known_at DESC, event_id DESC
                     LIMIT %s""",
                params,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def supersede(self, original_id: int, by_id: int) -> None:
        """Mark an event superseded. The predecessor stays readable."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {self._schema}.research_events
                       SET superseded_by = %s WHERE event_id = %s""",
                (by_id, original_id),
            )
        self.conn.commit()

    def class_counts(self) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT event_class, count(*)
                      FROM {self._schema}.research_events
                     GROUP BY event_class ORDER BY event_class"""
            )
            return {c: int(n) for c, n in cur.fetchall()}

    # ---------------- risk ----------------

    def record_risks(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.research_risk_facts
                        (ticker, risk_kind, observed_value, threshold, breached,
                         severity, statement, invalidates, source_kind,
                         detail_jsonb, as_of)
                 VALUES (%(ticker)s, %(kind)s, %(obs)s, %(thr)s, %(br)s,
                         %(sev)s, %(stmt)s, %(inval)s, %(src)s, %(detail)s,
                         %(as_of)s)
            ON CONFLICT (ticker, risk_kind, as_of) DO UPDATE
                    SET observed_value = EXCLUDED.observed_value,
                        breached = EXCLUDED.breached,
                        severity = EXCLUDED.severity,
                        statement = EXCLUDED.statement
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    {
                        "ticker": r["ticker"].upper(),
                        "kind": r["risk_kind"],
                        "obs": r.get("observed_value"),
                        "thr": r.get("threshold"),
                        "br": bool(r["breached"]),
                        "sev": r["severity"],
                        "stmt": r["statement"],
                        "inval": r.get("invalidates"),
                        "src": r["source_kind"],
                        "detail": Jsonb(r.get("detail") or {}),
                        "as_of": r["as_of"],
                    }
                    for r in rows
                ],
            )
        self.conn.commit()
        return len(rows)

    def risks_for(self, ticker: str, *, as_of: date | None = None) -> list[dict[str, Any]]:
        where = "ticker = %s"
        params: list[Any] = [ticker.upper()]
        if as_of is not None:
            where += " AND as_of <= %s"
            params.append(as_of)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (risk_kind)
                           risk_kind, observed_value, threshold, breached,
                           severity, statement, invalidates, source_kind, as_of
                      FROM {self._schema}.research_risk_facts
                     WHERE {where}
                     ORDER BY risk_kind, as_of DESC""",
                params,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def risk_summary(self) -> dict[str, dict[str, int]]:
        """Per risk kind: how many names were evaluated and how many breached.

        Grouped by KIND alone. Grouping by (kind, severity) and keying a dict on
        kind silently drops every group but the last, which made a breach rate
        read as 100% because the non-breached rows landed under `info` and were
        overwritten.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT risk_kind,
                           count(*) FILTER (WHERE breached)   AS breached,
                           count(*)                           AS evaluated,
                           count(*) FILTER (WHERE severity = 'material')
                                                              AS material
                      FROM {self._schema}.research_risk_facts
                     GROUP BY risk_kind ORDER BY risk_kind"""
            )
            return {
                kind: {
                    "breached": int(b),
                    "evaluated": int(n),
                    "material": int(m),
                }
                for kind, b, n, m in cur.fetchall()
            }
