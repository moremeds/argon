"""Persistence for backtest harness sweep runs/results (migration 095). New
domain — own file (never appended to repository.py)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class BacktestRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def create_run(
        self,
        *,
        strategy: str,
        reproduce_cmd: str,
        params_grid: dict | None = None,
        git_sha: str | None = None,
        data_start: date | None = None,
        data_end: date | None = None,
        notes: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO backtest_sweep_runs
                (strategy, reproduce_cmd, params_grid, git_sha,
                 data_start, data_end, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    strategy,
                    reproduce_cmd,
                    Jsonb(params_grid) if params_grid is not None else None,
                    git_sha,
                    data_start,
                    data_end,
                    notes,
                ),
            )
            run_id = cur.fetchone()[0]
        self._conn.commit()
        return int(run_id)

    def insert_result(
        self,
        run_id: int,
        *,
        config: dict,
        metrics: dict | None = None,
        gates: dict | None = None,
        n_trades: int | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO backtest_sweep_results
                (run_id, config, metrics, gates, n_trades, status, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    Jsonb(config),
                    Jsonb(metrics) if metrics is not None else None,
                    Jsonb(gates) if gates is not None else None,
                    n_trades,
                    status,
                    error,
                ),
            )
            rid = cur.fetchone()[0]
        self._conn.commit()
        return int(rid)

    def complete_run(
        self, run_id: int, *, status: str = "completed", error: str | None = None
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE backtest_sweep_runs SET status = %s, error = %s WHERE id = %s",
                (status, error, run_id),
            )
        self._conn.commit()

    def fetch_run_results(self, run_id: int) -> list[dict]:
        sql = """
            SELECT id, created_at, config, metrics, gates, n_trades, status, error
              FROM backtest_sweep_results
             WHERE run_id = %s
             ORDER BY id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
