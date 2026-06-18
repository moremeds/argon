"""Scan-run lifecycle, advisory lock, and scan-run JSONB helpers."""

from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from .. import models
from ._helpers import _nullable_float
from .rows import ScanDurationSummaryRow


class _ScanRunsMixin:
    _conn: psycopg.Connection
    _schema: str

    def latest_run_id(self, ticker: str) -> int:
        """Return the most recent *renderable* full-scan run_id for `ticker`, or 0.

        Selection keys on the property the report assembler actually depends
        on — did this run persist its ``aggregates`` payload? — rather than on
        a hand-maintained denylist of side-channel ``notes`` strings.

        Side-channel jobs (``flow_data_refresh``, ``positioning_refresh``,
        ``intraday_refresh``, ``skew_swing_greeks``, ``cockpit_daily_snapshot``,
        ``gex_scan_*``, ``grg_scan``, …) mint a ``scan_runs`` row only to tag
        their UW fetches by ``run_id``; they never call ``set_aggregates``, so
        ``aggregates`` stays NULL. Only a completed full_scan
        (``pipeline.run_single_stock``, line 388) writes it. Keying on
        ``aggregates IS NOT NULL`` is therefore self-enforcing: a *new*
        side-channel job is ignored automatically (no denylist entry to
        remember), and any run that legitimately carries the detail payload is
        eligible automatically. This replaced a per-note denylist that
        re-broke the stock detail page three times (PRs #106, #129, and the
        skew engine — whose ``skew_swing_greeks`` runs, having higher run_ids
        and no denylist entry, shadowed the real full_scan and blanked every
        ticker's detail page after ~17:30 ET each day).

        ``status = 'ok'`` still excludes failed full-scans (e.g. a UW HTTP 429
        daily-quota hit) that commit a ``failed: …`` row with no aggregates.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT run_id FROM {self._schema}.scan_runs "
                "WHERE ticker = %s "
                "  AND status = 'ok' "
                "  AND aggregates IS NOT NULL "
                "  AND aggregates::text NOT IN ('{}', 'null') "
                "ORDER BY run_id DESC LIMIT 1",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def insert_scan_run(self, ticker: str, notes: str = "") -> int:
        sql = (
            f"INSERT INTO {self._schema}.scan_runs (ticker, notes) "
            "VALUES (%s, %s) RETURNING run_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), notes))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def finish_scan_run(self, run_id: int, status: str = "ok") -> None:
        sql = (
            f"UPDATE {self._schema}.scan_runs "
            "SET finished_at = now(), status = %s WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (status, run_id))
        self._conn.commit()

    def get_scan_duration_summary(
        self, start: datetime, end: datetime
    ) -> ScanDurationSummaryRow:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    avg(extract(epoch FROM finished_at - started_at)),
                    percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY extract(epoch FROM finished_at - started_at)
                    )
                FROM {self._schema}.scan_runs
                WHERE finished_at >= %s
                  AND finished_at < %s
                  AND finished_at IS NOT NULL
                  AND started_at IS NOT NULL
                  AND status = 'ok'
                  -- Count only canonical full scans (those that persisted their
                  -- aggregates), the same property latest_run_id keys on. This
                  -- replaces a per-note denylist so fast side-channel jobs
                  -- (skew_swing_greeks, flow_data_refresh, gex_scan_*, …) never
                  -- skew the duration metric, and no future job needs to be
                  -- manually added to a list.
                  AND aggregates IS NOT NULL
                  AND aggregates::text NOT IN ('{{}}', 'null')
                """,
                (start, end),
            )
            row = cur.fetchone()
        return ScanDurationSummaryRow(
            avg_seconds=_nullable_float(row[0]) if row else None,
            p95_seconds=_nullable_float(row[1]) if row else None,
        )

    # ------------------------------------------------------------------
    # advisory locks (single-flight worker jobs)
    # ------------------------------------------------------------------

    def try_advisory_lock(self, key: int) -> bool:
        """Session-scoped ``pg_try_advisory_lock``; returns True if acquired.

        Mirror the precedent in ``api/routers/volatility.py``. Always pair with
        :meth:`release_advisory_lock` in a ``finally`` block.
        """

        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cur.fetchone()
            return bool(row and row[0])

    def release_advisory_lock(self, key: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))

    # ------------------------------------------------------------------
    # external_api_requests
    # ------------------------------------------------------------------

    def count_rows(self, table: str) -> int:
        sql = f"SELECT COUNT(*) FROM {self._schema}.{table}"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def apply_migration(self, sql_text: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql_text)

    # ------------------------------------------------------------------
    # S2: scan_universe + scan_results
    # ------------------------------------------------------------------

    def set_aggregates(self, run_id: int, agg: "models.MarketAggregates") -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET aggregates=%s WHERE run_id=%s",
                (Jsonb(agg.model_dump(mode="json")), run_id),
            )
        self._conn.commit()

    def get_aggregates(self, run_id: int) -> "models.MarketAggregates | None":
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT aggregates FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        return models.MarketAggregates.model_validate(row[0])

    # get_pcr_history_row moved to _MarketDataMixin

    # stock_history_rollup, watchlist count, record health, heartbeat methods moved to _HealthMixin

    # ---- strike_gex_curve (JSONB on scan_runs) ----

    def set_strike_gex_curve(self, run_id: int, curve: list[dict]) -> None:
        """Persist the per-strike, per-expiry GEX curve as JSONB on the run row."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET strike_gex_curve=%s WHERE run_id=%s",
                (Jsonb(curve), run_id),
            )
        self._conn.commit()

    def get_strike_gex_curve(self, run_id: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT strike_gex_curve FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else []

    # get_job moved to _JobsMixin

    # ---- Volatility Tab v2 helpers (spec 2026-05-13) ----
