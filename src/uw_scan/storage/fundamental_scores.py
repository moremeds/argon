"""Method versioning and stage-2 score outputs (migration 115).

Standalone repository. **Every writer commits** — same reason as
`fundamental_obs.py`: the known failure in this area is a refresh that ran,
logged success and persisted nothing.

Results are IMMUTABLE. `(ticker, as_of, engine_version, inputs_hash)` is the
identity, and a re-run producing the same four values is the same result — so the
write is `DO NOTHING`, never `DO UPDATE`. If any of the four differ it is a
genuinely different computation and gets its own row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from uw_scan.fundamentals.features import FEATURES


class FundamentalScoresRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- method versioning ----------------

    def register_version(
        self,
        *,
        engine_version: str,
        code_version: str,
        param_hash: str,
        params: Mapping[str, float],
        note: str | None = None,
    ) -> None:
        """Insert a version and its immutable parameter rows. Idempotent.

        Parameters are `DO NOTHING` on conflict rather than `DO UPDATE`: editing a
        parameter under a live version would silently reinterpret every score
        already computed under it. Retuning means a NEW version.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.fundamental_method_versions
                           (engine_version, code_version, param_hash, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (engine_version) DO NOTHING""",
                (engine_version, code_version, param_hash, note),
            )
            cur.executemany(
                f"""INSERT INTO {self._schema}.fundamental_method_params
                           (engine_version, param_key, param_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (engine_version, param_key) DO NOTHING""",
                [(engine_version, k, float(v)) for k, v in params.items()],
            )
        self.conn.commit()

    def activate(self, engine_version: str) -> None:
        """Point the singleton at a version. One atomic UPDATE, or an insert on
        first use — never a DELETE, which the migration's trigger forbids."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.fundamental_method_state
                           (singleton_id, active_engine_version)
                    VALUES (1, %s)
                    ON CONFLICT (singleton_id) DO UPDATE
                        SET active_engine_version = EXCLUDED.active_engine_version,
                            activated_at = now()""",
                (engine_version,),
            )
        self.conn.commit()

    def active_version(self) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT active_engine_version FROM {self._schema}.fundamental_method_state"
            )
            row = cur.fetchone()
            return row[0] if row else None

    def params(self, engine_version: str) -> dict[str, float]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT param_key, param_value
                      FROM {self._schema}.fundamental_method_params
                     WHERE engine_version = %s""",
                (engine_version,),
            )
            return {k: float(v) for k, v in cur.fetchall()}

    # ---------------- scores ----------------

    def insert_scores(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert immutable score rows. Returns how many were genuinely new."""
        if not rows:
            return 0
        cols = (
            [
                "ticker",
                "as_of",
                "engine_version",
                "inputs_hash",
                "period_end",
                "knowledge_date",
                "filing_date_known",
                "composite",
            ]
            + FEATURES
            + ["features_present", "source_obs_ids"]
        )
        placeholders = ", ".join(f"%({c})s" for c in cols)
        sql = f"""
            INSERT INTO {self._schema}.fundamental_scores ({", ".join(cols)})
                 VALUES ({placeholders})
            ON CONFLICT (ticker, as_of, engine_version, inputs_hash) DO NOTHING
        """
        before = self._count()
        with self.conn.cursor() as cur:
            cur.executemany(sql, [{c: r.get(c) for c in cols} for r in rows])
        self.conn.commit()
        return self._count() - before

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._schema}.fundamental_scores")
            return int(cur.fetchone()[0])

    def latest_for_ticker(
        self, ticker: str, engine_version: str | None = None
    ) -> dict[str, Any] | None:
        """Newest score for one name under the active (or given) version."""
        engine = engine_version or self.active_version()
        if engine is None:
            return None
        cols = [
            "as_of",
            "period_end",
            "knowledge_date",
            "filing_date_known",
            "composite",
            *FEATURES,
            "features_present",
            "inputs_hash",
            # The card joins these into `violated_fields` to decide which
            # subscores it is entitled to render.
            "source_obs_ids",
        ]
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {", ".join(cols)}
                      FROM {self._schema}.fundamental_scores
                     WHERE ticker = %s AND engine_version = %s
                     ORDER BY as_of DESC, computed_at DESC
                     LIMIT 1""",
                (ticker, engine),
            )
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

    def ranking(
        self, as_of_max: Any = None, engine_version: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Latest composite per ticker, ordered.

        **A sort key, not an expected return.** Valid only across the wide tier
        (spec §4.3) — the cost study measured zero gross alpha at every slice, so
        no caller may present this ordering as a return estimate.
        """
        engine = engine_version or self.active_version()
        if engine is None:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (ticker)
                           ticker, as_of, composite, features_present
                      FROM {self._schema}.fundamental_scores
                     WHERE engine_version = %s
                       AND (%s::date IS NULL OR as_of <= %s::date)
                     ORDER BY ticker, as_of DESC, computed_at DESC""",
                (engine, as_of_max, as_of_max),
            )
            rows = [
                {
                    "ticker": r[0],
                    "as_of": r[1],
                    "composite": None if r[2] is None else float(r[2]),
                    "features_present": r[3],
                }
                for r in cur.fetchall()
            ]
        rows.sort(key=lambda r: (r["composite"] is None, -(r["composite"] or 0.0)))
        return rows[:limit]
