"""Read queries behind the Research Radar router (``api/routers/radar.py``).

Standalone repository. Every method is a read over tables other repositories
write (``fundamental_statement_obs``, ``fundamental_universe``,
``fundamental_dimensions``, ``fundamental_company_type``, ``research_chains``,
``chain_membership``, ``company_exposure``). The rows come back as the raw
tuples the router shapes into its response models.
"""

from __future__ import annotations

from typing import Any

import psycopg


class ResearchRadarRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def has_statements(self, ticker: str) -> bool:
        """Whether Argon holds any statement observation for this name."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT 1 FROM {self._schema}.fundamental_statement_obs
                 WHERE ticker = %s LIMIT 1""",
                (ticker.upper(),),
            )
            return cur.fetchone() is not None

    def tier_size(self, tier: str) -> int:
        """Names currently in a fundamental-universe tier."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT count(*) FROM {self._schema}.fundamental_universe
                 WHERE tier = %s AND removed_at IS NULL""",
                (tier,),
            )
            return int(cur.fetchone()[0])

    def latest_tier_dimensions(
        self, tier: str, engine_version: str
    ) -> list[tuple[Any, ...]]:
        """Newest as_of per (ticker, dimension) under an engine, for one tier.

        Rows: (ticker, dimension, value, inputs_present, inputs_expected,
        authority, detail_jsonb, as_of, company_type), ordered by ticker then
        dimension.
        """
        with self.conn.cursor() as cur:
            # DISTINCT ON rather than a window function: one index scan, and
            # the ordering is the same one the index already provides.
            cur.execute(
                f"""
            SELECT DISTINCT ON (d.ticker, d.dimension)
                   d.ticker, d.dimension, d.value, d.inputs_present,
                   d.inputs_expected, d.authority, d.detail_jsonb, d.as_of,
                   t.company_type
              FROM {self._schema}.fundamental_dimensions d
              JOIN {self._schema}.fundamental_universe u
                ON u.ticker = d.ticker AND u.tier = %s AND u.removed_at IS NULL
              LEFT JOIN {self._schema}.fundamental_company_type t ON t.ticker = d.ticker
             WHERE d.engine_version = %s
             ORDER BY d.ticker, d.dimension, d.as_of DESC
            """,
                (tier, engine_version),
            )
            return cur.fetchall()

    def chain_matrix_cells(
        self, engine_version: str | None, taxonomy_version: str, domain: str | None
    ) -> list[tuple[Any, ...]]:
        """chain x layer member counts and the mean newest `priority`.

        Rows: (domain, chain, layer, layer_rank, members, with_result,
        priority_mean, with_magnitude), ordered by domain, chain, layer_rank,
        layer.
        """
        params: list[object] = [engine_version, taxonomy_version]
        domain_clause = ""
        if domain:
            domain_clause = " AND c.domain = %s"
            params.append(domain)

        with self.conn.cursor() as cur:
            cur.execute(
                f"""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, value
                  FROM {self._schema}.fundamental_dimensions
                 WHERE engine_version = %s AND dimension = 'priority'
                 ORDER BY ticker, as_of DESC
            )
            SELECT c.domain, c.chain, c.layer, c.layer_rank,
                   count(m.membership_id)                              AS members,
                   count(l.ticker)                                     AS with_result,
                   avg(l.value)                                        AS priority_mean,
                   count(DISTINCT e.ticker) FILTER
                        (WHERE e.magnitude IS NOT NULL)                AS with_magnitude
              FROM {self._schema}.research_chains c
              LEFT JOIN {self._schema}.chain_membership m
                     ON m.taxonomy_version = c.taxonomy_version
                    AND m.chain = c.chain AND m.layer = c.layer
                    AND m.valid_to IS NULL
              LEFT JOIN latest l ON l.ticker = m.ticker
              LEFT JOIN {self._schema}.company_exposure e
                     ON e.taxonomy_version = m.taxonomy_version
                    AND e.chain = m.chain AND e.ticker = m.ticker
                    AND e.valid_to IS NULL
             WHERE c.taxonomy_version = %s{domain_clause}
             GROUP BY c.domain, c.chain, c.layer, c.layer_rank
             ORDER BY c.domain, c.chain, c.layer_rank, c.layer
            """,
                params,
            )
            return cur.fetchall()

    def chain_member_rows(
        self,
        engine_version: str | None,
        taxonomy_version: str,
        chain: str,
        layer: str | None,
    ) -> list[tuple[Any, ...]]:
        """Open members of one chain (optionally one layer) with their exposure.

        Rows: (ticker, layer, evidence_class, approved_by, role, direction,
        magnitude, magnitude_basis, status, source_ref, priority), ordered by
        layer then ticker.
        """
        where = "m.taxonomy_version = %s AND m.chain = %s AND m.valid_to IS NULL"
        params: list[object] = [engine_version, taxonomy_version, chain]
        if layer:
            where += " AND m.layer = %s"
            params.append(layer)

        with self.conn.cursor() as cur:
            cur.execute(
                f"""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, value
                  FROM {self._schema}.fundamental_dimensions
                 WHERE engine_version = %s AND dimension = 'priority'
                 ORDER BY ticker, as_of DESC
            )
            SELECT m.ticker, m.layer, m.evidence_class, m.approved_by,
                   e.role, e.direction, e.magnitude, e.magnitude_basis,
                   e.status, e.source_ref, l.value
              FROM {self._schema}.chain_membership m
              LEFT JOIN {self._schema}.company_exposure e
                     ON e.taxonomy_version = m.taxonomy_version
                    AND e.chain = m.chain AND e.ticker = m.ticker
                    AND e.valid_to IS NULL
              LEFT JOIN latest l ON l.ticker = m.ticker
             WHERE {where}
             ORDER BY m.layer, m.ticker
            """,
                params,
            )
            return cur.fetchall()
