"""Versioned research taxonomy and company exposure (migrations 139/140).

Two tables, one owner, because they are the same research object seen twice:
`chain_membership` says a company BELONGS to a chain, `company_exposure` says how
much of it is economically THERE. Keeping them in one repository makes it hard to
read one while forgetting the other exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

EVIDENCE_DISCLOSED = "disclosed"
EVIDENCE_ANALYST = "analyst"
EVIDENCE_MIRRORED = "mirrored"
EVIDENCE_INFERRED = "inferred"

ROLES = (
    "supplier",
    "manufacturer",
    "component",
    "integrator",
    "customer",
    "beneficiary",
    "competitor",
    "other",
)

#: Bases that CAN carry a number. Mirrors the CHECK in migration 140 — kept in
#: sync deliberately so a caller gets a sentence before the database gets a
#: constraint violation.
EVIDENCED_BASES = frozenset(
    {
        "disclosed_revenue",
        "segment_share",
        "geographic_share",
        "customer_concentration",
        "capacity",
        "capex",
    }
)


class ResearchTaxonomyRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- versions ----------------

    def publish_version(
        self, version: str, *, note: str | None = None, activate: bool = False
    ) -> None:
        """Register a taxonomy version. Activating one deactivates the rest."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.research_taxonomy_versions
                            (taxonomy_version, note)
                     VALUES (%s, %s)
                ON CONFLICT (taxonomy_version) DO UPDATE SET note = EXCLUDED.note""",
                (version, note),
            )
            if activate:
                # One statement, not two: a gap between deactivate and activate
                # is a window where an unqualified read returns nothing.
                cur.execute(
                    f"""UPDATE {self._schema}.research_taxonomy_versions
                           SET is_active = (taxonomy_version = %s)""",
                    (version,),
                )
        self.conn.commit()

    def active_version(self) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT taxonomy_version
                      FROM {self._schema}.research_taxonomy_versions
                     WHERE is_active"""
            )
            row = cur.fetchone()
            return row[0] if row else None

    # ---------------- chains ----------------

    def define_chains(
        self, version: str, rows: Sequence[Mapping[str, Any]]
    ) -> int:
        """Upsert the layer catalogue for a version. Idempotent."""
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.research_chains
                        (taxonomy_version, domain, chain, layer, layer_rank,
                         description)
                 VALUES (%(v)s, %(domain)s, %(chain)s, %(layer)s, %(rank)s,
                         %(description)s)
            ON CONFLICT (taxonomy_version, chain, layer) DO UPDATE
                    SET domain = EXCLUDED.domain,
                        layer_rank = EXCLUDED.layer_rank,
                        description = EXCLUDED.description
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    {
                        "v": version,
                        "domain": r["domain"],
                        "chain": r["chain"],
                        "layer": r["layer"],
                        "rank": r.get("layer_rank", 0),
                        "description": r.get("description"),
                    }
                    for r in rows
                ],
            )
        self.conn.commit()
        return len(rows)

    def chains(self, version: str, domain: str | None = None) -> list[dict[str, Any]]:
        where = "taxonomy_version = %s"
        params: list[Any] = [version]
        if domain:
            where += " AND domain = %s"
            params.append(domain)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT domain, chain, layer, layer_rank, description
                      FROM {self._schema}.research_chains
                     WHERE {where}
                     ORDER BY domain, chain, layer_rank, layer""",
                params,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---------------- membership ----------------

    def add_membership(
        self,
        version: str,
        *,
        chain: str,
        layer: str,
        ticker: str,
        evidence_class: str,
        approved_by: str,
        note: str | None = None,
    ) -> bool:
        """Open a membership interval. Returns whether one was opened.

        A name already openly a member of this exact (chain, layer) is a no-op,
        so a reseed does not manufacture a history of identical intervals.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT 1 FROM {self._schema}.chain_membership
                     WHERE taxonomy_version = %s AND chain = %s AND layer = %s
                       AND ticker = %s AND valid_to IS NULL""",
                (version, chain, layer, ticker.upper()),
            )
            if cur.fetchone():
                return False
            cur.execute(
                f"""INSERT INTO {self._schema}.chain_membership
                            (taxonomy_version, chain, layer, ticker,
                             evidence_class, approved_by, note)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (version, chain, layer, ticker.upper(), evidence_class,
                 approved_by, note),
            )
        self.conn.commit()
        return True

    def members(
        self, version: str, chain: str, layer: str | None = None
    ) -> list[dict[str, Any]]:
        where = "taxonomy_version = %s AND chain = %s AND valid_to IS NULL"
        params: list[Any] = [version, chain]
        if layer:
            where += " AND layer = %s"
            params.append(layer)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, layer, evidence_class, approved_by, note,
                           valid_from
                      FROM {self._schema}.chain_membership
                     WHERE {where}
                     ORDER BY layer, ticker""",
                params,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def membership_matrix(self, version: str) -> list[dict[str, Any]]:
        """chain x layer with its member count — the matrix's own denominator."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT c.domain, c.chain, c.layer, c.layer_rank,
                           count(m.membership_id) AS members
                      FROM {self._schema}.research_chains c
                      LEFT JOIN {self._schema}.chain_membership m
                             ON m.taxonomy_version = c.taxonomy_version
                            AND m.chain = c.chain AND m.layer = c.layer
                            AND m.valid_to IS NULL
                     WHERE c.taxonomy_version = %s
                     GROUP BY c.domain, c.chain, c.layer, c.layer_rank
                     ORDER BY c.domain, c.chain, c.layer_rank, c.layer""",
                (version,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---------------- exposure ----------------

    def record_exposure(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert exposures. Raises before SQL on a magnitude with no evidence.

        The database enforces this too. Checking here as well buys the caller a
        sentence naming the offending row instead of a constraint name, which
        matters because the mistake is easy to make and its symptom is invisible.
        """
        if not rows:
            return 0
        for r in rows:
            if r.get("magnitude") is None:
                continue
            if r.get("status") != "disclosed" or r["magnitude_basis"] not in (
                EVIDENCED_BASES
            ):
                raise ValueError(
                    f"{r['ticker']}/{r['chain']}: a magnitude requires "
                    f"status='disclosed' and an evidenced magnitude_basis; got "
                    f"status={r.get('status')!r} basis={r['magnitude_basis']!r}. "
                    "An asserted exposure may name a role, not a number."
                )
        sql = f"""
            INSERT INTO {self._schema}.company_exposure
                        (taxonomy_version, ticker, chain, role, direction,
                         counterparty, magnitude, magnitude_basis, confidence,
                         status, source_kind, source_ref, source_obs_id, note)
                 VALUES (%(v)s, %(ticker)s, %(chain)s, %(role)s, %(direction)s,
                         %(counterparty)s, %(magnitude)s, %(magnitude_basis)s,
                         %(confidence)s, %(status)s, %(source_kind)s,
                         %(source_ref)s, %(source_obs_id)s, %(note)s)
            ON CONFLICT DO NOTHING
        """
        payload = [
            {
                "v": r["taxonomy_version"],
                "ticker": r["ticker"].upper(),
                "chain": r["chain"],
                "role": r["role"],
                "direction": r.get("direction"),
                "counterparty": r.get("counterparty"),
                "magnitude": r.get("magnitude"),
                "magnitude_basis": r["magnitude_basis"],
                "confidence": r.get("confidence", "low"),
                "status": r["status"],
                "source_kind": r["source_kind"],
                "source_ref": r.get("source_ref"),
                "source_obs_id": r.get("source_obs_id"),
                "note": r.get("note"),
            }
            for r in rows
        ]
        before = self._exposure_count()
        with self.conn.cursor() as cur:
            cur.executemany(sql, payload)
        self.conn.commit()
        return self._exposure_count() - before

    def _exposure_count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._schema}.company_exposure")
            return int(cur.fetchone()[0])

    def exposures(
        self, version: str, *, chain: str | None = None, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        where = "taxonomy_version = %s AND valid_to IS NULL"
        params: list[Any] = [version]
        if chain:
            where += " AND chain = %s"
            params.append(chain)
        if ticker:
            where += " AND ticker = %s"
            params.append(ticker.upper())
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, chain, role, direction, counterparty,
                           magnitude, magnitude_basis, confidence, status,
                           source_kind, source_ref, source_obs_id, note
                      FROM {self._schema}.company_exposure
                     WHERE {where}
                     ORDER BY chain, ticker, role""",
                params,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def exposure_coverage(self, version: str) -> dict[str, dict[str, int]]:
        """Per chain: members, how many carry an exposure, how many carry a NUMBER.

        Three denominators, because they answer three different questions and a
        surface that shows only the first invites the reader to assume the third.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.chain,
                       count(DISTINCT m.ticker)                       AS members,
                       count(DISTINCT e.ticker)                       AS with_exposure,
                       count(DISTINCT e.ticker) FILTER
                             (WHERE e.magnitude IS NOT NULL)          AS with_magnitude
                  FROM {self._schema}.chain_membership m
                  LEFT JOIN {self._schema}.company_exposure e
                         ON e.taxonomy_version = m.taxonomy_version
                        AND e.chain = m.chain AND e.ticker = m.ticker
                        AND e.valid_to IS NULL
                 WHERE m.taxonomy_version = %s AND m.valid_to IS NULL
                 GROUP BY m.chain
                 ORDER BY m.chain
                """,
                (version,),
            )
            return {
                chain: {
                    "members": int(n),
                    "with_exposure": int(e),
                    "with_magnitude": int(mag),
                }
                for chain, n, e, mag in cur.fetchall()
            }
