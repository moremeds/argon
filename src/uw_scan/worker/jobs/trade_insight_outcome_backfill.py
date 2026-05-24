"""Nightly outcome-scoring job for trade_insight_outcomes.

Two passes per tick:

  1. INITIAL — finds every succeeded `trade_insight_ai_analyses` row that
     does not yet have an `trade_insight_outcomes` sibling and bootstraps
     an empty outcome row (status='pending').

  2. INCREMENTAL — drains the pending queue (oldest first), fetches
     forward-looking daily closes from `daily_ohlc`, and updates each
     outcome with:
       - close_1d/3d/5d/10d (closest business day at or after the offset)
       - thesis_trigger_fired_after + thesis_trigger_hit_date
       - entry_trigger_fired_after + entry_trigger_hit_date
       - invalidation_hit + invalidation_hit_date
       - target_hit + target_hit_date
       - resolved_outcome (target_hit / invalidation_hit / pending)

Direction is inferred from `headline.directional_bias` on the source
outcome — SHORT_DELTA expects `close < level` for thesis/entry triggers
and `close > level` for invalidation. LONG_DELTA mirrors. WAIT outcomes
keep their per-trigger fields NULL since there's no direction to check
against.

For v4 / v5.0 / v5.1 / v5.2 rows that predate the v5.3 trigger
decomposition, only the fixed-window closes are populated; per-trigger
fields stay NULL. The priors view filters on prompt_version to keep
per-archetype stats apples-to-apples.

The job is idempotent: re-running on the same DB state is a no-op
(touches last_evaluated_at only). Backfill batches are bounded so a
multi-hundred-row catch-up cannot starve other scheduled jobs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from uw_scan.storage.trade_insight_outcomes_repository import (
    TradeInsightOutcomeRepository,
)

logger = logging.getLogger(__name__)

INITIAL_BACKFILL_BATCH = 50  # rows per initial-backfill tick
INCREMENTAL_BATCH = 25  # rows per incremental-scoring tick
WINDOW_OFFSETS = (1, 3, 5, 10)  # business-day offsets for fixed-window closes


# ---------------------------------------------------------------------------
# Outcome-shape helpers — pull the v5.3 trigger components out of a dict
# without needing to round-trip through Pydantic (faster + tolerant of v4/v5.0
# rows that don't have these fields).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TriggerLevel:
    level: Decimal | None
    meaning: str | None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip().lstrip("$"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not coerce %r to Decimal: %s", value, repr(exc))
        return None


def _extract_trigger(outcome: dict[str, Any], key: str) -> _TriggerLevel:
    """Pull (level, meaning) from a v5.3 outcome block. v5.2 backfill is
    handled by the lenient coercer at write time, so by the time we read
    these rows from outcome_jsonb the v5.3 shape is already populated."""
    block = (outcome or {}).get(key) or {}
    if not isinstance(block, dict):
        return _TriggerLevel(None, None)
    return _TriggerLevel(_decimal_or_none(block.get("level")), block.get("meaning"))


def _extract_target_level(outcome: dict[str, Any]) -> Decimal | None:
    """Target level lives on preferred_expression.strike_role.target_level
    (legacy v5.2 location) — v5.3 didn't promote target to a TriggerComponent."""
    pe = (outcome or {}).get("preferred_expression") or {}
    if not isinstance(pe, dict):
        return None
    sr = pe.get("strike_role") or {}
    if not isinstance(sr, dict):
        return None
    return _decimal_or_none(sr.get("target_level"))


def _direction_for(outcome: dict[str, Any]) -> str | None:
    """Read headline.directional_bias. Returns 'LONG_DELTA', 'SHORT_DELTA',
    or None when bias is WAIT / unknown — in which case per-trigger
    scoring is skipped (no direction to evaluate against)."""
    headline = (outcome or {}).get("headline") or {}
    bias = headline.get("directional_bias") if isinstance(headline, dict) else None
    if bias in ("LONG_DELTA", "SHORT_DELTA"):
        return bias
    return None


# ---------------------------------------------------------------------------
# Hit-detection logic
# ---------------------------------------------------------------------------


def _trigger_hit_date(
    closes: list[tuple[date, Decimal]],
    level: Decimal | None,
    direction: str,
    *,
    invert: bool = False,
) -> date | None:
    """Walk forward through (date, close) pairs after snapshot_date and
    return the first date where the close crosses `level` in the
    direction implied by `direction` (or its inverse if `invert=True`,
    which is how invalidation works: SHORT_DELTA thesis breaks when
    price reclaims back ABOVE the broken-support level).

    Returns None if level is None or no close ever crosses it.
    """
    if level is None:
        return None
    for d, c in closes:
        if direction == "SHORT_DELTA":
            crosses = (c > level) if invert else (c < level)
        else:  # LONG_DELTA
            crosses = (c < level) if invert else (c > level)
        if crosses:
            return d
    return None


