"""Long-weekend UW historical backfill for high-value date-addressable datasets.

This is an operator script for macmini runs. It is intentionally resumable:
existing ticker-date/date cells are skipped before calling UW, and every useful
result is committed in small units so an interrupted run can continue.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Jsonb

from uw_scan.config import Settings
from uw_scan.worker.market_session import is_us_equity_market_day

DATASETS = (
    "market_tide",
    "top_net_impact",
    "gex_levels",
    "oi_change",
    "oi_by_strike",
    "flow_bars",
    "dark_lit",
)

DATE_DATASETS = {"market_tide", "top_net_impact"}
TICKER_DATE_DATASETS = set(DATASETS) - DATE_DATASETS


class Budget:
    def __init__(self, max_uw_calls: int) -> None:
        self.max_uw_calls = max_uw_calls
        self.used = 0
        self.daily_count: int | None = None
        self.daily_limit: int | None = None
        self.minute_remaining: int | None = None
        self.stopped_reason: str | None = None

    def absorb(self, headers: httpx.Headers) -> None:
        self.used += 1
        self.daily_count = _int_or_none(headers.get("x-uw-daily-req-count"))
        self.daily_limit = _int_or_none(headers.get("x-uw-token-req-limit"))
        self.minute_remaining = _int_or_none(headers.get("x-uw-req-per-minute-remaining"))

    def can_call(self) -> bool:
        if self.used >= self.max_uw_calls:
            self.stopped_reason = "run_call_cap"
            return False
        if self.daily_count is not None and self.daily_count >= self.max_uw_calls:
            self.stopped_reason = "daily_call_cap"
            return False
        if (
            self.daily_count is not None
            and self.daily_limit is not None
            and self.daily_count >= self.daily_limit
        ):
            self.stopped_reason = "provider_daily_limit"
            return False
        return True


class UwDirectClient:
    def __init__(self, settings: Settings, budget: Budget) -> None:
        self._budget = budget
        self._client = httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self._budget.can_call():
            return None
        if self._budget.minute_remaining is not None and self._budget.minute_remaining < 5:
            time.sleep(2)
        resp = self._client.get(path, params=params or {})
        self._budget.absorb(resp.headers)
        if resp.status_code == 429:
            time.sleep(10)
            raise RuntimeError(f"UW 429 path={path}")
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"message": resp.text[:240]}
            code = body.get("code") if isinstance(body, dict) else None
            if resp.status_code in (400, 422) or code == "historic_data_access_missing":
                return {"data": [], "_no_data_status": resp.status_code, "_no_data_code": code}
            text = json.dumps(body, default=str)[:240].replace("\n", " ")
            raise RuntimeError(f"UW HTTP {resp.status_code} path={path} body={text}")
        return resp.json()


class RunStats:
    def __init__(self) -> None:
        self.rows: dict[str, int] = {}
        self.skipped_existing: dict[str, int] = {}
        self.no_data: dict[str, int] = {}
        self.errors: list[str] = []

    def add_rows(self, dataset: str, n: int) -> None:
        self.rows[dataset] = self.rows.get(dataset, 0) + n

    def add_skip(self, dataset: str, n: int = 1) -> None:
        self.skipped_existing[dataset] = self.skipped_existing.get(dataset, 0) + n

    def add_no_data(self, dataset: str, n: int = 1) -> None:
        self.no_data[dataset] = self.no_data.get(dataset, 0) + n


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _ts(value: Any, fallback_date: date | None = None) -> datetime | None:
    if value:
        text = str(value).replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(text)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return ts
        except ValueError:
            pass
    if fallback_date is not None:
        return datetime(fallback_date.year, fallback_date.month, fallback_date.day, tzinfo=UTC)
    return None


def _data(body: dict[str, Any] | None) -> Any:
    if not body:
        return None
    return body.get("data", body)


def _codes(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def market_sessions(start: date, end: date) -> list[date]:
    out: list[date] = []
    current = start
    while current <= end:
        if is_us_equity_market_day(current):
            out.append(current)
        current += timedelta(days=1)
    return out


def estimate_requests(
    datasets: list[str], *, ticker_count: int, session_count: int
) -> dict[str, int]:
    out: dict[str, int] = {}
    for dataset in datasets:
        if dataset in DATE_DATASETS:
            out[dataset] = session_count
        elif dataset in {"gex_levels", "oi_change", "oi_by_strike"}:
            out[dataset] = ticker_count * session_count
        elif dataset in {"flow_bars", "dark_lit"}:
            out[dataset] = ticker_count * session_count * 2
        else:
            raise ValueError(f"unknown dataset: {dataset}")
    out["total_estimated_requests"] = sum(out.values())
    return out


def _load_tickers(conn: psycopg.Connection, schema: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker
              FROM {schema}.watchlist
             WHERE removed_at IS NULL
             ORDER BY sort_rank, ticker
            """
        )
        return [str(r[0]).upper() for r in cur.fetchall()]


