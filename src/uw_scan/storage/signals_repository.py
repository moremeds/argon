"""Persistence for scanner detector outputs.

Standalone module - not a Repository mixin. Modelled on
provider_usage.py: takes its own psycopg connection (or shares one),
owns only scanner-related read/write methods, never appended to the
5,000+ line repository.py. See spec §7 and the standing rule in
MEMORY.md ("feedback_repository_split_threshold").

Read queries consumed by the API live here too - both halves of the
scanner persistence boundary stay in one file.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


class SignalsRepository:
    """Read/write for signal_hits, signal_context_flags, signal_gates.

    The connection is provided by the caller (typically reusing the same
    psycopg.Connection that the main Repository uses inside
    pipeline.run_single_stock, so writes participate in the existing
    scan transaction).
    """

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    # ------------------------------------------------------------------
    # Write API (called from scanner.pipeline.run_detectors)
    # ------------------------------------------------------------------

    def upsert_signal_hit(
        self,
        *,
        run_id: int,
        ticker: str,
        signal_type: str,
        tier: int,
        score: Decimal,
        evidence: dict[str, Any],
        freshness: str,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_hits
              (run_id, ticker, signal_type, tier, score, evidence, freshness)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker, signal_type) DO UPDATE SET
              tier = EXCLUDED.tier,
              score = EXCLUDED.score,
              evidence = EXCLUDED.evidence,
              freshness = EXCLUDED.freshness,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker.upper(),
                    signal_type,
                    tier,
                    score,
                    Jsonb(evidence),
                    freshness,
                ),
            )

    def upsert_context_flag(
        self,
        *,
        run_id: int,
        ticker: str,
        layer: str,
        label: str,
        value: Decimal | None,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_context_flags
              (run_id, ticker, layer, label, value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker, layer) DO UPDATE SET
              label = EXCLUDED.label,
              value = EXCLUDED.value,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper(), layer, label, value))

    def upsert_gate(
        self,
        *,
        run_id: int,
        ticker: str,
        earnings: str,
        liquidity: str,
        regime: str,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_gates
              (run_id, ticker, earnings, liquidity, regime)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker) DO UPDATE SET
              earnings = EXCLUDED.earnings,
              liquidity = EXCLUDED.liquidity,
              regime = EXCLUDED.regime,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (run_id, ticker.upper(), earnings, liquidity, regime),
            )

    # ------------------------------------------------------------------
    # Read API (called from scanner.pipeline & api/routers/scanner)
    # ------------------------------------------------------------------

    def fetch_hits_for_run(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = f"""
            SELECT signal_type, tier, score, evidence, freshness, inserted_at
            FROM {self._schema}.signal_hits
            WHERE run_id = %s AND ticker = %s
            ORDER BY tier ASC, signal_type ASC
        """
        return self._select_dicts(sql, (run_id, ticker.upper()))

    def fetch_context_flags_for_run(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = f"""
            SELECT layer, label, value
            FROM {self._schema}.signal_context_flags
            WHERE run_id = %s AND ticker = %s
            ORDER BY layer ASC
        """
        return self._select_dicts(sql, (run_id, ticker.upper()))

    def fetch_gate_for_run(self, run_id: int, ticker: str) -> dict[str, str] | None:
        sql = f"""
            SELECT earnings, liquidity, regime
            FROM {self._schema}.signal_gates
            WHERE run_id = %s AND ticker = %s
        """
        rows = self._select_dicts(sql, (run_id, ticker.upper()))
        return rows[0] if rows else None

    def fetch_dark_pool_window(
        self, ticker: str, *, lookback_days: int = 5
    ) -> list[dict[str, Any]]:
        """5-day rolling window of dark pool prints for a ticker.

        Matches xenon's 5-day aggregation (`xenon/analysis/ticker_data.py:321`)
        but reads from the already-persisted DB instead of re-fetching UW.
        Filters out canceled prints and rows with missing premium/price.
        """
        sql = f"""
            SELECT tracking_id, executed_at, price, size, premium,
                   nbbo_bid, nbbo_ask, market_center
            FROM {self._schema}.dark_pool_events
            WHERE ticker = %s
              AND executed_at >= NOW() - %s::interval
              AND COALESCE(canceled, FALSE) = FALSE
              AND premium IS NOT NULL
              AND price IS NOT NULL
            ORDER BY executed_at DESC
        """
        return self._select_dicts(sql, (ticker.upper(), f"{lookback_days} days"))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _select_dicts(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                return []
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in rows]
