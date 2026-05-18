"""Gold ETF flow persistence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg


class _GoldEtfMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_etf_flows_daily(
        self,
        *,
        ticker: str,
        obs_date: _date,
        share_change: Decimal | None,
        premium_change_usd: Decimal | None,
        close: Decimal | None,
        volume: Decimal | None,
        as_of: datetime,
        source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.etf_flows_daily
                  (ticker, obs_date, share_change, premium_change_usd, close,
                   volume, as_of, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, as_of) DO NOTHING
                """,
                (
                    ticker.upper(),
                    obs_date,
                    share_change,
                    premium_change_usd,
                    close,
                    volume,
                    as_of,
                    source,
                ),
            )

    def fetch_etf_flows_daily(
        self,
        ticker: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker.upper()]
        if from_date is not None:
            clauses.append("obs_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s")
            params.append(to_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, share_change, premium_change_usd, close, volume,
                  as_of, source
                FROM {self._schema}.etf_flows_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def insert_wgc_etf_monthly(
        self,
        *,
        ticker: str,
        obs_date: _date,
        fund_name: str | None,
        fund_type: str | None,
        region: str | None,
        country: str | None,
        gold_price_usd_oz: Decimal | None,
        aggregate_ounces: Decimal | None,
        aggregate_holdings_tonnes: Decimal | None,
        aggregate_value_usd: Decimal | None,
        holdings_tonnes: Decimal | None,
        demand_tonnes: Decimal | None,
        flow_usd_mn: Decimal | None,
        source_url: str,
        source_label: str | None,
        as_of: datetime,
        source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.wgc_etf_monthly
                  (ticker, obs_date, fund_name, fund_type, region, country,
                   gold_price_usd_oz, aggregate_ounces, aggregate_holdings_tonnes,
                   aggregate_value_usd, holdings_tonnes, demand_tonnes, flow_usd_mn,
                   source_url, source_label, as_of, source)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, source_url) DO UPDATE SET
                  fund_name = EXCLUDED.fund_name,
                  fund_type = EXCLUDED.fund_type,
                  region = EXCLUDED.region,
                  country = EXCLUDED.country,
                  gold_price_usd_oz = EXCLUDED.gold_price_usd_oz,
                  aggregate_ounces = EXCLUDED.aggregate_ounces,
                  aggregate_holdings_tonnes = EXCLUDED.aggregate_holdings_tonnes,
                  aggregate_value_usd = EXCLUDED.aggregate_value_usd,
                  holdings_tonnes = EXCLUDED.holdings_tonnes,
                  demand_tonnes = EXCLUDED.demand_tonnes,
                  flow_usd_mn = EXCLUDED.flow_usd_mn,
                  source_label = EXCLUDED.source_label,
                  as_of = EXCLUDED.as_of,
                  source = EXCLUDED.source
                """,
                (
                    ticker.upper(),
                    obs_date,
                    fund_name,
                    fund_type,
                    region,
                    country,
                    gold_price_usd_oz,
                    aggregate_ounces,
                    aggregate_holdings_tonnes,
                    aggregate_value_usd,
                    holdings_tonnes,
                    demand_tonnes,
                    flow_usd_mn,
                    source_url,
                    source_label,
                    as_of,
                    source,
                ),
            )

    def insert_wgc_etf_monthly_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["ticker"].upper(),
                row["obs_date"],
                row.get("fund_name"),
                row.get("fund_type"),
                row.get("region"),
                row.get("country"),
                row.get("gold_price_usd_oz"),
                row.get("aggregate_ounces"),
                row.get("aggregate_holdings_tonnes"),
                row.get("aggregate_value_usd"),
                row.get("holdings_tonnes"),
                row.get("demand_tonnes"),
                row.get("flow_usd_mn"),
                row["source_url"],
                row.get("source_label"),
                as_of,
                source,
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.wgc_etf_monthly
                  (ticker, obs_date, fund_name, fund_type, region, country,
                   gold_price_usd_oz, aggregate_ounces, aggregate_holdings_tonnes,
                   aggregate_value_usd, holdings_tonnes, demand_tonnes, flow_usd_mn,
                   source_url, source_label, as_of, source)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, source_url) DO UPDATE SET
                  fund_name = EXCLUDED.fund_name,
                  fund_type = EXCLUDED.fund_type,
                  region = EXCLUDED.region,
                  country = EXCLUDED.country,
                  gold_price_usd_oz = EXCLUDED.gold_price_usd_oz,
                  aggregate_ounces = EXCLUDED.aggregate_ounces,
                  aggregate_holdings_tonnes = EXCLUDED.aggregate_holdings_tonnes,
                  aggregate_value_usd = EXCLUDED.aggregate_value_usd,
                  holdings_tonnes = EXCLUDED.holdings_tonnes,
                  demand_tonnes = EXCLUDED.demand_tonnes,
                  flow_usd_mn = EXCLUDED.flow_usd_mn,
                  source_label = EXCLUDED.source_label,
                  as_of = EXCLUDED.as_of,
                  source = EXCLUDED.source
                """,
                values,
            )
        return len(values)

    def fetch_wgc_etf_monthly(
        self,
        ticker: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker.upper()]
        if from_date is not None:
            clauses.append("obs_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s")
            params.append(to_date)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  ticker, obs_date, fund_name, fund_type, region, country,
                  gold_price_usd_oz, aggregate_ounces, aggregate_holdings_tonnes,
                  aggregate_value_usd, holdings_tonnes, demand_tonnes, flow_usd_mn,
                  source_url, source_label, as_of, source
                FROM {self._schema}.wgc_etf_monthly_canonical
                WHERE {where}
                ORDER BY obs_date ASC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
