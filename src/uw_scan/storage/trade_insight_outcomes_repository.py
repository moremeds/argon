"""Persistence for Trade Insight outcome ledger (M8 of v5.3).

NEW DOMAIN — own file rather than extending repository.py per the
&lt;1000-line module budget rule. The repository.py monolith already sits
at ~5,000 lines; a brand-new persistence domain starts in its own
module from method one.

One row per `trade_insight_ai_analyses.analysis_id`. Rows are upserted
by the nightly worker job (`trade_insight_outcome_backfill`) as
forward-looking OHLC arrives; the priors view (M10) aggregates these
into per-provider per-archetype hit-rate stats.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection


@dataclass(frozen=True)
class TradeInsightOutcomeRow:
    """Read-side projection of `uw_scan.trade_insight_outcomes`.

    Mirrors the column order in `054_trade_insight_outcomes.sql`. NULL
    columns are surfaced as `None` so the priors view / API can
    distinguish "not yet scored" from "scored as False."
    """

    id: UUID
    analysis_id: UUID
    ticker: str
    provider: str
    prompt_version: str
    snapshot_date: date
    snapshot_close: Decimal | None
    close_1d: Decimal | None
    close_1d_date: date | None
    close_3d: Decimal | None
    close_3d_date: date | None
    close_5d: Decimal | None
    close_5d_date: date | None
    close_10d: Decimal | None
    close_10d_date: date | None
    thesis_trigger_level: Decimal | None
    thesis_trigger_meaning: str | None
    thesis_trigger_fired_after: bool | None
    thesis_trigger_hit_date: date | None
    entry_trigger_level: Decimal | None
    entry_trigger_meaning: str | None
    entry_trigger_fired_after: bool | None
    entry_trigger_hit_date: date | None
    invalidation_level: Decimal | None
    invalidation_hit: bool | None
    invalidation_hit_date: date | None
    target_level: Decimal | None
    target_hit: bool | None
    target_hit_date: date | None
    days_to_resolution: int | None
    resolved_outcome: str | None
    notes: str | None
    last_evaluated_at: datetime
    created_at: datetime


class TradeInsightOutcomeRepository:
    """Repository for the trade_insight_outcomes ledger.

    Owns the upsert path used by the nightly worker + the per-ticker /
    per-priors read paths used by the API. Schema is set via search_path
    in __init__, so SQL bodies use unqualified table names.
    """

    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        analysis_id: UUID | str,
        ticker: str,
        provider: str,
        prompt_version: str,
        snapshot_date: date,
        snapshot_close: Decimal | None,
        # fixed windows
        close_1d: Decimal | None = None,
        close_1d_date: date | None = None,
        close_3d: Decimal | None = None,
        close_3d_date: date | None = None,
        close_5d: Decimal | None = None,
        close_5d_date: date | None = None,
        close_10d: Decimal | None = None,
        close_10d_date: date | None = None,
        # v5.3 trigger components
        thesis_trigger_level: Decimal | None = None,
        thesis_trigger_meaning: str | None = None,
        thesis_trigger_fired_after: bool | None = None,
        thesis_trigger_hit_date: date | None = None,
        entry_trigger_level: Decimal | None = None,
        entry_trigger_meaning: str | None = None,
        entry_trigger_fired_after: bool | None = None,
        entry_trigger_hit_date: date | None = None,
        invalidation_level: Decimal | None = None,
        invalidation_hit: bool | None = None,
        invalidation_hit_date: date | None = None,
        target_level: Decimal | None = None,
        target_hit: bool | None = None,
        target_hit_date: date | None = None,
        # resolution
        days_to_resolution: int | None = None,
        resolved_outcome: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Insert or update the outcome row for an analysis.

        Upserts on the `analysis_id` unique index — re-running the
        nightly scorer is a no-op when nothing has changed.
        """
        sql = """
            INSERT INTO trade_insight_outcomes (
                analysis_id, ticker, provider, prompt_version,
                snapshot_date, snapshot_close,
                close_1d, close_1d_date,
                close_3d, close_3d_date,
                close_5d, close_5d_date,
                close_10d, close_10d_date,
                thesis_trigger_level, thesis_trigger_meaning,
                thesis_trigger_fired_after, thesis_trigger_hit_date,
                entry_trigger_level, entry_trigger_meaning,
                entry_trigger_fired_after, entry_trigger_hit_date,
                invalidation_level, invalidation_hit, invalidation_hit_date,
                target_level, target_hit, target_hit_date,
                days_to_resolution, resolved_outcome, notes,
                last_evaluated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                NOW()
            )
            ON CONFLICT (analysis_id) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                provider = EXCLUDED.provider,
                prompt_version = EXCLUDED.prompt_version,
                snapshot_date = EXCLUDED.snapshot_date,
                snapshot_close = EXCLUDED.snapshot_close,
                close_1d = EXCLUDED.close_1d,
                close_1d_date = EXCLUDED.close_1d_date,
                close_3d = EXCLUDED.close_3d,
                close_3d_date = EXCLUDED.close_3d_date,
                close_5d = EXCLUDED.close_5d,
                close_5d_date = EXCLUDED.close_5d_date,
                close_10d = EXCLUDED.close_10d,
                close_10d_date = EXCLUDED.close_10d_date,
                thesis_trigger_level = EXCLUDED.thesis_trigger_level,
                thesis_trigger_meaning = EXCLUDED.thesis_trigger_meaning,
                thesis_trigger_fired_after = EXCLUDED.thesis_trigger_fired_after,
                thesis_trigger_hit_date = EXCLUDED.thesis_trigger_hit_date,
                entry_trigger_level = EXCLUDED.entry_trigger_level,
                entry_trigger_meaning = EXCLUDED.entry_trigger_meaning,
                entry_trigger_fired_after = EXCLUDED.entry_trigger_fired_after,
                entry_trigger_hit_date = EXCLUDED.entry_trigger_hit_date,
                invalidation_level = EXCLUDED.invalidation_level,
                invalidation_hit = EXCLUDED.invalidation_hit,
                invalidation_hit_date = EXCLUDED.invalidation_hit_date,
                target_level = EXCLUDED.target_level,
                target_hit = EXCLUDED.target_hit,
                target_hit_date = EXCLUDED.target_hit_date,
                days_to_resolution = EXCLUDED.days_to_resolution,
                resolved_outcome = EXCLUDED.resolved_outcome,
                notes = EXCLUDED.notes,
                last_evaluated_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    str(analysis_id),
                    ticker,
                    provider,
                    prompt_version,
                    snapshot_date,
                    snapshot_close,
                    close_1d,
                    close_1d_date,
                    close_3d,
                    close_3d_date,
                    close_5d,
                    close_5d_date,
                    close_10d,
                    close_10d_date,
                    thesis_trigger_level,
                    thesis_trigger_meaning,
                    thesis_trigger_fired_after,
                    thesis_trigger_hit_date,
                    entry_trigger_level,
                    entry_trigger_meaning,
                    entry_trigger_fired_after,
                    entry_trigger_hit_date,
                    invalidation_level,
                    invalidation_hit,
                    invalidation_hit_date,
                    target_level,
                    target_hit,
                    target_hit_date,
                    days_to_resolution,
                    resolved_outcome,
                    notes,
                ),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def fetch_pending(self, *, limit: int = 100) -> list[tuple[UUID, date]]:
        """Return (analysis_id, snapshot_date) pairs for outcomes that
        still need scoring — resolved_outcome IS NULL or 'pending'.

        Ordered oldest-first so the nightly worker drains the backlog
        before scoring fresh rows. The partial index from migration
        054 keeps this scan cheap as the table grows.
        """
        sql = """
            SELECT analysis_id, snapshot_date
              FROM trade_insight_outcomes
             WHERE resolved_outcome IS NULL OR resolved_outcome = 'pending'
             ORDER BY last_evaluated_at ASC, snapshot_date ASC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    def fetch_for_analysis(
        self, analysis_id: UUID | str
    ) -> TradeInsightOutcomeRow | None:
        """Return the outcome row for a single analysis, or None."""
        sql = "SELECT * FROM trade_insight_outcomes WHERE analysis_id = %s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (str(analysis_id),))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
        if row is None:
            return None
        return TradeInsightOutcomeRow(**dict(zip(cols, row)))

    def fetch_unscored_analyses(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return succeeded analyses that don't yet have an outcome row.

        Used by the nightly worker's initial-backfill pass: every
        succeeded `trade_insight_ai_analyses` row without an outcome
        sibling becomes a candidate for scoring. Once the row exists,
        the incremental pass picks it up via `fetch_pending`.
        """
        sql = """
            SELECT a.analysis_id, a.ticker, a.provider, a.prompt_version,
                   a.finished_at, a.outcome_jsonb
              FROM trade_insight_ai_analyses a
              LEFT JOIN trade_insight_outcomes o ON o.analysis_id = a.analysis_id
             WHERE a.status = 'succeeded'
               AND o.analysis_id IS NULL
             ORDER BY a.finished_at ASC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
        return [
            {
                "analysis_id": r[0],
                "ticker": r[1],
                "provider": r[2],
                "prompt_version": r[3],
                "finished_at": r[4],
                "outcome_jsonb": r[5],
            }
            for r in rows
        ]
