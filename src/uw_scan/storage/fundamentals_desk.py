"""Nightly per-name desk rollup store (spec §3c, Task 12): revenue YoY and
gross-margin trajectory, one row per (ticker, period_end), computed by
`worker/jobs/fundamentals_desk_rollup.py` so the chain x metric matrix reads
it at request time with zero recompute.

Standalone repository, not a `Repository` mixin -- same rationale as
`earnings_calendar.py` / `implied_move.py`: `repository.py` is closed to new
query methods, and this is its own domain.

WHY UPSERT OVERWRITES (unlike `earnings_reactions`' insert-or-skip)
--------------------------------------------------------------------
A period's rollup is not a completed historical fact the way a realised
earnings reaction is. The statement store is append-only (a restatement lands
as a NEW `obs_id` beside the old one) and violations can be recorded or
cleared retroactively (`FundamentalObsRepository.recheck_violations`), so the
correct rev_yoy/gross_margin for an already-rolled-up period can change
between two nightly runs. The PK is (ticker, period_end), and a rerun should
overwrite with the freshest recompute -- same shape as `ImpliedMoveRepository.
upsert_rows`, not `EarningsReactionsRepository`'s.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg


class FundamentalsDeskRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-replace one row per (ticker, period_end). Returns rows
        genuinely NEW (measured via `xmax = 0`, not assumed from `len(rows)`
        -- a same-night replay must report zero new rows, honestly, even
        though every row's `computed_at` still advances).

        Every non-key column is in the DO UPDATE SET list, `knowledge_date_known`
        included. A column left out of that list is write-once: the first run's
        value sticks and no rerun can ever correct it, so a period that later
        acquires a real filing date would keep claiming its knowledge date was
        estimated.
        """
        if not rows:
            return 0
        table = f"{self._schema}.fundamentals_desk_rollup"
        sql = f"""
            INSERT INTO {table}
                        (ticker, period_end, rev_yoy, gross_margin, gross_profit,
                         knowledge_date, knowledge_date_known)
                 VALUES (%(ticker)s, %(period_end)s, %(rev_yoy)s, %(gross_margin)s,
                         %(gross_profit)s, %(knowledge_date)s,
                         %(knowledge_date_known)s)
            ON CONFLICT (ticker, period_end) DO UPDATE SET
                 rev_yoy              = EXCLUDED.rev_yoy,
                 gross_margin         = EXCLUDED.gross_margin,
                 gross_profit         = EXCLUDED.gross_profit,
                 knowledge_date       = EXCLUDED.knowledge_date,
                 knowledge_date_known = EXCLUDED.knowledge_date_known,
                 computed_at          = now()
              RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        with self.conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, {**row, "ticker": row["ticker"].upper()})
                fetched = cur.fetchone()
                if fetched is not None and fetched[0]:
                    inserted += 1
        self.conn.commit()
        return inserted

    def latest_per_ticker(self, tickers: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Newest `period_end` row per ticker -- what a matrix cell shows.
        Absent from the return dict, not a null-valued entry, for a ticker
        with no rollup row at all."""
        if not tickers:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (ticker)
                           ticker, period_end, rev_yoy, gross_margin, gross_profit,
                           knowledge_date, knowledge_date_known, computed_at
                      FROM {self._schema}.fundamentals_desk_rollup
                     WHERE ticker = ANY(%s)
                     ORDER BY ticker, period_end DESC""",
                ([t.upper() for t in tickers],),
            )
            cols = [d.name for d in cur.description]
            return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}

    def non_usd_currencies(self, tickers: Sequence[str]) -> dict[str, list[str]]:
        """Per ticker, every non-USD currency the store has EVER recorded.

        Two traps live in this one column. `reported_currency` arrives as the
        literal STRING `'None'` on some observations (AMZN 2026-Q2, verified),
        which is not SQL NULL and would sort into the result as a currency
        named "None". And a name is USD-safe only if NO observation of it
        carries another currency — testing the latest one alone would clear a
        filer that switched, for exactly the historical periods where the
        hazard is real.

        Absent from the returned dict means USD-only; the value is never an
        empty list.
        """
        if not tickers:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ticker, raw_jsonb->>'reported_currency'
                      FROM {self._schema}.fundamental_statement_obs
                     WHERE ticker = ANY(%s)""",
                ([t.upper() for t in tickers],),
            )
            found: dict[str, set[str]] = {}
            for ticker, currency in cur.fetchall():
                if currency in (None, "", "None", "USD"):
                    continue
                found.setdefault(ticker, set()).add(currency)
        return {t: sorted(cs) for t, cs in found.items()}

    def quarterly_line_item(
        self,
        tickers: Sequence[str],
        *,
        statement: str,
        field: str,
        since: date,
    ) -> list[tuple[str, date, str]]:
        """One filed quarterly line item, as FILED TEXT.

        Returned unparsed on purpose: the store holds whatever the provider
        served, and a `::numeric` cast in SQL turns one malformed string into
        a 500 on a page read. The caller parses and drops what it cannot read,
        which is a coverage fact it can then report.

        `DISTINCT ON (ticker, period_end) ... ORDER BY obs_id DESC` takes the
        NEWEST observation of each period. The statement store is append-only,
        so a restated period holds several rows (MSFT 2026-06-30 carries two);
        without the dedupe the period is double-counted in any sum.
        """
        if not tickers:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (ticker, period_end)
                           ticker, period_end, raw_jsonb->>%s
                      FROM {self._schema}.fundamental_statement_obs
                     WHERE statement = %s AND period_type = 'quarterly'
                       AND ticker = ANY(%s) AND period_end >= %s
                       AND raw_jsonb->>%s IS NOT NULL
                     ORDER BY ticker, period_end, obs_id DESC""",
                (field, statement, [t.upper() for t in tickers], since, field),
            )
            return [(r[0], r[1], r[2]) for r in cur.fetchall()]

    def chain_layers(
        self, *, version: str, domains: Sequence[str]
    ) -> dict[str, tuple[str, int]]:
        """Per chain, the layer holding its LOWEST rank: `{chain: (layer, rank)}`.

        Read from `research_chains` and NOT from the membership join, because
        the two disagree exactly where it matters. The five `dc_buildout`
        chains each carry an L3 row with NO open members plus a ranked stage
        row that holds all of them, so a layer derived from memberships labels
        `Cooling/Thermal` as layer `Cooling-Thermal` instead of `L3` — and the
        chain map then has no plane to put it on. `layer_rank = 0` is what
        "sits on a taxonomy layer plane" means; a chain whose lowest rank is
        positive (`Optical-Communication`) is a case chain and belongs in a
        funnel, not on a plane.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (chain) chain, layer, layer_rank
                      FROM {self._schema}.research_chains
                     WHERE taxonomy_version = %s AND domain = ANY(%s)
                     ORDER BY chain, layer_rank, layer""",
                (version, list(domains)),
            )
            return {r[0]: (r[1], int(r[2] or 0)) for r in cur.fetchall()}

    def chains_outside_domains(
        self, *, version: str, domains: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Open chains in the active taxonomy that this section does NOT cover.

        The boundary is computed, not listed: a chain added to a domain outside
        the section appears here without a code change, and one that moves INTO
        the section leaves here without one. Counted at DISTINCT-ticker grain
        because membership is (chain, layer, ticker)-grained.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT c.chain,
                           array_agg(DISTINCT c.domain ORDER BY c.domain),
                           count(DISTINCT m.ticker)
                      FROM {self._schema}.research_chains c
                      JOIN {self._schema}.chain_membership m
                        ON m.taxonomy_version = c.taxonomy_version
                       AND m.chain = c.chain AND m.layer = c.layer
                       AND m.valid_to IS NULL
                     WHERE c.taxonomy_version = %s
                       AND NOT (c.domain = ANY(%s))
                     GROUP BY c.chain
                     ORDER BY count(DISTINCT m.ticker) DESC, c.chain""",
                (version, list(domains)),
            )
            return [
                {"chain": r[0], "domains": list(r[1]), "members": int(r[2])}
                for r in cur.fetchall()
            ]

    def trajectory(self, ticker: str, quarters: int = 8) -> list[dict[str, Any]]:
        """Newest-first, most recent `quarters` periods for one ticker."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, period_end, rev_yoy, gross_margin, gross_profit,
                           knowledge_date, knowledge_date_known, computed_at
                      FROM {self._schema}.fundamentals_desk_rollup
                     WHERE ticker = %s
                     ORDER BY period_end DESC
                     LIMIT %s""",
                (ticker.upper(), quarters),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
