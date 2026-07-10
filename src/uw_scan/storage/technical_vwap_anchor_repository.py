"""Standalone repository for the user-set technical VWAP anchor (one per ticker)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class TechnicalVwapAnchorRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert(self, ticker: str, anchor_date: date, snapshot: list[dict]) -> None:
        """snapshot items must already be JSON-safe (ISO date strings)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO technical_vwap_anchor
                    (ticker, anchor_date, vwap_snapshot)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    anchor_date   = EXCLUDED.anchor_date,
                    vwap_snapshot = EXCLUDED.vwap_snapshot,
                    computed_at   = now()
                """,
                (ticker.upper(), anchor_date, Jsonb(snapshot)),
            )
        self._conn.commit()

    def get(self, ticker: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, anchor_date, vwap_snapshot, computed_at "
                "FROM technical_vwap_anchor WHERE ticker = %s",
                (ticker.upper(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "ticker": row[0],
            "anchor_date": row[1],
            "vwap_snapshot": row[2],
            "computed_at": row[3],
        }

    def delete(self, ticker: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM technical_vwap_anchor WHERE ticker = %s",
                (ticker.upper(),),
            )
        self._conn.commit()
