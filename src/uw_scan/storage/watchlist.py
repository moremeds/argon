"""Watchlist CRUD and card reads."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from .rows import (
    RescanQueueSummaryRow,
    WatchlistCardRow,
    WatchlistRow,
)


class _WatchlistMixin:
    _conn: psycopg.Connection
    _schema: str

    def list_active_watchlist(self) -> list[WatchlistRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, sector, notes, pinned, sort_rank, added_at, removed_at
                FROM {self._schema}.watchlist
                WHERE removed_at IS NULL
                ORDER BY sort_rank, ticker
                """
            )
            return [WatchlistRow(*row) for row in cur.fetchall()]

    def list_watchlist_spots(
        self,
    ) -> list[tuple[str, Decimal | None, datetime | None, str | None]]:
        """Lightweight (ticker, spot, spot_quoted_at, spot_source) projection
        for the live-spot browser poller — the WS consumer rewrites these
        columns every ~1s, and the full dashboard join is too heavy to poll.

        Codex P2 fix: drives from watchlist (LEFT JOIN watchlist_card +
        LEFT JOIN intraday_quote) so newly-added unscanned tickers — which
        have no watchlist_card row yet but DO get intraday_quote rows from
        the WS writer — still tick on the dashboard. Matches the same
        fresher-of-quote logic used by list_watchlist_cards."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  w.ticker,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.price
                    ELSE c.spot
                  END AS spot,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.quoted_at
                    ELSE c.spot_quoted_at
                  END AS spot_quoted_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.source
                    ELSE c.spot_source
                  END AS spot_source
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                WHERE w.removed_at IS NULL
                ORDER BY w.ticker
                """
            )
            return list(cur.fetchall())

    def add_watchlist_ticker(
        self,
        *,
        ticker: str,
        sector: str,
        notes: str | None = None,
        sort_rank: int = 0,
        pinned: bool = False,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist
                  (ticker, sector, notes, sort_rank, pinned)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET sector=EXCLUDED.sector, notes=EXCLUDED.notes,
                      sort_rank=EXCLUDED.sort_rank, pinned=EXCLUDED.pinned,
                      removed_at=NULL
                """,
                (ticker, sector, notes, sort_rank, pinned),
            )
        self._conn.commit()

    def soft_delete_watchlist_ticker(self, ticker: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET removed_at=NOW() WHERE ticker=%s",
                (ticker,),
            )
        self._conn.commit()

    def patch_watchlist_ticker(
        self,
        ticker: str,
        *,
        sector: str | None = None,
        notes: str | None = None,
        pinned: bool | None = None,
        sort_rank: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        for col, val in (
            ("sector", sector),
            ("notes", notes),
            ("pinned", pinned),
            ("sort_rank", sort_rank),
        ):
            if val is not None:
                sets.append(f"{col}=%s")
                vals.append(val)
        if not sets:
            return
        vals.append(ticker)
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET {', '.join(sets)} WHERE ticker=%s",
                vals,
            )
        self._conn.commit()

    # ---- watchlist_card ----

    def upsert_watchlist_card(
        self,
        *,
        ticker: str,
        run_id: int,
        scanned_at: datetime,
        spot: Decimal | None = None,
        preserve_spot: bool = False,
        **fields: Any,
    ) -> None:
        """Insert or replace the per-ticker card row.

        When ``preserve_spot=True``, an existing row's spot / spot_quoted_at /
        spot_source AND ret_1d/1w/30d are never overwritten — A13: the WS
        consumer owns both the spot price and the intraday-derived returns
        computed against that spot, so full_scan / rescan_tick computing
        returns from their own snapshot would drift the dashboard numbers
        away from the WS-canonical view. New rows (INSERT branch) still
        accept the passed values so an initial full_scan with no prior
        WS tick correctly seeds the card.

        ``updated_at`` is DB-owned (default NOW() on insert; refreshed by
        the conflict branch). It is NOT part of the column list, so INSERT
        cols and VALUES placeholders have matching arity.
        """
        cols = ["ticker", "run_id", "scanned_at", "spot", *fields.keys()]
        vals = [ticker, run_id, scanned_at, spot, *fields.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        # A13: gate the spot triple AND the return triple together. Gating
        # only spot would leave the WS-owned returns vulnerable to a
        # full_scan stomping ret_1d with a less-fresh snapshot.
        SPOT_OWNED = {
            "spot",
            "spot_quoted_at",
            "spot_source",
            "ret_1d",
            "ret_1w",
            "ret_30d",
        }
        if preserve_spot:
            update_cols = [c for c in cols if c != "ticker" and c not in SPOT_OWNED]
        else:
            update_cols = [c for c in cols if c != "ticker"]
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
        # When preserve_spot drops every updatable column (rare — would mean
        # full_scan only passed spot fields), fall back to a no-op DO NOTHING
        # so we don't emit empty `SET , updated_at=NOW()` SQL.
        conflict_clause = (
            f"DO UPDATE SET {updates}, updated_at=NOW()"
            if update_cols
            else "DO NOTHING"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist_card ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (ticker) {conflict_clause}
                """,
                vals,
            )
        self._conn.commit()

    def get_watchlist_card(self, ticker: str) -> WatchlistCardRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.watchlist_card WHERE ticker=%s",
                (ticker,),
            )
            row = cur.fetchone()
            return WatchlistCardRow.from_db(row, cur.description) if row else None

    def bulk_upsert_watchlist_card_spots(
        self,
        rows: list[tuple[str, Decimal, datetime, str]],
    ) -> None:
        """Update only spot/spot_quoted_at/spot_source on existing cards.

        Rows with no existing watchlist_card row are silently skipped — the
        WS consumer is not responsible for materializing cards (full_scan
        owns card creation).

        Does NOT commit — caller controls the transaction.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                UPDATE {self._schema}.watchlist_card
                SET spot           = %s,
                    spot_quoted_at = %s,
                    spot_source    = %s
                WHERE ticker = %s
                """,
                [
                    (price, quoted_at, source, ticker)
                    for (ticker, price, quoted_at, source) in rows
                ],
            )

    def bulk_upsert_watchlist_card_quotes(
        self,
        rows: list[
            tuple[
                str,
                Decimal,
                datetime,
                str,
                Decimal | None,
                Decimal | None,
                Decimal | None,
            ]
        ],
    ) -> None:
        """Update spot triple + intraday return triple on existing cards.

        Tuple shape: (ticker, price, quoted_at, source, ret_1d, ret_1w, ret_30d).
        Returns may be None (e.g., insufficient OHLC history). Rows with no
        existing card row are silently skipped. Does NOT commit — caller
        controls the transaction.

        Used by the WS writer to keep ret_1d/1w/30d in sync with the latest
        WS spot (R9). Without this, returns would only update on full_scan /
        rescan_tick and the dashboard cards would show stale returns
        mid-session even though spot ticked.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                UPDATE {self._schema}.watchlist_card
                SET spot           = %s,
                    spot_quoted_at = %s,
                    spot_source    = %s,
                    ret_1d         = %s,
                    ret_1w         = %s,
                    ret_30d        = %s
                WHERE ticker = %s
                """,
                [
                    (price, quoted_at, source, r1d, r1w, r30d, ticker)
                    for (ticker, price, quoted_at, source, r1d, r1w, r30d) in rows
                ],
            )

    def list_watchlist_cards(self) -> list[WatchlistCardRow]:
        """Return one row per active watchlist ticker.

        LEFT JOIN from watchlist → watchlist_card so tickers that haven't been
        scanned yet still appear (with scan-derived fields = None). The page
        renders them as 'no data' placeholders, which is preferable to making
        them invisible while a full_scan is still chewing through the queue.
        Also LEFT JOINs intraday_quotes so a 15-min-delayed spot price shows
        up even before the first full scan for that ticker.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH active_jobs AS (
                  SELECT
                    id, ticker, status, requested_at, started_at,
                    row_number() OVER (
                      ORDER BY priority DESC, requested_at ASC, id ASC
                    ) AS queue_position
                  FROM {self._schema}.jobs
                  WHERE status IN ('queued', 'running')
                ),
                latest_market_caps AS (
                  SELECT DISTINCT ON (ticker)
                    ticker,
                    marketcap
                  FROM {self._schema}.scan_results
                  WHERE marketcap IS NOT NULL
                  ORDER BY ticker, run_id DESC
                )
                -- The screener / etf-AUM fallbacks are LEFT JOIN LATERAL
                -- below so they only scan payloads for the ~100 watchlist
                -- tickers, not the full audit history. The pre-LATERAL CTE
                -- form tripped the planner into a parallel seq scan over
                -- 2.6 GB of raw_payloads (9.4 s on the watchlist endpoint).
                SELECT
                  w.ticker, w.sector, w.pinned, w.sort_rank,
                  c.run_id, c.scanned_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.price
                    ELSE c.spot
                  END                                                       AS spot,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.quoted_at
                    ELSE c.spot_quoted_at
                  END                                                       AS spot_quoted_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.source
                    ELSE c.spot_source
                  END                                                       AS spot_source,
                  c.iv_atm, c.iv_rank,
                  c.setup_type, c.setup_direction, c.setup_score,
                  c.aggression_pct,
                  c.ret_1d, c.ret_1w, c.ret_30d,
                  COALESCE(
                    sr.aggregates->>'market_cap',
                    lmc.marketcap::text,
                    lss.market_cap
                  ) AS market_cap,
                  COALESCE(sr.aggregates->>'aum', lea.aum) AS aum,
                  c.gex_flip_distance, c.gex_flip_price, c.gex_per_1pct_move,
                  c.max_gex_strike, c.gex_expiring_pct, c.gex_expiring_date,
                  c.skew_25d_30dte,
                  c.call_oi_total, c.put_oi_total, c.pcr_oi, c.pcr_vol,
                  c.pcr_delta_30d,
                  j.id AS active_job_id,
                  j.status AS active_job_status,
                  j.queue_position AS active_job_queue_position,
                  j.requested_at AS active_job_requested_at,
                  j.started_at AS active_job_started_at
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.scan_runs sr ON c.run_id = sr.run_id
                LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker
                LEFT JOIN LATERAL (
                  SELECT p.payload_jsonb->'data'->0->>'marketcap' AS market_cap
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE r.ticker = w.ticker
                    AND a.endpoint_slug = 'bulk_screener_stocks'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'array'
                    AND p.payload_jsonb->'data'->0->>'marketcap' IS NOT NULL
                  ORDER BY r.run_id DESC
                  LIMIT 1
                ) lss ON TRUE
                LEFT JOIN LATERAL (
                  SELECT p.payload_jsonb->'data'->>'aum' AS aum
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE r.ticker = w.ticker
                    AND a.endpoint_slug = 'etf_info'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'object'
                    AND p.payload_jsonb->'data'->>'aum' IS NOT NULL
                  ORDER BY r.run_id DESC
                  LIMIT 1
                ) lea ON TRUE
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                LEFT JOIN active_jobs j ON w.ticker = j.ticker
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, w.ticker
                """
            )
            return [
                WatchlistCardRow.from_list_row(row, cur.description)
                for row in cur.fetchall()
            ]

    def list_watchlist_cards_with_queue_summary(
        self,
    ) -> tuple[list[WatchlistCardRow], RescanQueueSummaryRow]:
        """Variant of list_watchlist_cards that also returns the rescan queue
        summary in a single round trip. Used by /api/watchlist to collapse
        2 DB queries into 1 in the common path.

        Edge case: when the watchlist is empty, CROSS JOIN summary drops all
        rows even if jobs exist — fall back to standalone summary query to
        preserve today's behavior (1 query in steady state, 2 in the
        empty-watchlist edge case).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH active_jobs AS (
                  SELECT
                    id, ticker, status, requested_at, started_at,
                    row_number() OVER (
                      ORDER BY priority DESC, requested_at ASC, id ASC
                    ) AS queue_position
                  FROM {self._schema}.jobs
                  WHERE status IN ('queued', 'running')
                ),
                summary AS (
                  SELECT
                    count(*)                                     AS s_total,
                    count(*) FILTER (WHERE status = 'queued')    AS s_queued,
                    count(*) FILTER (WHERE status = 'running')   AS s_running,
                    min(requested_at)                            AS s_oldest
                  FROM active_jobs
                ),
                latest_market_caps AS (
                  SELECT DISTINCT ON (ticker)
                    ticker,
                    marketcap
                  FROM {self._schema}.scan_results
                  WHERE marketcap IS NOT NULL
                  ORDER BY ticker, run_id DESC
                )
                -- The screener / etf-AUM fallbacks are LEFT JOIN LATERAL
                -- below (see list_watchlist_cards for the same rewrite).
                SELECT
                  w.ticker, w.sector, w.pinned, w.sort_rank,
                  c.run_id, c.scanned_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.price
                    ELSE c.spot
                  END                                                       AS spot,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.quoted_at
                    ELSE c.spot_quoted_at
                  END                                                       AS spot_quoted_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.source
                    ELSE c.spot_source
                  END                                                       AS spot_source,
                  c.iv_atm, c.iv_rank,
                  c.setup_type, c.setup_direction, c.setup_score,
                  c.aggression_pct,
                  c.ret_1d, c.ret_1w, c.ret_30d,
                  COALESCE(
                    sr.aggregates->>'market_cap',
                    lmc.marketcap::text,
                    lss.market_cap
                  ) AS market_cap,
                  COALESCE(sr.aggregates->>'aum', lea.aum) AS aum,
                  c.gex_flip_distance, c.gex_flip_price, c.gex_per_1pct_move,
                  c.max_gex_strike, c.gex_expiring_pct, c.gex_expiring_date,
                  c.skew_25d_30dte,
                  c.call_oi_total, c.put_oi_total, c.pcr_oi, c.pcr_vol,
                  c.pcr_delta_30d,
                  j.id AS active_job_id,
                  j.status AS active_job_status,
                  j.queue_position AS active_job_queue_position,
                  j.requested_at AS active_job_requested_at,
                  j.started_at AS active_job_started_at,
                  sm.s_total, sm.s_queued, sm.s_running, sm.s_oldest
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.scan_runs sr ON c.run_id = sr.run_id
                LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker
                LEFT JOIN LATERAL (
                  SELECT p.payload_jsonb->'data'->0->>'marketcap' AS market_cap
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE r.ticker = w.ticker
                    AND a.endpoint_slug = 'bulk_screener_stocks'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'array'
                    AND p.payload_jsonb->'data'->0->>'marketcap' IS NOT NULL
                  ORDER BY r.run_id DESC
                  LIMIT 1
                ) lss ON TRUE
                LEFT JOIN LATERAL (
                  SELECT p.payload_jsonb->'data'->>'aum' AS aum
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE r.ticker = w.ticker
                    AND a.endpoint_slug = 'etf_info'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'object'
                    AND p.payload_jsonb->'data'->>'aum' IS NOT NULL
                  ORDER BY r.run_id DESC
                  LIMIT 1
                ) lea ON TRUE
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                LEFT JOIN active_jobs j ON w.ticker = j.ticker
                CROSS JOIN summary sm
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, w.ticker
                """
            )
            all_rows = cur.fetchall()
            description = cur.description

        if not all_rows:
            # Empty watchlist: CROSS JOIN drops all rows even if active jobs
            # exist. Fall back to standalone summary to preserve today's
            # behavior (Codex review ISSUE-3 regression guard).
            return [], self.get_rescan_queue_summary()

        # The SELECT projects 37 card columns plus 4 summary columns
        # (s_total, s_queued, s_running, s_oldest). Look up by name to be
        # robust to a future hand reordering the projection.
        col_idx = {col.name: i for i, col in enumerate(description)}
        summary_col_names = {"s_total", "s_queued", "s_running", "s_oldest"}

        first = all_rows[0]
        summary = RescanQueueSummaryRow(
            total=first[col_idx["s_total"]] or 0,
            queued=first[col_idx["s_queued"]] or 0,
            running=first[col_idx["s_running"]] or 0,
            oldest_requested_at=first[col_idx["s_oldest"]],
        )

        # Strip the 4 summary columns before constructing the strict
        # WatchlistCardRow. Filter by name (not by trailing position) so a
        # future reordering of the SELECT projection doesn't silently break.
        card_positions = [
            i for i, col in enumerate(description) if col.name not in summary_col_names
        ]
        card_cols = [description[i] for i in card_positions]
        cards = [
            WatchlistCardRow.from_list_row(
                tuple(row[i] for i in card_positions),
                card_cols,
            )
            for row in all_rows
        ]
        return cards, summary

    # daily_ohlc / intraday_quote / pcr_history methods moved to _MarketDataMixin

    # jobs queue methods moved to _JobsMixin
    # etf_aum_cache methods moved to _MarketDataMixin

    # ---- aggregates (JSONB on scan_runs) ----
