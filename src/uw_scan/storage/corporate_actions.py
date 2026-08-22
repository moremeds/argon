"""Corporate-action event store (VRP research expansion, item 1 support).

massive_fundamentals keeps only the LATEST split/dividend; split-adjusting a
multi-month price series needs every event, so this domain owns the full
per-event history. Also exposes fetch_distinct_vrp_tickers (the scoring
universe) so the ingestion job stays self-contained.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg


class _CorporateActionsMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_corporate_action(
        self,
        *,
        ticker: str,
        event_type: str,
        event_date: _date,
        split_ratio: Decimal | None = None,
        cash_amount: Decimal | None = None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.corporate_actions "
            "(ticker, event_type, event_date, split_ratio, cash_amount) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, event_type, event_date) DO UPDATE SET "
            "split_ratio = EXCLUDED.split_ratio, cash_amount = EXCLUDED.cash_amount"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql, (ticker.upper(), event_type, event_date, split_ratio, cash_amount)
            )

    def fetch_corporate_actions(self, ticker: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT event_type, event_date, split_ratio, cash_amount "
            f"FROM {self._schema}.corporate_actions WHERE ticker = %s "
            "ORDER BY event_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def split_factors(
        self, tickers: list[str]
    ) -> dict[str, list[tuple[_date, float]]]:
        """`{ticker: [(execution_date, ratio), ...]}` — the splits on record.

        Bulk because the caller checks a whole universe in one pass and
        `fetch_corporate_actions` is one round trip per name.

        `ratio` is shares-after per share-before, so a 1-for-25 forward split is
        25.0 and a 50-for-1 reverse is 0.02. The band job does not adjust prices
        with these — livewire's silver tier already publishes adjusted closes.
        It uses them to decide whether a name it CANNOT read from silver may be
        priced from raw bronze anyway, which is true exactly when no split falls
        inside the window being priced.
        """
        if not tickers:
            return {}
        sql = (
            "SELECT ticker, event_date, split_ratio "
            f"FROM {self._schema}.corporate_actions "
            "WHERE event_type = 'split' AND split_ratio IS NOT NULL "
            "AND split_ratio > 0 AND ticker = ANY(%s) "
            "ORDER BY ticker, event_date"
        )
        out: dict[str, list[tuple[_date, float]]] = {}
        with self._conn.cursor() as cur:
            cur.execute(sql, ([t.upper() for t in tickers],))
            for ticker, event_date, ratio in cur.fetchall():
                out.setdefault(ticker, []).append((event_date, float(ratio)))
        return out

    def ingested_tickers(self, tickers: list[str]) -> set[str]:
        """The subset with at least one row on record — split OR dividend.

        Membership is evidence the ingest ever reached this name, and that is
        the thing `split_factors` cannot tell you: "never split" and "never
        asked" both come back as an empty list, so a caller that reads the empty
        one as clean prices a split name on an unadjusted series. On 2026-08-22
        that gap covered 15 of the 18 names the band job must price from bronze
        — AIG, CMCSA, ECL and HON among them, every one silently trusted — for
        the plain reason that the ingest then covered 137 of the universe's 450.

        Zero rows mostly means not ingested, because a 12-split/24-dividend
        lookback catches nearly every established name: across the 188 tickers
        the ingest did cover on 2026-08-22, not one ended with zero rows. It is
        not a perfect proxy, and the exceptions are known by name — massive
        returns no split AND no dividend for CFLT, CYBR and PSTG, so those three
        stay unverifiable however often they are ingested, and lose a band they
        could in principle carry. Three names against silently mispricing a split
        one is the trade taken; the caller's refusal text says "indistinguishable
        from never having asked" rather than asserting the ingest skipped them.

        ponytail: an event table cannot record a non-event. If those three ever
        matter, the upgrade is a per-ticker ingest-coverage row written by
        `corporate_actions_refresh_once`, not a sentinel event in here.
        """
        if not tickers:
            return set()
        sql = (
            "SELECT DISTINCT ticker "
            f"FROM {self._schema}.corporate_actions "
            "WHERE ticker = ANY(%s)"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, ([t.upper() for t in tickers],))
            return {row[0] for row in cur.fetchall()}

    def fetch_fundamental_universe_tickers(self) -> list[str]:
        """Every active name in the fundamental universe, any tier.

        Here rather than on `FundamentalObsRepository` for the reason the
        module docstring gives for `fetch_distinct_vrp_tickers`: the ingestion
        job takes one aggregate repo and stays self-contained. `valuation_anchors`
        prices 20 quarters of history, and for the names livewire cannot
        publish an adjusted series for, this store is the only evidence of
        whether their raw closes are on today's share basis. Without coverage
        here those names are banded across their own splits — CXAI's 50-for-1
        left buy_below at $0.107 against a $4.59 spot.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker FROM {self._schema}.fundamental_universe "
                "WHERE removed_at IS NULL ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]

    def fetch_distinct_vrp_tickers(self) -> list[str]:
        """The VRP scoring universe — every ticker with a vrp_daily panel. The
        corporate-action ingestion covers this ∪ active watchlist ∪ the
        fundamental universe so every scored ticker has corp-action coverage
        (research-expansion ISSUE-9)."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker FROM {self._schema}.vrp_daily ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]


class CorporateActionsRepository(_CorporateActionsMixin):
    """Standalone handle for callers outside the aggregate `Repository`.

    The mixin is assembled into `Repository` for the ingest job, which already
    holds one. `fundamental_anchors` does not — it takes a bare connection — and
    reaching for the aggregate just to read splits would pull in every other
    domain. Same shape as the other standalone domain repositories.
    """

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn
