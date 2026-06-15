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

    def insert_candidate_snapshots_bulk(
        self,
        *,
        run_id: int | None,
        section: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Append candidate snapshots (markout-ready). One row per candidate.

        Each ``rows`` dict carries: ticker, scored_at, bias, direction, score,
        score_model, score_breakdown, spot_at_signal, is_type_f, evidence.
        Append-only (no upsert) — every run accrues a new batch so history is
        preserved for Phase-2 markout.
        """
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.scanner_candidate_snapshots
              (run_id, section, ticker, scored_at, bias, direction, score,
               score_model, score_breakdown, spot_at_signal, is_type_f, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            (
                run_id,
                section,
                r["ticker"].upper(),
                r["scored_at"],
                r.get("bias"),
                r.get("direction"),
                r.get("score"),
                r["score_model"],
                Jsonb(r.get("score_breakdown"))
                if r.get("score_breakdown") is not None
                else None,
                r.get("spot_at_signal"),
                r.get("is_type_f"),
                Jsonb(r.get("evidence")) if r.get("evidence") is not None else None,
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_discovery_run_meta(self, run_id: int, meta: dict[str, Any]) -> None:
        """Store discovery run-level counts on the scan_runs row, namespaced under
        the ``discovery`` key of the existing ``aggregates`` JSONB.

        Persisted independently of candidate rows so a non-empty feed filtered to
        zero candidates still records alerts_pulled / earnings_unknown_dropped.
        The ``_DISCOVER`` sentinel ticker guarantees no collision with the
        real-ticker MarketAggregates readers (health / watchlist), which filter
        by real ticker + status.
        """
        sql = f"""
            UPDATE {self._schema}.scan_runs
            SET aggregates = COALESCE(aggregates, '{{}}'::jsonb)
                             || jsonb_build_object('discovery', %s::jsonb)
            WHERE run_id = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (Jsonb(meta), run_id))

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

    def fetch_latest_discovery_snapshot(self, limit: int = 20) -> dict[str, Any] | None:
        """Latest discovery run + its top-N candidate snapshots by score.

        Returns ``None`` if no discovery run has ever completed. Run-level counts
        come from ``scan_runs.aggregates->'discovery'`` (set by
        ``upsert_discovery_run_meta``), so they resolve even for empty / fully
        filtered runs. Run identity/timestamp come from the ``scan_runs`` row.
        """
        run_sql = f"""
            SELECT run_id, finished_at, aggregates
            FROM {self._schema}.scan_runs
            WHERE notes = 'discovery_scan' AND status = 'ok'
            ORDER BY finished_at DESC NULLS LAST, run_id DESC
            LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(run_sql)
            run = cur.fetchone()
        if run is None:
            return None
        run_id, finished_at, aggregates = run[0], run[1], run[2]
        run_meta: dict[str, Any] = (aggregates or {}).get("discovery") or {}

        rows_sql = f"""
            SELECT ticker, scored_at, bias, direction, score, score_model,
                   score_breakdown, spot_at_signal, evidence
            FROM {self._schema}.scanner_candidate_snapshots
            WHERE run_id = %s AND section = 'discovery'
              -- Drop tickers the user has since added to the watchlist so a
              -- just-promoted ticker doesn't linger in DISCOVERED (showing in
              -- both sections) until the next scheduled discovery run.
              AND ticker NOT IN (
                SELECT upper(ticker) FROM {self._schema}.watchlist
                WHERE removed_at IS NULL
              )
            ORDER BY score DESC NULLS LAST, ticker ASC
            LIMIT %s
        """
        candidates = self._select_dicts(rows_sql, (run_id, limit))
        return {
            "run_id": run_id,
            "scored_at": finished_at,
            "alerts_pulled": int(run_meta.get("alerts_pulled", 0) or 0),
            "earnings_unknown_dropped": int(
                run_meta.get("earnings_unknown_dropped", 0) or 0
            ),
            "candidates": candidates,
        }

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