def _target_hit_date(
    closes: list[tuple[date, Decimal]],
    target: Decimal | None,
    direction: str,
) -> date | None:
    """Target is reached when price hits the favorable side of the level:
    SHORT_DELTA target = lower price (close <= target);
    LONG_DELTA target = higher price (close >= target)."""
    if target is None:
        return None
    for d, c in closes:
        reached = (c <= target) if direction == "SHORT_DELTA" else (c >= target)
        if reached:
            return d
    return None


def _fixed_window_closes(
    closes: list[tuple[date, Decimal]],
    snapshot_date: date,
) -> dict[int, tuple[date | None, Decimal | None]]:
    """For each business-day offset in WINDOW_OFFSETS, pick the close on
    the offset day OR the next available trading day (since closes only
    exist on trading days). Returns {offset: (date, close)} with
    (None, None) when the future bar hasn't arrived yet.
    """
    out: dict[int, tuple[date | None, Decimal | None]] = {}
    for offset in WINDOW_OFFSETS:
        # `closes` excludes snapshot_date itself (filtered upstream).
        # The nth-business-day target is approximate — pick the first
        # close whose calendar offset >= business-day offset. This is
        # close enough for outcome scoring; precise NYSE business-day
        # calendar isn't worth the dependency.
        target_min_offset_days = offset  # treat business day offset as a lower bound
        hit: tuple[date, Decimal] | None = None
        for d, c in closes:
            if (d - snapshot_date).days >= target_min_offset_days:
                hit = (d, c)
                break
        out[offset] = (hit[0], hit[1]) if hit else (None, None)
    return out


# ---------------------------------------------------------------------------
# OHLC fetch
# ---------------------------------------------------------------------------


