"""WS consumer heartbeat + activity counters for api.massive.com WebSocket."""

from __future__ import annotations

from datetime import datetime

import psycopg

from .rows import WsConsumerStateRow


class _WsConsumerStateMixin:
    _conn: psycopg.Connection
    _schema: str

    def get_ws_consumer_state(self) -> WsConsumerStateRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT last_tick_at, last_flush_at, ticks_received, ticks_flushed,
                       connection_started_at, last_error, last_error_at, updated_at
                FROM {self._schema}.ws_consumer_state
                WHERE id = 1
                """
            )
            row = cur.fetchone()
            return WsConsumerStateRow(*row) if row else None

    def record_ws_heartbeat(
        self,
        *,
        last_tick_at: datetime | None,
        last_flush_at: datetime,
        ticks_received_delta: int,
        ticks_flushed_delta: int,
    ) -> None:
        """Does NOT commit — caller controls the transaction so heartbeat
        + bulk upserts share atomicity. The WS writer wraps all three writes
        in one ``with self._conn.transaction():`` block."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET last_tick_at  = COALESCE(%s, last_tick_at),
                    last_flush_at = %s,
                    ticks_received = ticks_received + %s,
                    ticks_flushed  = ticks_flushed  + %s,
                    updated_at = NOW()
                WHERE id = 1
                """,
                (
                    last_tick_at,
                    last_flush_at,
                    ticks_received_delta,
                    ticks_flushed_delta,
                ),
            )

    def record_ws_connection_started(self, started_at: datetime) -> None:
        """Does NOT commit — caller controls."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET connection_started_at = %s,
                    last_error = NULL,
                    last_error_at = NULL,
                    updated_at = NOW()
                WHERE id = 1
                """,
                (started_at,),
            )

    def record_ws_error(self, message: str, error_at: datetime) -> None:
        """Does NOT commit — caller controls."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET last_error = %s, last_error_at = %s, updated_at = NOW()
                WHERE id = 1
                """,
                (message[:1000], error_at),
            )
