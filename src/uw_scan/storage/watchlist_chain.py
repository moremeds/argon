"""Many-to-many watchlist chain membership (`uw_scan.watchlist_chain`, migration 113).

Standalone repository rather than a Repository mixin — new persistence domains get
their own module from method one (storage split rule in CLAUDE.md).

Two membership sources share the table and must not clobber each other:

- `taxonomy` — enumerated in `uw_scan.watchlist_taxonomy`. Re-seeding replaces
  these wholesale, because the module is the source of truth for them.
- `sector` — inherited from the legacy `watchlist.sector` value so that every
  ticker is reachable by at least one chain even if the taxonomy never names it.
  A ticker on the watchlist that no chain lists would be scanned (costing UW
  budget) while being invisible to every filter, which is the worst of both.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import psycopg


class WatchlistChainRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    def replace_taxonomy_memberships(self, rows: Sequence[tuple[str, str, str]]) -> int:
        """Replace all source='taxonomy' rows with `rows` — (ticker, layer, chain).

        Delete-then-insert scoped to source='taxonomy' so inherited sector rows
        survive. A plain upsert would leave orphans behind when a ticker is
        removed from a chain in the module, and those orphans are invisible —
        the filter would keep returning a ticker the taxonomy no longer lists.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.watchlist_chain WHERE source = 'taxonomy'"
            )
            if not rows:
                return 0
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.watchlist_chain (ticker, layer, chain, source)
                VALUES (%s, %s, %s, 'taxonomy')
                ON CONFLICT (ticker, chain) DO UPDATE SET layer = EXCLUDED.layer,
                                                          source = 'taxonomy'
                """,
                [(t.upper(), layer, chain) for t, layer, chain in rows],
            )
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(rows)

    def inherit_sector_memberships(self, layer_for_chain: dict[str, str]) -> int:
        """Give every active ticker a membership for its own `watchlist.sector`.

        Only fills gaps: `ON CONFLICT DO NOTHING` means a chain already asserted
        by the taxonomy keeps source='taxonomy'. Tickers whose sector is not a
        known chain are skipped rather than inventing a layer for them.
        """
        pairs = [(chain, layer) for chain, layer in layer_for_chain.items()]
        if not pairs:
            return 0
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist_chain (ticker, layer, chain, source)
                SELECT w.ticker, m.layer, w.sector, 'sector'
                  FROM {self._schema}.watchlist w
                  JOIN (VALUES %s) AS m(chain, layer) ON m.chain = w.sector
                 WHERE w.removed_at IS NULL
                ON CONFLICT (ticker, chain) DO NOTHING
                """.replace("%s", ", ".join(["(%s, %s)"] * len(pairs))),
                [v for pair in pairs for v in pair],
            )
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def chains_by_ticker(
        self, tickers: Iterable[str] | None = None
    ) -> dict[str, list[str]]:
        """ticker -> its chains. One query for the whole watchlist payload.

        Per-ticker lookups would be ~114 round trips to render one dashboard.
        """
        sql = f"""
            SELECT ticker, chain FROM {self._schema}.watchlist_chain
        """
        params: list[object] = []
        tickers = list(tickers) if tickers is not None else None
        if tickers:
            sql += " WHERE ticker = ANY(%s)"
            params.append([t.upper() for t in tickers])
        sql += " ORDER BY ticker, chain"
        out: dict[str, list[str]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, params or None)
            for ticker, chain in cur.fetchall():
                out.setdefault(ticker, []).append(chain)
        return out

    def tickers_in_chain(self, chain: str) -> list[str]:
        """Active tickers in a chain. Joins watchlist so removed names drop out.

        Membership rows are not deleted when a ticker leaves the watchlist —
        without this join a removed ticker would still answer the filter.
        """
        sql = f"""
            SELECT c.ticker
              FROM {self._schema}.watchlist_chain c
              JOIN {self._schema}.watchlist w ON w.ticker = c.ticker
             WHERE c.chain = %s AND w.removed_at IS NULL
             ORDER BY c.ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (chain,))
            return [r[0] for r in cur.fetchall()]

    def counts_by_chain(self) -> dict[str, int]:
        """chain -> active member count, for badges and empty-chain detection."""
        sql = f"""
            SELECT c.chain, count(*)
              FROM {self._schema}.watchlist_chain c
              JOIN {self._schema}.watchlist w ON w.ticker = c.ticker
             WHERE w.removed_at IS NULL
             GROUP BY c.chain
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return dict(cur.fetchall())