def _insert_scan_run(conn: psycopg.Connection, schema: str, ticker: str, notes: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {schema}.scan_runs (ticker, notes) VALUES (%s, %s) RETURNING run_id",
            (ticker, notes),
        )
        return int(cur.fetchone()[0])


def _finish_scan_run(
    conn: psycopg.Connection, schema: str, run_id: int, status: str = "ok"
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {schema}.scan_runs SET finished_at=now(), status=%s WHERE run_id=%s",
            (status, run_id),
        )


def _existing_date_cells(conn: psycopg.Connection, schema: str, dataset: str) -> set[date]:
    table_col = {
        "market_tide": ("market_tide_snapshots", "data_date"),
        "top_net_impact": ("top_net_impact_snapshots", "data_date"),
    }[dataset]
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {table_col[1]} FROM {schema}.{table_col[0]}")
        return {r[0] for r in cur.fetchall()}


def _existing_ticker_date_cells(
    conn: psycopg.Connection, schema: str, dataset: str
) -> set[tuple[str, date]]:
    query = {
        "gex_levels": f"SELECT ticker, market_date FROM {schema}.uw_gex_levels_daily",
        "oi_change": f"SELECT underlying_symbol, curr_date FROM {schema}.oi_change_events",
        "oi_by_strike": f"SELECT ticker, market_date FROM {schema}.oi_by_strike",
        "flow_bars": f"SELECT ticker, market_date FROM {schema}.uw_intraday_option_flow_bars",
        "dark_lit": f"SELECT ticker, market_date FROM {schema}.uw_dark_lit_flow_prints",
    }[dataset]
    with conn.cursor() as cur:
        cur.execute(query)
        return {(str(r[0]).upper(), r[1]) for r in cur.fetchall() if r[1] is not None}


def _upsert_market_tide(
    conn: psycopg.Connection, schema: str, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.market_tide_snapshots
                (data_date, ts, net_call_premium, net_put_premium, net_volume)
            VALUES (%(data_date)s, %(ts)s, %(net_call_premium)s,
                    %(net_put_premium)s, %(net_volume)s)
            ON CONFLICT (data_date, ts) DO UPDATE SET
                net_call_premium = EXCLUDED.net_call_premium,
                net_put_premium = EXCLUDED.net_put_premium,
                net_volume = EXCLUDED.net_volume
            """,
            rows,
        )
    return len(rows)


def _upsert_top_net_impact(
    conn: psycopg.Connection, schema: str, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.top_net_impact_snapshots
                (data_date, ticker, net_premium, rank, prev_rank)
            VALUES (%(data_date)s, %(ticker)s, %(net_premium)s, %(rank)s, NULL)
            ON CONFLICT (data_date, ticker) DO UPDATE SET
                prev_rank = {schema}.top_net_impact_snapshots.rank,
                rank = EXCLUDED.rank,
                net_premium = EXCLUDED.net_premium,
                captured_at = now()
            """,
            rows,
        )
    return len(rows)


