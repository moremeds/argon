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

    def sync_ticker_memberships(
        self,
        ticker: str,
        rows: Sequence[tuple[str, str]],
        layer_for_chain: dict[str, str],
    ) -> list[str]:
        """Enforce one ticker's memberships — `rows` is its (layer, chain) pairs.

        The whole-table pair (replace + inherit) is the seeder's path and stays
        that way. This is the mutation path: adding a ticker or changing its
        sector must not rewrite 300 unrelated rows, because the module those
        rows would be rebuilt from is whatever the *running container* shipped
        with. When deployed code lags main — the normal state between a merge
        and a release — a whole-table rewrite triggered by an unrelated edit
        would quietly restore the old taxonomy. Scoping to one ticker caps that
        blast radius at the row set the caller actually touched.

        Rows the ticker keeps are updated in place rather than deleted and
        reinserted, so `added_at` still answers "since when has it been here".

        The target set is taxonomy rows ∪ the ticker's own sector — deliberately
        the same set the seeder's replace+inherit pair produces. Anything else
        would make a ticker's chains depend on which path last touched it. A
        sector that is not a known chain contributes nothing rather than an
        invented layer, matching inherit_sector_memberships.
        """
        ticker = ticker.upper()
        desired: dict[str, tuple[str, str]] = {
            chain: (layer, "taxonomy") for layer, chain in rows
        }
        sector = self._sector_of(ticker)
        if sector and sector not in desired and layer_for_chain.get(sector):
            desired[sector] = (layer_for_chain[sector], "sector")

        with self.conn.cursor() as cur:
            if desired:
                cur.execute(
                    f"""
                    DELETE FROM {self._schema}.watchlist_chain
                     WHERE ticker = %s AND chain <> ALL(%s)
                    """,
                    (ticker, list(desired)),
                )
                cur.executemany(
                    f"""
                    INSERT INTO {self._schema}.watchlist_chain
                                (ticker, layer, chain, source)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker, chain) DO UPDATE
                       SET layer = EXCLUDED.layer, source = EXCLUDED.source
                    """,
                    [
                        (ticker, layer, chain, source)
                        for chain, (layer, source) in desired.items()
                    ],
                )
            else:
                cur.execute(
                    f"DELETE FROM {self._schema}.watchlist_chain WHERE ticker = %s",
                    (ticker,),
                )
            cur.execute(
                f"SELECT chain FROM {self._schema}.watchlist_chain "
                "WHERE ticker = %s ORDER BY chain",
                (ticker,),
            )
            return [r[0] for r in cur.fetchall()]

    def _sector_of(self, ticker: str) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT sector FROM {self._schema}.watchlist WHERE ticker = %s",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def drop_stale_inherited_memberships(self) -> int:
        """Delete inherited rows whose chain no longer matches the ticker's sector.

        A source='sector' row means "this ticker is here because its sector said
        so". The moment `watchlist.sector` changes, that justification is gone
        and the row is stale — nothing else in the system can express it.

        This exists because inheriting only ever filled gaps and never retracted:
        correcting two mis-typed tickers' sectors left their old inherited rows
        behind, so the filter kept returning NOV under Healthcare and ELV under
        Sector-ETF through every re-seed. Scoped to source='sector' on purpose —
        taxonomy rows belong to replace_taxonomy_memberships, and letting both
        methods delete the same rows makes the outcome depend on call order.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {self._schema}.watchlist_chain c
                 USING {self._schema}.watchlist w
                 WHERE w.ticker = c.ticker
                   AND c.source = 'sector'
                   AND c.chain IS DISTINCT FROM w.sector
                """
            )
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def inherit_sector_memberships(self, layer_for_chain: dict[str, str]) -> int:
        """Give every active ticker a membership for its own `watchlist.sector`.

        Retracts before it fills. Inherited rows the sector no longer justifies
        are dropped first (see drop_stale_inherited_memberships), then the gaps
        are filled: `ON CONFLICT DO NOTHING` means a chain already asserted by
        the taxonomy keeps source='taxonomy'. Tickers whose sector is not a known
        chain are skipped rather than inventing a layer for them.
        """
        self.drop_stale_inherited_memberships()
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