def _fetch_forward_closes(
    conn: psycopg.Connection,
    ticker: str,
    snapshot_date: date,
    horizon_days: int = 90,
) -> list[tuple[date, Decimal]]:
    """Return (date, close) pairs from daily_ohlc for `ticker` where
    date > snapshot_date AND date <= snapshot_date + horizon_days,
    ordered ascending. Empty list when the table has no forward bars
    (recent snapshots, or massive.com hasn't backfilled yet)."""
    end = snapshot_date + timedelta(days=horizon_days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close
              FROM uw_scan.daily_ohlc
             WHERE ticker = %s AND date > %s AND date <= %s
             ORDER BY date ASC
            """,
            (ticker, snapshot_date, end),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def _fetch_snapshot_close(
    conn: psycopg.Connection,
    ticker: str,
    snapshot_date: date,
) -> Decimal | None:
    """Return the close on snapshot_date, or the latest close at or
    before it if snapshot_date itself isn't in daily_ohlc."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close FROM uw_scan.daily_ohlc
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 1
            """,
            (ticker, snapshot_date),
        )
        row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Pass 1: initial backfill — bootstrap empty rows for unscored analyses
# ---------------------------------------------------------------------------


def _bootstrap_unscored_rows(
    conn: psycopg.Connection,
    repo: TradeInsightOutcomeRepository,
    *,
    limit: int = INITIAL_BACKFILL_BATCH,
) -> int:
    """Insert empty (resolved_outcome='pending') outcome rows for every
    succeeded analysis that doesn't yet have one. Returns the count."""
    unscored = repo.fetch_unscored_analyses(limit=limit)
    if not unscored:
        return 0
    for analysis in unscored:
        outcome = analysis["outcome_jsonb"] or {}
        finished_at = analysis["finished_at"]
        snapshot_date = finished_at.date() if finished_at else None
        if snapshot_date is None:
            logger.warning(
                "analysis %s succeeded with NULL finished_at — skipping",
                analysis["analysis_id"],
            )
            continue
        snapshot_close = _fetch_snapshot_close(conn, analysis["ticker"], snapshot_date)
        thesis = _extract_trigger(outcome, "thesis_trigger")
        entry = _extract_trigger(outcome, "entry_trigger")
        invalid = _extract_trigger(outcome, "invalidation")
        target = _extract_target_level(outcome)
        repo.upsert(
            analysis_id=analysis["analysis_id"],
            ticker=analysis["ticker"],
            provider=analysis["provider"],
            prompt_version=analysis["prompt_version"],
            snapshot_date=snapshot_date,
            snapshot_close=snapshot_close,
            thesis_trigger_level=thesis.level,
            thesis_trigger_meaning=thesis.meaning,
            entry_trigger_level=entry.level,
            entry_trigger_meaning=entry.meaning,
            invalidation_level=invalid.level,
            target_level=target,
            resolved_outcome="pending",
            notes="initial backfill — awaiting forward closes",
        )
    return len(unscored)


# ---------------------------------------------------------------------------
# Pass 2: incremental scoring — score the pending queue with available bars
# ---------------------------------------------------------------------------


def _score_pending_rows(
    conn: psycopg.Connection,
    repo: TradeInsightOutcomeRepository,
    *,
    limit: int = INCREMENTAL_BATCH,
) -> int:
    """For each pending outcome, fetch forward closes from daily_ohlc and
    update the row with whatever scoring is now possible. Returns count."""
    pending = repo.fetch_pending(limit=limit)
    if not pending:
        return 0
    scored = 0
    for analysis_id, snapshot_date in pending:
        # Read the source analysis to learn direction + ticker + levels
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT a.ticker, a.provider, a.prompt_version, a.outcome_jsonb
                  FROM uw_scan.trade_insight_ai_analyses a
                 WHERE a.analysis_id = %s
                """,
                (str(analysis_id),),
            )
            analysis = cur.fetchone()
        if analysis is None:
            logger.warning(
                "outcome %s references missing analysis — leaving as pending",
                analysis_id,
            )
            continue
        outcome = analysis["outcome_jsonb"] or {}
        ticker = analysis["ticker"]
        direction = _direction_for(outcome)
        closes = _fetch_forward_closes(conn, ticker, snapshot_date)
        windows = _fixed_window_closes(closes, snapshot_date)

        # Per-trigger scoring is direction-sensitive. WAIT outcomes get
        # only the fixed-window closes; trigger fields stay NULL.
        thesis = _extract_trigger(outcome, "thesis_trigger")
        entry = _extract_trigger(outcome, "entry_trigger")
        invalid = _extract_trigger(outcome, "invalidation")
        target = _extract_target_level(outcome)

        thesis_hit_date = (
            _trigger_hit_date(closes, thesis.level, direction) if direction else None
        )
        entry_hit_date = (
            _trigger_hit_date(closes, entry.level, direction) if direction else None
        )
        # Invalidation crosses AGAINST the trade direction — invert.
        invalid_hit_date = (
            _trigger_hit_date(closes, invalid.level, direction, invert=True)
            if direction
            else None
        )
        target_hit_date = (
            _target_hit_date(closes, target, direction) if direction else None
        )

        # Resolution: first-hit wins between target and invalidation.
        resolved_outcome = "pending"
        days_to_resolution = None
        if target_hit_date and (
            invalid_hit_date is None or target_hit_date <= invalid_hit_date
        ):
            resolved_outcome = "target_hit"
            days_to_resolution = (target_hit_date - snapshot_date).days
        elif invalid_hit_date and (
            target_hit_date is None or invalid_hit_date < target_hit_date
        ):
            resolved_outcome = "invalidation_hit"
            days_to_resolution = (invalid_hit_date - snapshot_date).days

        repo.upsert(
            analysis_id=analysis_id,
            ticker=ticker,
            provider=analysis["provider"],
            prompt_version=analysis["prompt_version"],
            snapshot_date=snapshot_date,
            snapshot_close=_fetch_snapshot_close(conn, ticker, snapshot_date),
            close_1d=windows[1][1],
            close_1d_date=windows[1][0],
            close_3d=windows[3][1],
            close_3d_date=windows[3][0],
            close_5d=windows[5][1],
            close_5d_date=windows[5][0],
            close_10d=windows[10][1],
            close_10d_date=windows[10][0],
            thesis_trigger_level=thesis.level,
            thesis_trigger_meaning=thesis.meaning,
            thesis_trigger_fired_after=(
                thesis_hit_date is not None if thesis.level is not None else None
            ),
            thesis_trigger_hit_date=thesis_hit_date,
            entry_trigger_level=entry.level,
            entry_trigger_meaning=entry.meaning,
            entry_trigger_fired_after=(
                entry_hit_date is not None if entry.level is not None else None
            ),
            entry_trigger_hit_date=entry_hit_date,
            invalidation_level=invalid.level,
            invalidation_hit=(
                invalid_hit_date is not None if invalid.level is not None else None
            ),
            invalidation_hit_date=invalid_hit_date,
            target_level=target,
            target_hit=(target_hit_date is not None if target is not None else None),
            target_hit_date=target_hit_date,
            days_to_resolution=days_to_resolution,
            resolved_outcome=resolved_outcome,
            notes=(
                f"scored against {len(closes)} forward closes "
                f"(direction={direction or 'wait'})"
            ),
        )
        scored += 1
    return scored


# ---------------------------------------------------------------------------
# Public entry point — called by the scheduler nightly at 17:00 ET
# ---------------------------------------------------------------------------


def trade_insight_outcome_backfill_once(
    conn: psycopg.Connection,
    *,
    initial_batch: int = INITIAL_BACKFILL_BATCH,
    incremental_batch: int = INCREMENTAL_BATCH,
) -> dict[str, int]:
    """Single tick of the outcome scorer. Returns counts for telemetry."""
    repo = TradeInsightOutcomeRepository(conn)
    bootstrapped = _bootstrap_unscored_rows(conn, repo, limit=initial_batch)
    scored = _score_pending_rows(conn, repo, limit=incremental_batch)
    return {"bootstrapped": bootstrapped, "scored": scored}