def _upsert_gex_level(
    conn: psycopg.Connection,
    schema: str,
    ticker: str,
    market_date: date,
    row: dict[str, Any],
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.uw_gex_levels_daily (
                ticker, market_date, call_wall, put_wall,
                gamma_flip, gamma_magnet, raw_jsonb
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, market_date) DO UPDATE SET
                call_wall = EXCLUDED.call_wall,
                put_wall = EXCLUDED.put_wall,
                gamma_flip = EXCLUDED.gamma_flip,
                gamma_magnet = EXCLUDED.gamma_magnet,
                raw_jsonb = EXCLUDED.raw_jsonb,
                fetched_at = now()
            """,
            (
                ticker,
                market_date,
                _dec(row.get("call_wall")),
                _dec(row.get("put_wall")),
                _dec(row.get("gamma_flip")),
                _dec(row.get("gamma_magnet")),
                Jsonb(row),
            ),
        )
    return 1


def _upsert_oi_by_strike(
    conn: psycopg.Connection,
    schema: str,
    ticker: str,
    rows: list[dict[str, Any]],
) -> int:
    params = []
    for row in rows:
        dt = _date(row.get("date"))
        strike = _dec(row.get("strike"))
        if dt is None or strike is None:
            continue
        params.append((ticker, dt, strike, _int(row.get("call_oi")), _int(row.get("put_oi"))))
    if not params:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.oi_by_strike
                (ticker, market_date, strike, call_oi, put_oi)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, market_date, strike) DO UPDATE SET
                call_oi = EXCLUDED.call_oi,
                put_oi = EXCLUDED.put_oi
            """,
            params,
        )
    return len(params)


def _replace_oi_change(
    conn: psycopg.Connection,
    schema: str,
    run_id: int,
    ticker: str,
    curr_date: date,
    rows: list[dict[str, Any]],
) -> int:
    params = []
    for row in rows:
        curr_date = _date(row.get("curr_date"))
        option_symbol = row.get("option_symbol")
        underlying = row.get("underlying_symbol")
        if curr_date is None or not option_symbol or not underlying:
            continue
        params.append(
            (
                run_id,
                str(underlying).upper(),
                str(option_symbol).upper(),
                curr_date,
                _date(row.get("last_date")),
                _int(row.get("curr_oi")),
                _int(row.get("last_oi")),
                _int(row.get("oi_diff_plain")),
                _dec(row.get("oi_change")),
                _int(row.get("volume")),
                _int(row.get("trades")),
                _dec(row.get("avg_price")),
                _dec(row.get("last_fill")),
                _int(row.get("days_of_oi_increases")),
                _int(row.get("days_of_vol_greater_than_oi")),
                _dec(row.get("percentage_of_total")),
                _int(row.get("rnk")),
                _int(row.get("prev_ask_volume")),
                _int(row.get("prev_bid_volume")),
                _int(row.get("prev_mid_volume")),
                _int(row.get("prev_neutral_volume")),
                _int(row.get("prev_multi_leg_volume")),
                _int(row.get("prev_stock_multi_leg_volume")),
                _dec(row.get("prev_total_premium")),
                _dec(row.get("last_ask")),
                _dec(row.get("last_bid")),
            )
        )
    if not params:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {schema}.oi_change_events "
            "WHERE underlying_symbol = %s AND curr_date = %s",
            (ticker, curr_date),
        )
        cur.executemany(
            f"""
            INSERT INTO {schema}.oi_change_events (
                run_id, underlying_symbol, option_symbol, curr_date, last_date,
                curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades,
                avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi,
                percentage_of_total, rnk,
                prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume,
                prev_multi_leg_volume, prev_stock_multi_leg_volume,
                prev_total_premium, last_ask, last_bid
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, option_symbol) DO NOTHING
            """,
            params,
        )
    return len(params)


def _flow_ts(row: dict[str, Any], fallback_date: date) -> datetime | None:
    for key in ("timestamp", "tape_time", "time", "created_at", "date"):
        ts = _ts(row.get(key), fallback_date)
        if ts:
            return ts
    return None


