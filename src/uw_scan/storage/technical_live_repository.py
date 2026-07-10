"""Standalone repository for the technical_live latest-only cache."""

from __future__ import annotations

from datetime import datetime

from psycopg import Connection
from psycopg.types.json import Jsonb


class TechnicalLiveRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert(
        self,
        ticker: str,
        captured_at: datetime,
        spot: float | None,
        spot_source: str | None,
        payload: dict,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO technical_live
                    (ticker, captured_at, spot, spot_source, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    captured_at = EXCLUDED.captured_at,
                    spot        = EXCLUDED.spot,
                    spot_source = EXCLUDED.spot_source,
                    payload     = EXCLUDED.payload,
                    inserted_at = now()
                """,
                (ticker.upper(), captured_at, spot, spot_source, Jsonb(payload)),
            )
        self._conn.commit()

    def fetch(self, ticker: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticker, captured_at, spot, spot_source, payload
                FROM technical_live WHERE ticker = %s
                """,
                (ticker.upper(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "ticker": row[0],
            "captured_at": row[1],
            "spot": row[2],
            "spot_source": row[3],
            "payload": row[4],
        }
