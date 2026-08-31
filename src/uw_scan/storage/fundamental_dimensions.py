"""Persisted research-priority dimensions (migration 138). Standalone repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class FundamentalDimensionsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def record(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert dimension rows. Returns how many were genuinely new."""
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.fundamental_dimensions
                        (result_id, ticker, as_of, engine_version, dimension,
                         value, inputs_present, inputs_expected, authority,
                         detail_jsonb)
                 VALUES (%(result_id)s, %(ticker)s, %(as_of)s, %(engine_version)s,
                         %(dimension)s, %(value)s, %(inputs_present)s,
                         %(inputs_expected)s, %(authority)s, %(detail_jsonb)s)
            ON CONFLICT (result_id, dimension) DO NOTHING
        """
        payload = [
            {
                "result_id": r["result_id"],
                "ticker": r["ticker"],
                "as_of": r["as_of"],
                "engine_version": r["engine_version"],
                "dimension": r["dimension"],
                "value": r.get("value"),
                "inputs_present": r.get("inputs_present", 0),
                "inputs_expected": r.get("inputs_expected", 0),
                "authority": r["authority"],
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
                f"SELECT count(*) FROM {self._schema}.fundamental_dimensions"
            )
            return int(cur.fetchone()[0])

    def for_ticker(
        self, ticker: str, *, engine_version: str, as_of: date | None = None
    ) -> dict[str, Any]:
        """The newest (or as-of) dimension set for one name, keyed by dimension.

        Returns `{}` rather than a zero-filled skeleton when nothing was
        computed. A caller must be able to tell "no dimensions" from "all
        dimensions at zero".
        """
        where = "ticker = %s AND engine_version = %s"
        params: list[Any] = [ticker.upper(), engine_version]
        if as_of is not None:
            where += " AND as_of <= %s"
            params.append(as_of)
        sql = f"""
            SELECT DISTINCT ON (dimension)
                   dimension, value, inputs_present, inputs_expected,
                   authority, detail_jsonb, as_of, result_id
              FROM {self._schema}.fundamental_dimensions
             WHERE {where}
             ORDER BY dimension, as_of DESC
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return {
                r[0]: dict(zip(cols, r, strict=True)) for r in cur.fetchall()
            }

    def authority_audit(self, engine_version: str) -> dict[str, dict[str, int]]:
        """dimension -> {authority: count}. The gate a reviewer reads.

        One dimension appearing under two authorities means something wrote a
        permission the module does not declare, which is the failure this audit
        exists to surface.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT dimension, authority, count(*)
                      FROM {self._schema}.fundamental_dimensions
                     WHERE engine_version = %s
                     GROUP BY dimension, authority
                     ORDER BY dimension""",
                (engine_version,),
            )
            out: dict[str, dict[str, int]] = {}
            for dim, auth, n in cur.fetchall():
                out.setdefault(dim, {})[auth] = int(n)
        return out

    def coverage(self, engine_version: str) -> dict[str, dict[str, Any]]:
        """Per dimension: how often it was computable at all."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT dimension,
                           count(*),
                           count(value),
                           avg(inputs_present::float / nullif(inputs_expected, 0))
                      FROM {self._schema}.fundamental_dimensions
                     WHERE engine_version = %s
                     GROUP BY dimension
                     ORDER BY dimension""",
                (engine_version,),
            )
            return {
                dim: {
                    "rows": int(n),
                    "with_value": int(v),
                    "mean_input_share": float(share) if share is not None else None,
                }
                for dim, n, v, share in cur.fetchall()
            }