def _upsert_flow_bars(
    conn: psycopg.Connection,
    schema: str,
    ticker: str,
    market_date: date,
    source: str,
    rows: list[dict[str, Any]],
) -> int:
    params = []
    for row in rows:
        ts = _flow_ts(row, market_date)
        if ts is None:
            continue
        params.append(
            (
                ticker,
                market_date,
                ts,
                source,
                _date(row.get("expiry")) or date(1, 1, 1),
                _dec(row.get("net_call_premium")),
                _dec(row.get("net_put_premium")),
                _dec(row.get("net_delta")),
                _int(row.get("call_volume")),
                _int(row.get("put_volume")),
                _dec(row.get("dir_delta_flow")),
                _dec(row.get("dir_vega_flow")),
                _dec(row.get("otm_dir_delta_flow")),
                _dec(row.get("otm_dir_vega_flow")),
                _int(row.get("transactions")),
                _int(row.get("volume")),
                Jsonb(row),
            )
        )
    if not params:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.uw_intraday_option_flow_bars (
                ticker, market_date, ts, source, expiry,
                net_call_premium, net_put_premium, net_delta,
                call_volume, put_volume, dir_delta_flow,
                dir_vega_flow, otm_dir_delta_flow,
                otm_dir_vega_flow, transactions, volume, raw_jsonb
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, market_date, ts, source, expiry) DO UPDATE SET
                net_call_premium = EXCLUDED.net_call_premium,
                net_put_premium = EXCLUDED.net_put_premium,
                net_delta = EXCLUDED.net_delta,
                call_volume = EXCLUDED.call_volume,
                put_volume = EXCLUDED.put_volume,
                dir_delta_flow = EXCLUDED.dir_delta_flow,
                dir_vega_flow = EXCLUDED.dir_vega_flow,
                otm_dir_delta_flow = EXCLUDED.otm_dir_delta_flow,
                otm_dir_vega_flow = EXCLUDED.otm_dir_vega_flow,
                transactions = EXCLUDED.transactions,
                volume = EXCLUDED.volume,
                raw_jsonb = EXCLUDED.raw_jsonb,
                fetched_at = now()
            """,
            params,
        )
    return len(params)


def _upsert_dark_lit(
    conn: psycopg.Connection,
    schema: str,
    ticker: str,
    market_date: date,
    source: str,
    rows: list[dict[str, Any]],
) -> int:
    params = []
    for row in rows:
        executed_at = _ts(row.get("executed_at"), market_date)
        tracking_id = row.get("tracking_id") or row.get("id")
        if executed_at is None or not tracking_id:
            continue
        params.append(
            (
                source,
                str(tracking_id),
                ticker,
                executed_at,
                market_date,
                _dec(row.get("price")),
                _int(row.get("size")),
                _dec(row.get("premium")),
                row.get("market_center"),
                _dec(row.get("nbbo_bid")),
                _dec(row.get("nbbo_ask")),
                _int(row.get("nbbo_bid_quantity")),
                _int(row.get("nbbo_ask_quantity")),
                _codes(row.get("sale_cond_codes")),
                row.get("trade_code"),
                Jsonb(row),
            )
        )
    if not params:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.uw_dark_lit_flow_prints (
                source, tracking_id, ticker, executed_at, market_date,
                price, size, premium, market_center, nbbo_bid,
                nbbo_ask, nbbo_bid_quantity, nbbo_ask_quantity,
                sale_cond_codes, trade_code, raw_jsonb
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, tracking_id) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                executed_at = EXCLUDED.executed_at,
                market_date = EXCLUDED.market_date,
                price = EXCLUDED.price,
                size = EXCLUDED.size,
                premium = EXCLUDED.premium,
                market_center = EXCLUDED.market_center,
                nbbo_bid = EXCLUDED.nbbo_bid,
                nbbo_ask = EXCLUDED.nbbo_ask,
                nbbo_bid_quantity = EXCLUDED.nbbo_bid_quantity,
                nbbo_ask_quantity = EXCLUDED.nbbo_ask_quantity,
                sale_cond_codes = EXCLUDED.sale_cond_codes,
                trade_code = EXCLUDED.trade_code,
                raw_jsonb = EXCLUDED.raw_jsonb,
                fetched_at = now()
            """,
            params,
        )
    return len(params)


