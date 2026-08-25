"""Availability-evidence claims for statement content versions (migration 130).

Standalone repository, never a `Repository` mixin — new persistence domains get
their own module from method one (storage split rule, CLAUDE.md).

**Every writer here commits**, matching `FundamentalObsRepository`: the known
failure in this area is a research-layer refresh that ran, logged success and
never committed a row.

APPEND-ONLY IN PRACTICE, NOT JUST IN INTENT
-------------------------------------------
Every write is `ON CONFLICT (obs_id, claim_key) DO NOTHING`. There is no update
path in this module and no method that takes a claim id, so a replay of a rule
cannot revise what that rule previously concluded — it can only fail to add a
row. Stronger evidence arrives under a DIFFERENT `claim_key` and lands beside its
predecessor, which is what preserves the record of what Argon believed and when.

The corollary is a real constraint on callers: fixing a bad claim means writing a
new rule version (`…:v2`), not re-running the old one and expecting the value to
move. Migration 130 documents why that trade is worth making.

WHY THE SEEDING PATH IS ONE STATEMENT
-------------------------------------
`seed_claims` is `INSERT … SELECT` over a keyset page of observations, so a
90,000-row backfill costs one round-trip per page rather than one per row. The
page cursor is `obs_id`, never `OFFSET`: forward ingest keeps appending
observations while a backfill runs, and an offset walk over a growing table skips
rows silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from uw_scan.fundamentals.observation_time import (
    CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
    CLAIM_KEY_LEGACY_CURRENT_VINTAGE,
    SOURCE_ARGON_CAPTURE,
    SOURCE_ARGON_LEGACY,
    EvidenceClass,
    normalize_claim,
)

#: The two classes a rule can derive from rows Argon already holds, and the rule
#: identity each one writes under. `true_pit` is deliberately absent: it requires
#: a publication artifact, and no rule here can manufacture one. `unknown` is
#: absent because it asserts nothing — an observation with no claim already reads
#: as unknown to every policy, so writing the row buys nothing.
_SEEDABLE: dict[EvidenceClass, tuple[str, str, str]] = {
    # class: (claim_key, evidence_source, SQL expression for available_at)
    EvidenceClass.CAPTURE_BOUNDED: (
        CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
        SOURCE_ARGON_CAPTURE,
        "o.first_observed_at",
    ),
    EvidenceClass.CURRENT_VINTAGE: (
        CLAIM_KEY_LEGACY_CURRENT_VINTAGE,
        SOURCE_ARGON_LEGACY,
        "NULL::timestamptz",
    ),
}

#: Page size for the keyset walk. One page is one round-trip; 5,000 keeps the
#: statement's parameter count trivial while amortising the walk over a table
#: that is ~90k rows today.
PAGE = 5000


class FundamentalObsAvailabilityRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- writes ----------------

    def record_claims(self, claims: Sequence[dict[str, Any]]) -> int:
        """Insert explicit claims. Returns the number actually written.

        Every row is validated through `normalize_claim` BEFORE any SQL runs, so
        a batch carrying one malformed claim writes none of its valid siblings.
        A partially-applied batch that still returned a success count is exactly
        the shape of a backfill that reports coverage it does not have.
        """
        batch = list(claims)
        if not batch:
            return 0

        rows = []
        for claim in batch:
            cls, at = normalize_claim(
                claim["evidence_class"], claim.get("available_at")
            )
            rows.append(
                {
                    "obs_id": claim["obs_id"],
                    "claim_key": claim["claim_key"],
                    "evidence_class": cls.value,
                    "available_at": at,
                    "evidence_source": claim["evidence_source"],
                    "evidence_ref": claim.get("evidence_ref"),
                    "evidence_jsonb": Jsonb(claim.get("evidence_jsonb") or {}),
                }
            )

        sql = f"""
            INSERT INTO {self._schema}.fundamental_obs_availability
                        (obs_id, claim_key, evidence_class, available_at,
                         evidence_source, evidence_ref, evidence_jsonb)
                 VALUES (%(obs_id)s, %(claim_key)s, %(evidence_class)s,
                         %(available_at)s, %(evidence_source)s, %(evidence_ref)s,
                         %(evidence_jsonb)s)
            ON CONFLICT (obs_id, claim_key) DO NOTHING
        """
        before = self._count()
        with self.conn.cursor() as cur:
            cur.executemany(sql, rows)
        self.conn.commit()
        return self._count() - before

    def seed_claims(
        self,
        evidence_class: EvidenceClass | str,
        *,
        tickers: Sequence[str] | None = None,
        after_obs_id: int = 0,
        limit: int | None = None,
    ) -> tuple[int, int | None]:
        """Derive one page of claims from the observations themselves.

        Returns `(inserted, cursor)` where `cursor` is the highest `obs_id` in
        the page SCANNED — not the highest inserted. Resuming from the inserted
        maximum would re-walk every already-claimed row forever once the tail of
        a page is fully claimed. `cursor` is None when the page was empty, which
        is the loop's termination signal.
        """
        try:
            claim_key, source, at_expr = _SEEDABLE[EvidenceClass(evidence_class)]
        except KeyError as exc:
            raise ValueError(
                f"{evidence_class} cannot be derived from stored observations; "
                "it needs positive external evidence"
            ) from exc

        where = ["o.obs_id > %(after)s"]
        params: dict[str, Any] = {
            "after": after_obs_id,
            "limit": limit if limit is not None else PAGE,
            "claim_key": claim_key,
            "class": EvidenceClass(evidence_class).value,
            "source": source,
        }
        if tickers is not None:
            where.append("o.ticker = ANY(%(tickers)s)")
            params["tickers"] = list(tickers)

        sql = f"""
            WITH page AS (
                SELECT o.obs_id, {at_expr} AS available_at
                  FROM {self._schema}.fundamental_statement_obs o
                 WHERE {" AND ".join(where)}
                 ORDER BY o.obs_id
                 LIMIT %(limit)s
            ), ins AS (
                INSERT INTO {self._schema}.fundamental_obs_availability
                            (obs_id, claim_key, evidence_class, available_at,
                             evidence_source)
                     SELECT page.obs_id, %(claim_key)s, %(class)s,
                            page.available_at, %(source)s
                       FROM page
                ON CONFLICT (obs_id, claim_key) DO NOTHING
                  RETURNING 1
            )
            SELECT (SELECT count(*) FROM ins), (SELECT max(obs_id) FROM page)
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            inserted, cursor = cur.fetchone()
        self.conn.commit()
        return (int(inserted), cursor)

    # ---------------- reads ----------------

    def claims_for_obs_ids(
        self, obs_ids: Sequence[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Every claim for these observations, strongest class first."""
        if not obs_ids:
            return {}
        sql = f"""
            SELECT availability_id, obs_id, claim_key, evidence_class,
                   available_at, evidence_source, evidence_ref, evidence_jsonb
              FROM {self._schema}.fundamental_obs_availability
             WHERE obs_id = ANY(%s)
             ORDER BY obs_id, evidence_class, available_at
        """
        out: dict[int, list[dict[str, Any]]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, (list(obs_ids),))
            for row in cur.fetchall():
                out.setdefault(row[1], []).append(
                    {
                        "availability_id": row[0],
                        "obs_id": row[1],
                        "claim_key": row[2],
                        "evidence_class": EvidenceClass(row[3]),
                        "available_at": row[4],
                        "evidence_source": row[5],
                        "evidence_ref": row[6],
                        "evidence_jsonb": row[7],
                    }
                )
        return out

    def claim_counts(self) -> dict[EvidenceClass, int]:
        """Rows per evidence class. Absent classes are absent, not zero-filled —
        the audit reports what exists, and inventing a `true_pit: 0` row would
        read as a measured coverage figure rather than an untried rule."""
        sql = f"""
            SELECT evidence_class, count(*)
              FROM {self._schema}.fundamental_obs_availability
             GROUP BY evidence_class
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return {EvidenceClass(cls): int(n) for cls, n in cur.fetchall()}

    def unclaimed_observation_count(self) -> int:
        """Observations carrying no claim at all — they fail closed everywhere,
        so this is the number the backfill exists to drive to zero."""
        sql = f"""
            SELECT count(*)
              FROM {self._schema}.fundamental_statement_obs o
             WHERE NOT EXISTS (
                   SELECT 1 FROM {self._schema}.fundamental_obs_availability a
                    WHERE a.obs_id = o.obs_id)
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return int(cur.fetchone()[0])

    def coverage_audit(self) -> dict[str, Any]:
        """Every dimension the availability report needs, in four queries.

        Counts rather than rows: the artifact this feeds is a coverage report,
        and a per-row dump of ~90k observations would bury the one number that
        matters — how much of the panel can support a historical replay at all.
        """
        report: dict[str, Any] = {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT a.evidence_class, o.source, o.statement, o.period_type,
                       EXTRACT(YEAR FROM o.period_end)::int AS period_year,
                       count(*), count(DISTINCT o.ticker),
                       min(a.available_at), max(a.available_at)
                  FROM {self._schema}.fundamental_obs_availability a
                  JOIN {self._schema}.fundamental_statement_obs o
                    ON o.obs_id = a.obs_id
                 GROUP BY 1, 2, 3, 4, 5
                 ORDER BY 1, 2, 3, 4, 5
                """
            )
            report["by_class"] = [
                {
                    "evidence_class": r[0],
                    "source": r[1],
                    "statement": r[2],
                    "period_type": r[3],
                    "period_year": r[4],
                    "rows": r[5],
                    "tickers": r[6],
                    "earliest_available_at": r[7],
                    "latest_available_at": r[8],
                }
                for r in cur.fetchall()
            ]

            # Identities carrying more than one content version are the only ones
            # where selection order can differ between the two readers — the
            # population this whole contract exists for.
            cur.execute(
                f"""
                SELECT count(*), coalesce(sum(versions), 0)
                  FROM (SELECT count(*) AS versions
                          FROM {self._schema}.fundamental_statement_obs
                         GROUP BY source, ticker, period_end, period_type, statement
                        HAVING count(*) > 1) t
                """
            )
            identities, rows = cur.fetchone()
            report["multi_version_identities"] = int(identities)
            report["multi_version_rows"] = int(rows)

            cur.execute(
                f"SELECT count(*) FROM {self._schema}.fundamental_statement_obs"
            )
            report["observations"] = int(cur.fetchone()[0])

            # The self-check inputs: a true-PIT claim with no artifact reference,
            # and any observation the backfill never classified.
            cur.execute(
                f"""
                SELECT count(*) FILTER (
                           WHERE evidence_class = 'true_pit'
                             AND (evidence_ref IS NULL OR available_at IS NULL)),
                       count(*) FILTER (
                           WHERE evidence_class IN ('current_vintage', 'unknown')
                             AND available_at IS NOT NULL),
                       count(*)
                  FROM {self._schema}.fundamental_obs_availability
                """
            )
            unsupported, mistimed, total = cur.fetchone()
            report["true_pit_without_evidence"] = int(unsupported)
            report["untimed_claims_carrying_an_instant"] = int(mistimed)
            report["claims"] = int(total)

        report["by_evidence_class"] = {
            cls.value: n for cls, n in self.claim_counts().items()
        }
        report["unclaimed_observations"] = self.unclaimed_observation_count()
        return report

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM {self._schema}.fundamental_obs_availability"
            )
            return int(cur.fetchone()[0])

    def true_pit_obs_ids(self, obs_ids: Sequence[int]) -> set[int]:
        """Which of these observations carry a `true_pit` claim.

        Exists so a CURRENT-vintage run can still report honest evidence coverage.
        Deriving it from the run's own `availability_ids` would read 0 for every
        current-vintage row — not because the evidence is absent but because that
        run never consulted it, which is an artifact reported as a measurement.
        """
        if not obs_ids:
            return set()
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT obs_id
                      FROM {self._schema}.fundamental_obs_availability
                     WHERE obs_id = ANY(%s) AND evidence_class = 'true_pit'""",
                (list(obs_ids),),
            )
            return {int(r[0]) for r in cur.fetchall()}
