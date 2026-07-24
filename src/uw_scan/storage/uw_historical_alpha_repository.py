"""Persistence for the UW historical-alpha datasets. New domain — own file.

Standalone repository (NOT composed into `Repository`). Three `(ticker,
market_date)` daily upserts and two append-only insert-ignore event logs.

No method commits internally — the caller (capture wrapper, heal adapter, or
test) owns the transaction, so all writes for one ticker land atomically.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from psycopg import Connection
from psycopg.types.json import Jsonb

_GEX_COLS = (
    "ticker",
    "market_date",
    "call_wall",
    "put_wall",
    "gamma_flip",
    "gamma_magnet",
    "spot",
    "raw_jsonb",
)
_VOL_COLS = (
    "ticker",
    "market_date",
    "anomaly_direction",
    "anomaly_score",
    "vol_character",
    "half_life_days",
    "hurst_rv",
    "vrp_rank",
    "risk_premium",
    "source_mask",
    "raw_jsonb",
)
_SHORT_COLS = (
    "ticker",
    "market_date",
    "short_interest",
    "si_float",
    "si_float_with_synth_long_pct_of_total_shares",
    "days_to_cover",
    "fee_rate",
    "rebate_rate",
    "short_shares_available",
    "total_float",
    "ftd_quantity",
    "short_volume",
    "total_volume",
    "short_volume_ratio",
    "raw_jsonb",
)
_DARK_LIT_COLS = (
    "source",
    "tracking_id",
    "ticker",
    "executed_at",
    "market_date",
    "price",
    "size",
    "premium",
    "market_center",
    "nbbo_bid",
    "nbbo_ask",
    "nbbo_bid_quantity",
    "nbbo_ask_quantity",
    "sale_cond_codes",
    "trade_code",
    "raw_jsonb",
)
_INTRADAY_COLS = (
    "ticker",
    "market_date",
    "ts",
    "source",
    "expiry",
    "net_call_premium",
    "net_put_premium",
    "net_delta",
    "call_volume",
    "put_volume",
    "dir_delta_flow",
    "dir_vega_flow",
    "otm_dir_delta_flow",
    "otm_dir_vega_flow",
    "transactions",
    "volume",
    "raw_jsonb",
)


class UwHistoricalAlphaRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    # -- generic writer -------------------------------------------------- #
    def _write(
        self,
        table: str,
        cols: Sequence[str],
        params: list[dict],
        conflict_cols: Sequence[str],
        *,
        update: bool,
    ) -> int:
        # table/cols are hardcoded module constants — no value is f-strung.
        if not params:
            return 0
        collist = ", ".join(cols)
        values = ", ".join(f"%({c})s" for c in cols)
        keys = set(conflict_cols)
        if update:
            setters = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in keys)
            conflict = (
                f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET "
                f"{setters}, fetched_at=now()"
            )
        else:
            conflict = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        sql = f"INSERT INTO {table} ({collist}) VALUES ({values}) {conflict}"
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    @staticmethod
    def _row(cols: Sequence[str], r: dict) -> dict:
        p = {c: r.get(c) for c in cols}
        if "ticker" in p and p.get("ticker"):
            p["ticker"] = str(p["ticker"]).upper()
        p["raw_jsonb"] = Jsonb(r.get("raw_jsonb") or {})
        return p

    # -- daily upserts --------------------------------------------------- #
    def upsert_gex_levels(self, rows: Iterable[dict]) -> int:
        params = [self._row(_GEX_COLS, r) for r in rows]
        return self._write(
            "uw_gex_levels_daily",
            _GEX_COLS,
            params,
            ("ticker", "market_date"),
            update=True,
        )

    def upsert_volatility_signal(self, rows: Iterable[dict]) -> int:
        params = []
        for r in rows:
            p = self._row(_VOL_COLS, r)
            p["source_mask"] = list(r.get("source_mask") or [])
            params.append(p)
        return self._write(
            "uw_volatility_signal_daily",
            _VOL_COLS,
            params,
            ("ticker", "market_date"),
            update=True,
        )

    def upsert_short_pressure(self, rows: Iterable[dict]) -> int:
        params = [self._row(_SHORT_COLS, r) for r in rows]
        return self._write(
            "uw_short_pressure_daily",
            _SHORT_COLS,
            params,
            ("ticker", "market_date"),
            update=True,
        )

    # -- append-only event logs ----------------------------------------- #
    def insert_dark_lit_prints(self, rows: Iterable[dict]) -> int:
        # psycopg adapts a Python list -> TEXT[] natively (sale_cond_codes).
        params = []
        for r in rows:
            p = self._row(_DARK_LIT_COLS, r)
            p["tracking_id"] = str(r["tracking_id"])
            params.append(p)
        return self._write(
            "uw_dark_lit_flow_prints",
            _DARK_LIT_COLS,
            params,
            ("source", "tracking_id"),
            update=False,
        )

    def insert_intraday_flow_bars(self, rows: Iterable[dict]) -> int:
        params = [self._row(_INTRADAY_COLS, r) for r in rows]
        return self._write(
            "uw_intraday_option_flow_bars",
            _INTRADAY_COLS,
            params,
            ("ticker", "market_date", "ts", "source", "expiry"),
            update=False,
        )
