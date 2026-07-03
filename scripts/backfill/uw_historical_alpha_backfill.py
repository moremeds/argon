"""Backfill UW historical alpha datasets under a hard request cap.

This script is intentionally self-contained so we can start capturing
retention-limited UW history before the research UI/API integration lands.

Examples:

  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    uv run python scripts/backfill/uw_historical_alpha_backfill.py plan \\
    --start 2026-01-01 --end 2026-07-01

  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    uv run python scripts/backfill/uw_historical_alpha_backfill.py execute \\
    --start 2026-01-01 --end 2026-07-01 --max-uw-calls 50000 --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Jsonb

from uw_scan.config import Settings

DATASETS = (
    "uw_volatility_signal_daily",
    "uw_gex_levels_daily",
    "uw_intraday_option_flow_bars",
    "uw_dark_lit_flow_prints",
    "uw_short_pressure_daily",
)


@dataclass
class Budget:
    max_calls: int
    reserve_calls: int
    used: int = 0
    daily_count: int | None = None
    daily_limit: int | None = None
    minute_remaining: int | None = None
    stopped_reason: str | None = None

    def can_call(self) -> bool:
        if self.used >= self.max_calls:
            self.stopped_reason = f"local_cap:{self.max_calls}"
            return False
        if self.daily_count is not None and self.daily_limit is not None:
            if self.daily_count >= self.daily_limit - self.reserve_calls:
                self.stopped_reason = (
                    f"provider_reserve:daily_count={self.daily_count} "
                    f"daily_limit={self.daily_limit} reserve={self.reserve_calls}"
                )
                return False
        return True

    def absorb(self, headers: httpx.Headers) -> None:
        self.used += 1
        self.daily_count = _int_or_none(headers.get("x-uw-daily-req-count"))
        self.daily_limit = _int_or_none(headers.get("x-uw-token-req-limit"))
        self.minute_remaining = _int_or_none(headers.get("x-uw-req-per-minute-remaining"))


@dataclass
class RunStats:
    calls: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    skipped_existing: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_rows(self, dataset: str, n: int) -> None:
        self.rows[dataset] = self.rows.get(dataset, 0) + n

    def add_skip(self, dataset: str, n: int = 1) -> None:
        self.skipped_existing[dataset] = self.skipped_existing.get(dataset, 0) + n


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
            body = resp.text[:240].replace("\n", " ")
            raise RuntimeError(f"UW HTTP {resp.status_code} path={path} body={body}")
        return resp.json()


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
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            pass
    if fallback_date is not None:
        return datetime(fallback_date.year, fallback_date.month, fallback_date.day, tzinfo=UTC)
    return None


def _data(body: dict[str, Any] | None) -> Any:
    if not body:
        return None
    return body.get("data", body)


def _load_tickers(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker
              FROM uw_scan.watchlist
             WHERE removed_at IS NULL
             ORDER BY sort_rank, ticker
            """
        )
        return [str(r[0]).upper() for r in cur.fetchall()]


def _load_sessions(conn: psycopg.Connection, start: date, end: date) -> list[date]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_date
              FROM uw_scan.market_tide_sentiment_daily
             WHERE data_date BETWEEN %s AND %s
             ORDER BY data_date
            """,
            (start, end),
        )
        rows = [r[0] for r in cur.fetchall()]
    if rows:
        return rows
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d::date
              FROM generate_series(%s::date, %s::date, interval '1 day') d
             WHERE extract(isodow from d) BETWEEN 1 AND 5
             ORDER BY d
            """,
            (start, end),
        )
        return [r[0] for r in cur.fetchall()]


def _existing_dates(conn: psycopg.Connection, table: str, ticker: str) -> set[date]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT market_date FROM uw_scan.{table} WHERE ticker = %s",
            (ticker,),
        )
        return {r[0] for r in cur.fetchall()}