def backfill_market_tide(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "market_tide"
    existing = _existing_date_cells(conn, schema, dataset)
    for dt in sessions:
        if not uw._budget.can_call():
            return
        if dt in existing:
            stats.add_skip(dataset)
            continue
        try:
            body = uw.get("/api/market/market-tide", {"date": dt.isoformat()})
            rows = []
            for row in _data(body) or []:
                rows.append(
                    {
                        "data_date": _date(row.get("date")) or dt,
                        "ts": _ts(row.get("timestamp"), dt),
                        "net_call_premium": _dec(row.get("net_call_premium")),
                        "net_put_premium": _dec(row.get("net_put_premium")),
                        "net_volume": _int(row.get("net_volume")),
                    }
                )
            rows = [r for r in rows if r["ts"] is not None]
            n = _upsert_market_tide(conn, schema, rows)
            conn.commit()
            stats.add_rows(dataset, n)
            if n == 0:
                stats.add_no_data(dataset)
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            stats.errors.append(f"{dataset} {dt}: {exc}")
    print(f"{dataset} calls={uw._budget.used}", flush=True)


def backfill_top_net_impact(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "top_net_impact"
    existing = _existing_date_cells(conn, schema, dataset)
    for dt in sessions:
        if not uw._budget.can_call():
            return
        if dt in existing:
            stats.add_skip(dataset)
            continue
        try:
            body = uw.get("/api/market/top-net-impact", {"date": dt.isoformat(), "limit": 100})
            rows = []
            for idx, row in enumerate(_data(body) or [], start=1):
                ticker = row.get("ticker")
                if not ticker:
                    continue
                rows.append(
                    {
                        "data_date": dt,
                        "ticker": str(ticker).upper(),
                        "net_premium": _dec(row.get("net_premium")),
                        "rank": idx,
                    }
                )
            n = _upsert_top_net_impact(conn, schema, rows)
            conn.commit()
            stats.add_rows(dataset, n)
            if n == 0:
                stats.add_no_data(dataset)
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            stats.errors.append(f"{dataset} {dt}: {exc}")
    print(f"{dataset} calls={uw._budget.used}", flush=True)


def backfill_gex_levels(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "gex_levels"
    existing = _existing_ticker_date_cells(conn, schema, dataset)
    for ticker in tickers:
        for dt in sessions:
            if not uw._budget.can_call():
                return
            if (ticker, dt) in existing:
                stats.add_skip(dataset)
                continue
            try:
                body = uw.get(f"/api/stock/{ticker}/gex-levels", {"date": dt.isoformat()})
                data = _data(body) or {}
                if not data:
                    stats.add_no_data(dataset)
                    continue
                n = _upsert_gex_level(conn, schema, ticker, dt, data)
                conn.commit()
                stats.add_rows(dataset, n)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                stats.errors.append(f"{dataset} {ticker} {dt}: {exc}")
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def backfill_oi_change(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "oi_change"
    existing = _existing_ticker_date_cells(conn, schema, dataset)
    for ticker in tickers:
        for dt in sessions:
            if not uw._budget.can_call():
                return
            if (ticker, dt) in existing:
                stats.add_skip(dataset)
                continue
            run_id: int | None = None
            try:
                body = uw.get(f"/api/stock/{ticker}/oi-change", {"date": dt.isoformat(), "limit": 50})
                rows = _data(body) or []
                if not rows:
                    stats.add_no_data(dataset)
                    continue
                run_id = _insert_scan_run(conn, schema, ticker, f"oi_change_history_backfill {dt}")
                n = _replace_oi_change(conn, schema, run_id, ticker, dt, rows)
                _finish_scan_run(conn, schema, run_id)
                conn.commit()
                stats.add_rows(dataset, n)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                stats.errors.append(f"{dataset} {ticker} {dt}: {exc}")
                if run_id is not None:
                    try:
                        _finish_scan_run(conn, schema, run_id, "failed")
                        conn.commit()
                    except Exception:
                        conn.rollback()
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def backfill_oi_by_strike(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "oi_by_strike"
    existing = _existing_ticker_date_cells(conn, schema, dataset)
    for ticker in tickers:
        for dt in sessions:
            if not uw._budget.can_call():
                return
            if (ticker, dt) in existing:
                stats.add_skip(dataset)
                continue
            try:
                body = uw.get(f"/api/stock/{ticker}/oi-per-strike", {"date": dt.isoformat()})
                rows = _data(body) or []
                n = _upsert_oi_by_strike(conn, schema, ticker, rows)
                conn.commit()
                stats.add_rows(dataset, n)
                if n == 0:
                    stats.add_no_data(dataset)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                stats.errors.append(f"{dataset} {ticker} {dt}: {exc}")
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def backfill_flow_bars(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "flow_bars"
    existing = _existing_ticker_date_cells(conn, schema, dataset)
    endpoints = (
        ("net_prem_ticks", "/api/stock/{ticker}/net-prem-ticks"),
        ("greek_flow", "/api/stock/{ticker}/greek-flow"),
    )
    for ticker in tickers:
        for dt in sessions:
            if (ticker, dt) in existing:
                stats.add_skip(dataset)
                continue
            wrote = 0
            for source, path_template in endpoints:
                if not uw._budget.can_call():
                    return
                try:
                    body = uw.get(path_template.format(ticker=ticker), {"date": dt.isoformat()})
                    rows = _data(body) or []
                    wrote += _upsert_flow_bars(conn, schema, ticker, dt, source, rows)
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    stats.errors.append(f"{dataset} {ticker} {dt} {source}: {exc}")
            stats.add_rows(dataset, wrote)
            if wrote == 0:
                stats.add_no_data(dataset)
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def backfill_dark_lit(
    conn: psycopg.Connection,
    schema: str,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "dark_lit"
    existing = _existing_ticker_date_cells(conn, schema, dataset)
    endpoints = (
        ("darkpool", "/api/darkpool/{ticker}"),
        ("lit_flow", "/api/lit-flow/{ticker}"),
    )
    for ticker in tickers:
        for dt in sessions:
            if (ticker, dt) in existing:
                stats.add_skip(dataset)
                continue
            wrote = 0
            for source, path_template in endpoints:
                if not uw._budget.can_call():
                    return
                try:
                    body = uw.get(
                        path_template.format(ticker=ticker),
                        {"date": dt.isoformat(), "limit": 500},
                    )
                    rows = _data(body) or []
                    wrote += _upsert_dark_lit(conn, schema, ticker, dt, source, rows)
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    stats.errors.append(f"{dataset} {ticker} {dt} {source}: {exc}")
            stats.add_rows(dataset, wrote)
            if wrote == 0:
                stats.add_no_data(dataset)
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def coverage(
    conn: psycopg.Connection,
    schema: str,
    datasets: list[str],
    sessions: list[date],
    tickers: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dataset in datasets:
        if dataset == "market_tide":
            table, date_col, expected = "market_tide_snapshots", "data_date", len(sessions)
            sql = f"SELECT count(DISTINCT {date_col}), min({date_col}), max({date_col}), count(*) FROM {schema}.{table} WHERE {date_col} BETWEEN %s AND %s"
            args = (sessions[0], sessions[-1])
        elif dataset == "top_net_impact":
            table, date_col, expected = "top_net_impact_snapshots", "data_date", len(sessions)
            sql = f"SELECT count(DISTINCT {date_col}), min({date_col}), max({date_col}), count(*) FROM {schema}.{table} WHERE {date_col} BETWEEN %s AND %s"
            args = (sessions[0], sessions[-1])
        else:
            expected = len(tickers) * len(sessions)
            if dataset == "gex_levels":
                table, ticker_col, date_col = "uw_gex_levels_daily", "ticker", "market_date"
            elif dataset == "oi_change":
                table, ticker_col, date_col = "oi_change_events", "underlying_symbol", "curr_date"
            elif dataset == "oi_by_strike":
                table, ticker_col, date_col = "oi_by_strike", "ticker", "market_date"
            elif dataset == "flow_bars":
                table, ticker_col, date_col = "uw_intraday_option_flow_bars", "ticker", "market_date"
            elif dataset == "dark_lit":
                table, ticker_col, date_col = "uw_dark_lit_flow_prints", "ticker", "market_date"
            else:
                raise ValueError(dataset)
            sql = f"""
                SELECT count(DISTINCT ({ticker_col}, {date_col})),
                       min({date_col}), max({date_col}), count(*)
                  FROM {schema}.{table}
                 WHERE {ticker_col} = ANY(%s)
                   AND {date_col} BETWEEN %s AND %s
            """
            args = (tickers, sessions[0], sessions[-1])
        with conn.cursor() as cur:
            cur.execute(sql, args)
            covered, min_dt, max_dt, rows = cur.fetchone()
        covered_i = int(covered or 0)
        out.append(
            {
                "dataset": dataset,
                "expected_cells": expected,
                "covered_cells": covered_i,
                "coverage_pct": round((covered_i / expected) * 100, 2) if expected else 0,
                "rows": int(rows or 0),
                "min_date": str(min_dt) if min_dt else None,
                "max_date": str(max_dt) if max_dt else None,
            }
        )
    return out


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "audit", "execute", "verify"))
    parser.add_argument("--datasets", default=os.environ.get("UW_LONG_WEEKEND_DATASETS", ",".join(DATASETS)))
    parser.add_argument("--start", default=os.environ.get("UW_LONG_WEEKEND_START", "2023-08-03"))
    parser.add_argument("--end", default=os.environ.get("UW_LONG_WEEKEND_END", "2025-12-31"))
    parser.add_argument("--max-uw-calls", type=int, default=int(os.environ.get("UW_LONG_WEEKEND_MAX_UW_CALLS", "118000")))
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output-dir", default="/tmp/uw-long-weekend-history")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    unknown = sorted(set(datasets) - set(DATASETS))
    if unknown:
        raise SystemExit(f"unknown datasets: {unknown}")
    start = _date(args.start)
    end = _date(args.end)
    if start is None or end is None:
        raise SystemExit("invalid --start/--end")
    sessions = market_sessions(start, end)
    if not sessions:
        raise SystemExit("no market sessions in range")
    settings = Settings.from_env()
    out_dir = Path(args.output_dir)
    stats = RunStats()
    budget = Budget(args.max_uw_calls)

    with psycopg.connect(settings.db_dsn()) as conn:
        tickers = _load_tickers(conn, settings.db_schema)
        request_plan = {
            "checked_at": datetime.now(UTC).isoformat(),
            "start": str(sessions[0]),
            "end": str(sessions[-1]),
            "tickers": len(tickers),
            "sessions": len(sessions),
            "datasets": datasets,
            "request_estimate": estimate_requests(
                datasets, ticker_count=len(tickers), session_count=len(sessions)
            ),
        }
        if args.command == "plan":
            print(json.dumps(request_plan, indent=2, sort_keys=True))
            write_report(out_dir / "request-plan.json", request_plan)
            return 0
        if args.command in {"audit", "verify"}:
            payload = {
                "checked_at": datetime.now(UTC).isoformat(),
                "request_plan": request_plan,
                "coverage": coverage(conn, settings.db_schema, datasets, sessions, tickers),
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            write_report(out_dir / "coverage-report.json", payload)
            return 0
        if args.command == "execute":
            if not args.confirm:
                raise SystemExit("execute requires --confirm")
            uw = UwDirectClient(settings, budget)
            try:
                for dataset in datasets:
                    if not budget.can_call():
                        break
                    if dataset == "market_tide":
                        backfill_market_tide(conn, settings.db_schema, uw, sessions, stats)
                    elif dataset == "top_net_impact":
                        backfill_top_net_impact(conn, settings.db_schema, uw, sessions, stats)
                    elif dataset == "gex_levels":
                        backfill_gex_levels(conn, settings.db_schema, uw, tickers, sessions, stats)
                    elif dataset == "oi_change":
                        backfill_oi_change(conn, settings.db_schema, uw, tickers, sessions, stats)
                    elif dataset == "oi_by_strike":
                        backfill_oi_by_strike(conn, settings.db_schema, uw, tickers, sessions, stats)
                    elif dataset == "flow_bars":
                        backfill_flow_bars(conn, settings.db_schema, uw, tickers, sessions, stats)
                    elif dataset == "dark_lit":
                        backfill_dark_lit(conn, settings.db_schema, uw, tickers, sessions, stats)
            finally:
                uw.close()
            payload = {
                "checked_at": datetime.now(UTC).isoformat(),
                "request_plan": request_plan,
                "calls_used": budget.used,
                "daily_count": budget.daily_count,
                "daily_limit": budget.daily_limit,
                "stopped_reason": budget.stopped_reason,
                "rows": stats.rows,
                "skipped_existing": stats.skipped_existing,
                "no_data": stats.no_data,
                "error_count": len(stats.errors),
                "errors": stats.errors[:200],
                "coverage": coverage(conn, settings.db_schema, datasets, sessions, tickers),
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            write_report(out_dir / "execute-report.json", payload)
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
