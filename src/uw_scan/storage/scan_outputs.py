"""Scan output writes: opportunity_scores."""

from __future__ import annotations

from decimal import Decimal

import psycopg


class _ScanOutputsMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_opportunity_score(
        self,
        run_id: int,
        ticker: str,
        score: Decimal,
        setup_types: list[str],
        direction: str | None,
        confirmations: list[str],
        warnings: list[str],
        notes: str,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.opportunity_scores "
            "(run_id, ticker, score, setup_types, direction, confirmations, "
            "warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING score_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker,
                    score,
                    setup_types,
                    direction,
                    confirmations,
                    warnings,
                    notes,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])