def _upsert_volatility(
    conn: psycopg.Connection,
    ticker: str,
    market_date: date,
    *,
    anomaly: dict[str, Any] | None = None,
    character: dict[str, Any] | None = None,
    vrp: dict[str, Any] | None = None,
) -> int:
    raw: dict[str, Any] = {}
    sources: list[str] = []
    if anomaly:
        raw["anomaly"] = anomaly
        sources.append("anomaly")
    if character:
        raw["character"] = character
        sources.append("character")
    if vrp:
        raw["vrp"] = vrp
        sources.append("vrp")
    if not sources:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.uw_volatility_signal_daily (
                ticker, market_date, anomaly_direction, anomaly_score,
                vol_character, half_life_days, hurst_rv, vrp_rank,
                risk_premium, source_mask, raw_jsonb
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, market_date) DO UPDATE SET
                anomaly_direction = COALESCE(EXCLUDED.anomaly_direction, uw_volatility_signal_daily.anomaly_direction),
                anomaly_score = COALESCE(EXCLUDED.anomaly_score, uw_volatility_signal_daily.anomaly_score),
                vol_character = COALESCE(EXCLUDED.vol_character, uw_volatility_signal_daily.vol_character),
                half_life_days = COALESCE(EXCLUDED.half_life_days, uw_volatility_signal_daily.half_life_days),
                hurst_rv = COALESCE(EXCLUDED.hurst_rv, uw_volatility_signal_daily.hurst_rv),
                vrp_rank = COALESCE(EXCLUDED.vrp_rank, uw_volatility_signal_daily.vrp_rank),
                risk_premium = COALESCE(EXCLUDED.risk_premium, uw_volatility_signal_daily.risk_premium),
                source_mask = (
                    SELECT array_agg(DISTINCT x)
                      FROM unnest(uw_volatility_signal_daily.source_mask || EXCLUDED.source_mask) AS x
                ),
                raw_jsonb = COALESCE(uw_volatility_signal_daily.raw_jsonb, '{}'::jsonb) || EXCLUDED.raw_jsonb,
                fetched_at = now()
            """,
            (
                ticker,
                market_date,
                anomaly.get("direction") if anomaly else None,
                _dec(anomaly.get("score")) if anomaly else None,
                character.get("character") if character else None,
                _dec(character.get("half_life_days")) if character else None,
                _dec(character.get("hurst_rv")) if character else None,
                _dec(vrp.get("rank")) if vrp else None,
                _dec(vrp.get("risk_premium")) if vrp else None,
                sources,
                Jsonb(raw),
            ),
        )
    return 1


def backfill_volatility(
    conn: psycopg.Connection,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "uw_volatility_signal_daily"
    start, end = sessions[0], sessions[-1]
    for ticker in tickers:
        if not uw._budget.can_call():
            return
        try:
            anomaly_body = uw.get(f"/api/stock/{ticker}/volatility/anomaly", {"date": end.isoformat()})
            character_body = uw.get(f"/api/stock/{ticker}/volatility/character", {"date": end.isoformat()})
            vrp_body = uw.get(f"/api/stock/{ticker}/volatility/variance-risk-premium", {"date": end.isoformat()})
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"{dataset} {ticker}: {exc}")
            continue

        rows_by_date: dict[date, dict[str, dict[str, Any]]] = {}
        for row in (_data(anomaly_body) or {}).get("history", []) or []:
            dt = _date(row.get("date"))
            if dt and start <= dt <= end:
                rows_by_date.setdefault(dt, {})["anomaly"] = row
        latest = (_data(anomaly_body) or {}).get("latest")
        if isinstance(latest, dict):
            dt = _date(latest.get("date"))
            if dt and start <= dt <= end:
                rows_by_date.setdefault(dt, {})["anomaly"] = latest
        for row in (_data(character_body) or {}).get("history", []) or []:
            dt = _date(row.get("date"))
            if dt and start <= dt <= end:
                rows_by_date.setdefault(dt, {})["character"] = row
        latest = (_data(character_body) or {}).get("latest")
        if isinstance(latest, dict):
            dt = _date(latest.get("date"))
            if dt and start <= dt <= end:
                rows_by_date.setdefault(dt, {})["character"] = latest
        for row in _data(vrp_body) or []:
            if not isinstance(row, dict):
                continue
            dt = _date(row.get("date"))
            if dt and start <= dt <= end:
                rows_by_date.setdefault(dt, {})["vrp"] = row

        n = 0
        for dt, parts in rows_by_date.items():
            n += _upsert_volatility(
                conn,
                ticker,
                dt,
                anomaly=parts.get("anomaly"),
                character=parts.get("character"),
                vrp=parts.get("vrp"),
            )
        conn.commit()
        stats.add_rows(dataset, n)
        print(f"{dataset} ticker={ticker} rows={n} calls={uw._budget.used}", flush=True)


def backfill_gex(
    conn: psycopg.Connection,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "uw_gex_levels_daily"
    for ticker in tickers:
        existing = _existing_dates(conn, dataset, ticker)
        for dt in sessions:
            if not uw._budget.can_call():
                return
            if dt in existing:
                stats.add_skip(dataset)
                continue
            try:
                body = uw.get(f"/api/stock/{ticker}/gex-levels", {"date": dt.isoformat()})
                data = _data(body) or {}
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO uw_scan.uw_gex_levels_daily (
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
                            dt,
                            _dec(data.get("call_wall")),
                            _dec(data.get("put_wall")),
                            _dec(data.get("gamma_flip")),
                            _dec(data.get("gamma_magnet")),
                            Jsonb(data),
                        ),
                    )
                conn.commit()
                stats.add_rows(dataset, 1)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                stats.errors.append(f"{dataset} {ticker} {dt}: {exc}")
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def _flow_ts(row: dict[str, Any], fallback_date: date) -> datetime | None:
    for key in ("timestamp", "tape_time", "time", "created_at", "date"):
        ts = _ts(row.get(key), fallback_date)
        if ts:
            return ts
    return None


def backfill_intraday_flow(
    conn: psycopg.Connection,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "uw_intraday_option_flow_bars"
    endpoints = (
        ("net_prem_ticks", "/api/stock/{ticker}/net-prem-ticks"),
        ("greek_flow", "/api/stock/{ticker}/greek-flow"),
    )
    for ticker in tickers:
        for dt in sessions:
            for source, path_template in endpoints:
                if not uw._budget.can_call():
                    return
                path = path_template.format(ticker=ticker)
                try:
                    body = uw.get(path, {"date": dt.isoformat()})
                    rows = _data(body) or []
                    n = 0
                    with conn.cursor() as cur:
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            ts = _flow_ts(row, dt)
                            if ts is None:
                                continue
                            cur.execute(
                                """
                                INSERT INTO uw_scan.uw_intraday_option_flow_bars (
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
                                (
                                    ticker,
                                    dt,
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
                                ),
                            )
                            n += 1
                    conn.commit()
                    stats.add_rows(dataset, n)
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    stats.errors.append(f"{dataset} {ticker} {dt} {source}: {exc}")
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def _codes(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def backfill_dark_lit(
    conn: psycopg.Connection,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "uw_dark_lit_flow_prints"
    endpoints = (
        ("darkpool", "/api/darkpool/{ticker}"),
        ("lit_flow", "/api/lit-flow/{ticker}"),
    )
    for ticker in tickers:
        for dt in sessions:
            for source, path_template in endpoints:
                if not uw._budget.can_call():
                    return
                try:
                    body = uw.get(
                        path_template.format(ticker=ticker),
                        {"date": dt.isoformat(), "limit": 500},
                    )
                    rows = _data(body) or []
                    n = 0
                    with conn.cursor() as cur:
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            executed_at = _ts(row.get("executed_at"), dt)
                            tracking_id = row.get("tracking_id") or row.get("id")
                            if executed_at is None or not tracking_id:
                                continue
                            cur.execute(
                                """
                                INSERT INTO uw_scan.uw_dark_lit_flow_prints (
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
                                (
                                    source,
                                    str(tracking_id),
                                    ticker,
                                    executed_at,
                                    dt,
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
                                ),
                            )
                            n += 1
                    conn.commit()
                    stats.add_rows(dataset, n)
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    stats.errors.append(f"{dataset} {ticker} {dt} {source}: {exc}")
        print(f"{dataset} ticker={ticker} calls={uw._budget.used}", flush=True)


def backfill_short_pressure(
    conn: psycopg.Connection,
    uw: UwDirectClient,
    tickers: list[str],
    sessions: list[date],
    stats: RunStats,
) -> None:
    dataset = "uw_short_pressure_daily"
    start, end = sessions[0], sessions[-1]
    for ticker in tickers:
        if not uw._budget.can_call():
            return
        try:
            interest = _data(uw.get(f"/api/shorts/{ticker}/interest-float/v2")) or []
            ftds = _data(uw.get(f"/api/shorts/{ticker}/ftds")) or []
            volumes = _data(uw.get(f"/api/shorts/{ticker}/volumes-by-exchange")) or []
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"{dataset} {ticker}: {exc}")
            continue
        by_date: dict[date, dict[str, Any]] = {}
        for row in interest:
            if not isinstance(row, dict):
                continue
            dt = _date(row.get("market_date") or row.get("created_at"))
            if dt and start <= dt <= end:
                by_date.setdefault(dt, {})["interest"] = row
        for row in ftds:
            if not isinstance(row, dict):
                continue
            dt = _date(row.get("date"))
            if dt and start <= dt <= end:
                by_date.setdefault(dt, {})["ftd_quantity"] = (
                    (by_date.setdefault(dt, {}).get("ftd_quantity") or Decimal("0"))
                    + (_dec(row.get("quantity")) or Decimal("0"))
                )
        vol_by_date: dict[date, dict[str, Decimal]] = {}
        for row in volumes:
            if not isinstance(row, dict):
                continue
            dt = _date(row.get("date") or row.get("created_at"))
            if not dt or not (start <= dt <= end):
                continue
            acc = vol_by_date.setdefault(dt, {"short_volume": Decimal("0"), "total_volume": Decimal("0")})
            acc["short_volume"] += _dec(row.get("short_volume")) or Decimal("0")
            acc["total_volume"] += _dec(row.get("total_volume")) or Decimal("0")
        for dt, row in vol_by_date.items():
            by_date.setdefault(dt, {})["volume"] = row
        n = 0
        with conn.cursor() as cur:
            for dt, parts in by_date.items():
                interest_row = parts.get("interest") or {}
                volume = parts.get("volume") or {}
                total_volume = volume.get("total_volume")
                short_volume = volume.get("short_volume")
                ratio = short_volume / total_volume if short_volume is not None and total_volume else None
                raw = {"interest": interest_row, "ftd_quantity": str(parts.get("ftd_quantity") or ""), "volume": {k: str(v) for k, v in volume.items()}}
                cur.execute(
                    """
                    INSERT INTO uw_scan.uw_short_pressure_daily (
                        ticker, market_date, short_interest, si_float,
                        si_float_with_synth_long_pct_of_total_shares,
                        days_to_cover, fee_rate, rebate_rate, short_shares_available,
                        total_float, ftd_quantity, short_volume, total_volume,
                        short_volume_ratio, raw_jsonb
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ticker, market_date) DO UPDATE SET
                        short_interest = COALESCE(EXCLUDED.short_interest, uw_short_pressure_daily.short_interest),
                        si_float = COALESCE(EXCLUDED.si_float, uw_short_pressure_daily.si_float),
                        si_float_with_synth_long_pct_of_total_shares = COALESCE(EXCLUDED.si_float_with_synth_long_pct_of_total_shares, uw_short_pressure_daily.si_float_with_synth_long_pct_of_total_shares),
                        days_to_cover = COALESCE(EXCLUDED.days_to_cover, uw_short_pressure_daily.days_to_cover),
                        fee_rate = COALESCE(EXCLUDED.fee_rate, uw_short_pressure_daily.fee_rate),
                        rebate_rate = COALESCE(EXCLUDED.rebate_rate, uw_short_pressure_daily.rebate_rate),
                        short_shares_available = COALESCE(EXCLUDED.short_shares_available, uw_short_pressure_daily.short_shares_available),
                        total_float = COALESCE(EXCLUDED.total_float, uw_short_pressure_daily.total_float),
                        ftd_quantity = COALESCE(EXCLUDED.ftd_quantity, uw_short_pressure_daily.ftd_quantity),
                        short_volume = COALESCE(EXCLUDED.short_volume, uw_short_pressure_daily.short_volume),
                        total_volume = COALESCE(EXCLUDED.total_volume, uw_short_pressure_daily.total_volume),
                        short_volume_ratio = COALESCE(EXCLUDED.short_volume_ratio, uw_short_pressure_daily.short_volume_ratio),
                        raw_jsonb = COALESCE(uw_short_pressure_daily.raw_jsonb, '{}'::jsonb) || EXCLUDED.raw_jsonb,
                        fetched_at = now()
                    """,
                    (
                        ticker,
                        dt,
                        _dec(interest_row.get("short_interest")),
                        _dec(interest_row.get("si_float")),
                        _dec(interest_row.get("si_float_with_synth_long_pct_of_total_shares")),
                        _dec(interest_row.get("days_to_cover")),
                        _dec(interest_row.get("fee_rate")),
                        _dec(interest_row.get("rebate_rate")),
                        _dec(interest_row.get("short_shares_available")),
                        _dec(interest_row.get("total_float")),
                        parts.get("ftd_quantity"),
                        short_volume,
                        total_volume,
                        ratio,
                        Jsonb(raw),
                    ),
                )
                n += 1
        conn.commit()
        stats.add_rows(dataset, n)
        print(f"{dataset} ticker={ticker} rows={n} calls={uw._budget.used}", flush=True)


def estimate_requests(dataset: str, ticker_count: int, session_count: int) -> int:
    if dataset == "uw_volatility_signal_daily":
        return ticker_count * 3
    if dataset == "uw_gex_levels_daily":
        return ticker_count * session_count
    if dataset == "uw_intraday_option_flow_bars":
        return ticker_count * session_count * 2
    if dataset == "uw_dark_lit_flow_prints":
        return ticker_count * session_count * 2
    if dataset == "uw_short_pressure_daily":
        return ticker_count * 3
    raise ValueError(dataset)


def coverage(conn: psycopg.Connection, datasets: list[str], sessions: list[date], tickers: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    expected = len(tickers) * len(sessions)
    for dataset in datasets:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(DISTINCT (ticker, market_date)),
                       min(market_date),
                       max(market_date),
                       count(*)
                  FROM uw_scan.{dataset}
                 WHERE ticker = ANY(%s)
                   AND market_date BETWEEN %s AND %s
                """,
                (tickers, sessions[0], sessions[-1]),
            )
            covered, min_dt, max_dt, rows = cur.fetchone()
        out.append(
            {
                "dataset": dataset,
                "expected_ticker_dates": expected,
                "covered_ticker_dates": int(covered or 0),
                "coverage_pct": round((int(covered or 0) / expected) * 100, 2) if expected else 0,
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
    parser.add_argument("--datasets", default=os.environ.get("UW_HISTORICAL_ALPHA_DATASETS", ",".join(DATASETS)))
    parser.add_argument("--start", default=os.environ.get("UW_HISTORICAL_ALPHA_START", "2026-01-01"))
    parser.add_argument("--end", default=os.environ.get("UW_HISTORICAL_ALPHA_END"))
    parser.add_argument("--max-uw-calls", type=int, default=int(os.environ.get("UW_HISTORICAL_ALPHA_MAX_UW_CALLS", "20000")))
    parser.add_argument("--uw-reserve-calls", type=int, default=int(os.environ.get("UW_HISTORICAL_ALPHA_RESERVE_CALLS", "1000")))
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output-dir", default="output/uw-historical-alpha")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    unknown = sorted(set(datasets) - set(DATASETS))
    if unknown:
        raise SystemExit(f"unknown datasets: {unknown}")
    settings = Settings.from_env()
    start = _date(args.start)
    if start is None:
        raise SystemExit(f"invalid --start {args.start!r}")
    end = _date(args.end) if args.end else date.today()
    if end is None:
        raise SystemExit(f"invalid --end {args.end!r}")

    stats = RunStats()
    budget = Budget(args.max_uw_calls, args.uw_reserve_calls)
    out_dir = Path(args.output_dir)
    with psycopg.connect(settings.db_dsn()) as conn:
        tickers = _load_tickers(conn)
        sessions = _load_sessions(conn, start, end)
        if not sessions:
            raise SystemExit("no sessions found")
        request_plan = {
            "checked_at": datetime.now(UTC).isoformat(),
            "tickers": len(tickers),
            "sessions": len(sessions),
            "start": str(sessions[0]),
            "end": str(sessions[-1]),
            "datasets": {
                d: estimate_requests(d, len(tickers), len(sessions))
                for d in datasets
            },
        }
        request_plan["total_estimated_requests"] = sum(request_plan["datasets"].values())
        if args.command == "plan":
            print(json.dumps(request_plan, indent=2, sort_keys=True))
            write_report(out_dir / "request-plan.json", request_plan)
            return 0

        if args.command in {"audit", "verify"}:
            payload = {
                "checked_at": datetime.now(UTC).isoformat(),
                "request_plan": request_plan,
                "coverage": coverage(conn, datasets, sessions, tickers),
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
                    if dataset == "uw_volatility_signal_daily":
                        backfill_volatility(conn, uw, tickers, sessions, stats)
                    elif dataset == "uw_gex_levels_daily":
                        backfill_gex(conn, uw, tickers, sessions, stats)
                    elif dataset == "uw_intraday_option_flow_bars":
                        backfill_intraday_flow(conn, uw, tickers, sessions, stats)
                    elif dataset == "uw_dark_lit_flow_prints":
                        backfill_dark_lit(conn, uw, tickers, sessions, stats)
                    elif dataset == "uw_short_pressure_daily":
                        backfill_short_pressure(conn, uw, tickers, sessions, stats)
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
                "errors": stats.errors[:200],
                "error_count": len(stats.errors),
                "coverage": coverage(conn, datasets, sessions, tickers),
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            write_report(out_dir / "execute-report.json", payload)
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
