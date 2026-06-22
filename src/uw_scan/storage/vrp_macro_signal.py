"""VRP macro short-vol signal daily-snapshot persistence (Layer-3 of
reports/vrp_macro_signal.py). One row per (name, snapshot_date)."""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_COLUMNS = (
    "name",
    "snapshot_date",
    "as_of",
    "spot",
    "iv",
    "rv20",
    "vrp",
    "vrp_z",
    "weight",
    "action",
    "short_put",
    "long_put",
    "put_width",
    "credit",
    "max_loss",
    "hold_days",
    "short_delta",
    "wing_delta",
    "bt_n",
    "bt_sharpe",
    "bt_maxdd",
    "bt_annror",
    "bt_calmar",
    "config_jsonb",
)


class _VrpMacroSignalMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_vrp_macro_signal(
        self,
        *,
        name: str,
        snapshot_date: _date,
        as_of: _date,
        spot: float,
        iv: float,
        rv20: float | None,
        vrp: float | None,
        vrp_z: float | None,
        weight: float,
        action: str,
        short_put: float | None,
        long_put: float | None,
        put_width: float | None,
        credit: float | None,
        max_loss: float | None,
        hold_days: int,
        short_delta: float,
        wing_delta: float,
        bt_n: int | None,
        bt_sharpe: float | None,
        bt_maxdd: float | None,
        bt_annror: float | None,
        bt_calmar: float | None,
        config: dict[str, Any] | None,
    ) -> None:
        """Insert/update the (name, snapshot_date) signal snapshot. Idempotent —
        re-running the job same-day overwrites the row in place."""
        placeholders = ", ".join(["%s"] * len(_COLUMNS))
        cols = ", ".join(_COLUMNS)
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _COLUMNS
            if c not in ("name", "snapshot_date")
        )
        sql = (
            f"INSERT INTO {self._schema}.vrp_macro_signal_daily ({cols}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (name, snapshot_date) DO UPDATE SET "
            f"{updates}, created_at = now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    name,
                    snapshot_date,
                    as_of,
                    spot,
                    iv,
                    rv20,
                    vrp,
                    vrp_z,
                    weight,
                    action,
                    short_put,
                    long_put,
                    put_width,
                    credit,
                    max_loss,
                    hold_days,
                    short_delta,
                    wing_delta,
                    bt_n,
                    bt_sharpe,
                    bt_maxdd,
                    bt_annror,
                    bt_calmar,
                    Jsonb(config) if config is not None else None,
                ),
            )

    def fetch_latest_vrp_macro_signals(
        self, names: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Latest snapshot per name (one row each), newest first by name. Pass
        `names` to restrict; None returns every tracked name."""
        select_cols = ", ".join(_COLUMNS) + ", created_at"
        where = ""
        params: tuple[Any, ...] = ()
        if names:
            where = "WHERE name = ANY(%s) "
            params = ([n.upper() for n in names],)
        sql = (
            f"SELECT DISTINCT ON (name) {select_cols} "
            f"FROM {self._schema}.vrp_macro_signal_daily "
            f"{where}"
            "ORDER BY name, snapshot_date DESC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            keys = [d.name for d in cur.description or []]
            return [dict(zip(keys, row, strict=False)) for row in cur.fetchall()]
