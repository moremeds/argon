"""VRP harvest markout verdict persistence + earnings-date reconstruction (Spec B)."""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg


class _VrpMarkoutMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_vrp_harvest_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        verdict: str,
        mean_realized_vrp: float | None,
        mean_holdout: float | None,
        rich_cheap_spread: float | None,
        n: int,
        n_holdout: int,
        survives_walkforward: bool,
        survives_window_gate: bool,
        confidence: str | None,
        as_of: _date | None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.vrp_harvest_verdicts "
            "(asset_class, deviation_class, verdict, mean_realized_vrp, mean_holdout, "
            "rich_cheap_spread, n, n_holdout, survives_walkforward, "
            "survives_window_gate, confidence, as_of) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (asset_class, deviation_class) DO UPDATE SET "
            "verdict = EXCLUDED.verdict, "
            "mean_realized_vrp = EXCLUDED.mean_realized_vrp, "
            "mean_holdout = EXCLUDED.mean_holdout, "
            "rich_cheap_spread = EXCLUDED.rich_cheap_spread, "
            "n = EXCLUDED.n, n_holdout = EXCLUDED.n_holdout, "
            "survives_walkforward = EXCLUDED.survives_walkforward, "
            "survives_window_gate = EXCLUDED.survives_window_gate, "
            "confidence = EXCLUDED.confidence, as_of = EXCLUDED.as_of, "
            "inserted_at = now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    asset_class,
                    deviation_class,
                    verdict,
                    mean_realized_vrp,
                    mean_holdout,
                    rich_cheap_spread,
                    n,
                    n_holdout,
                    survives_walkforward,
                    survives_window_gate,
                    confidence,
                    as_of,
                ),
            )

    def fetch_vrp_harvest_verdicts(self) -> list[dict[str, Any]]:
        sql = (
            "SELECT asset_class, deviation_class, verdict, mean_realized_vrp, "
            "mean_holdout, rich_cheap_spread, n, n_holdout, survives_walkforward, "
            "survives_window_gate, confidence, as_of "
            f"FROM {self._schema}.vrp_harvest_verdicts "
            "ORDER BY asset_class, deviation_class"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_known_earnings_dates(self, ticker: str) -> set[_date]:
        """Reconstruct the ticker's earnings calendar from the DISTINCT
        next_earnings_date values flow_events recorded over time. argon has no
        dedicated historical earnings table; each flow_events row carried the
        next-earnings date as known at insert, so the distinct set approximates
        the actual earnings dates seen over the panel window. Coverage is limited
        to tickers that appeared in flow_events; indices return an empty set."""
        sql = (
            f"SELECT DISTINCT next_earnings_date FROM {self._schema}.flow_events "
            "WHERE ticker = %s AND next_earnings_date IS NOT NULL"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            return {row[0] for row in cur.fetchall()}
