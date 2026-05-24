"""US rates mirror persistence helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class _RatesMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_rates_observation_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        seen_at: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["series_id"],
                row["obs_date"],
                row["value"],
                row["realtime_start"],
                row["realtime_end"],
                seen_at,
                seen_at,
                row.get("release_date"),
                source,
                row.get("source_url"),
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_observations
                  (
                    series_id,
                    obs_date,
                    value,
                    realtime_start,
                    realtime_end,
                    first_seen_at,
                    last_seen_at,
                    release_date,
                    source,
                    source_url
                  )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_date, source)
                DO UPDATE SET
                  value = EXCLUDED.value,
                  realtime_start = EXCLUDED.realtime_start,
                  realtime_end = EXCLUDED.realtime_end,
                  last_seen_at = EXCLUDED.last_seen_at,
                  release_date = EXCLUDED.release_date,
                  source_url = EXCLUDED.source_url
                """,
                values,
            )
        return len(values)

    def fetch_rates_series(
        self,
        series_id: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        realtime_start_max: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if from_date is not None:
            clauses.append("obs_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s")
            params.append(to_date)
        if realtime_start_max is not None:
            clauses.append("realtime_start <= %s")
            params.append(realtime_start_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  series_id,
                  obs_date,
                  value,
                  realtime_start,
                  realtime_end,
                  first_seen_at,
                  last_seen_at,
                  release_date,
                  source,
                  source_url
                FROM {self._schema}.rates_observations
                WHERE {where}
                ORDER BY obs_date ASC, realtime_start DESC, last_seen_at DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def fetch_latest_rates_values(
        self,
        series_ids: Iterable[str],
        *,
        realtime_start_max: _date | None = None,
    ) -> dict[str, dict[str, Any]]:
        ids = list(series_ids)
        if not ids:
            return {}
        clauses = ["series_id = ANY(%s)"]
        params: list[Any] = [ids]
        if realtime_start_max is not None:
            clauses.append("realtime_start <= %s")
            params.append(realtime_start_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (series_id)
                  series_id,
                  obs_date,
                  value,
                  realtime_start,
                  realtime_end,
                  first_seen_at,
                  last_seen_at,
                  release_date,
                  source,
                  source_url
                FROM {self._schema}.rates_observations
                WHERE {where}
                ORDER BY series_id, obs_date DESC, realtime_start DESC, last_seen_at DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return {
                row_dict["series_id"]: row_dict
                for row_dict in [
                    dict(zip(cols, row, strict=True)) for row in cur.fetchall()
                ]
            }

    def insert_rates_snapshot(
        self,
        *,
        snapshot_date: _date,
        computed_at: datetime,
        payload: dict[str, Any],
        source_freshness: list[dict[str, Any]],
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.rates_snapshots
                  (snapshot_date, computed_at, payload, source_freshness)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (snapshot_date, computed_at)
                DO UPDATE SET
                  payload = EXCLUDED.payload,
                  source_freshness = EXCLUDED.source_freshness
                """,
                (
                    snapshot_date,
                    computed_at,
                    Jsonb(payload),
                    Jsonb(source_freshness),
                ),
            )

    def fetch_latest_rates_snapshot(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT snapshot_date, computed_at, payload, source_freshness
                FROM {self._schema}.rates_snapshots
                ORDER BY computed_at DESC, snapshot_date DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))

    def upsert_rates_cftc_tff_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
        source_url: str | None,
    ) -> int:
        values = [
            (
                row["contract_code"],
                row["contract_name"],
                row.get("commodity_name"),
                row["tenor_bucket"],
                row["obs_date"],
                row["release_date"],
                row.get("open_interest"),
                row.get("dealer_long"),
                row.get("dealer_short"),
                row.get("dealer_net"),
                row.get("asset_mgr_long"),
                row.get("asset_mgr_short"),
                row.get("asset_mgr_net"),
                row.get("lev_money_long"),
                row.get("lev_money_short"),
                row.get("lev_money_net"),
                row.get("other_rept_long"),
                row.get("other_rept_short"),
                row.get("other_rept_net"),
                row.get("dealer_net_pct_oi"),
                row.get("asset_mgr_net_pct_oi"),
                row.get("lev_money_net_pct_oi"),
                as_of,
                source_url,
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_cftc_tff_weekly
                  (
                    contract_code, contract_name, commodity_name, tenor_bucket,
                    obs_date, release_date, open_interest,
                    dealer_long, dealer_short, dealer_net,
                    asset_mgr_long, asset_mgr_short, asset_mgr_net,
                    lev_money_long, lev_money_short, lev_money_net,
                    other_rept_long, other_rept_short, other_rept_net,
                    dealer_net_pct_oi, asset_mgr_net_pct_oi, lev_money_net_pct_oi,
                    as_of, source_url
                  )
                VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (contract_code, obs_date, as_of) DO UPDATE SET
                  contract_name = EXCLUDED.contract_name,
                  commodity_name = EXCLUDED.commodity_name,
                  tenor_bucket = EXCLUDED.tenor_bucket,
                  release_date = EXCLUDED.release_date,
                  open_interest = EXCLUDED.open_interest,
                  dealer_long = EXCLUDED.dealer_long,
                  dealer_short = EXCLUDED.dealer_short,
                  dealer_net = EXCLUDED.dealer_net,
                  asset_mgr_long = EXCLUDED.asset_mgr_long,
                  asset_mgr_short = EXCLUDED.asset_mgr_short,
                  asset_mgr_net = EXCLUDED.asset_mgr_net,
                  lev_money_long = EXCLUDED.lev_money_long,
                  lev_money_short = EXCLUDED.lev_money_short,
                  lev_money_net = EXCLUDED.lev_money_net,
                  other_rept_long = EXCLUDED.other_rept_long,
                  other_rept_short = EXCLUDED.other_rept_short,
                  other_rept_net = EXCLUDED.other_rept_net,
                  dealer_net_pct_oi = EXCLUDED.dealer_net_pct_oi,
                  asset_mgr_net_pct_oi = EXCLUDED.asset_mgr_net_pct_oi,
                  lev_money_net_pct_oi = EXCLUDED.lev_money_net_pct_oi,
                  source_url = EXCLUDED.source_url
                """,
                values,
            )
        return len(values)

    def fetch_latest_rates_cftc_tff_rows(self) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH latest AS (
                  SELECT max(obs_date) AS obs_date
                  FROM {self._schema}.rates_cftc_tff_weekly
                )
                SELECT DISTINCT ON (t.contract_code)
                  t.contract_code,
                  t.contract_name,
                  t.commodity_name,
                  t.tenor_bucket,
                  t.obs_date,
                  t.release_date,
                  t.open_interest,
                  t.dealer_long,
                  t.dealer_short,
                  t.dealer_net,
                  t.asset_mgr_long,
                  t.asset_mgr_short,
                  t.asset_mgr_net,
                  t.lev_money_long,
                  t.lev_money_short,
                  t.lev_money_net,
                  t.other_rept_long,
                  t.other_rept_short,
                  t.other_rept_net,
                  t.dealer_net_pct_oi,
                  t.asset_mgr_net_pct_oi,
                  t.lev_money_net_pct_oi,
                  t.as_of,
                  t.source_url
                FROM {self._schema}.rates_cftc_tff_weekly t
                JOIN latest ON latest.obs_date = t.obs_date
                ORDER BY t.contract_code, t.as_of DESC
                """
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def upsert_rates_treasury_auction_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
    ) -> int:
        values = [
            (
                row["cusip"],
                row["security_type"],
                row["security_term"],
                row["auction_date"],
                row.get("issue_date"),
                row.get("offering_amount"),
                row.get("high_rate"),
                row.get("bid_to_cover"),
                row.get("direct_bidder_pct"),
                row.get("indirect_bidder_pct"),
                row.get("primary_dealer_pct"),
                row.get("tail_indicator"),
                as_of,
                row.get("source_url"),
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_treasury_auctions
                  (
                    cusip, security_type, security_term, auction_date, issue_date,
                    offering_amount, high_rate, bid_to_cover, direct_bidder_pct,
                    indirect_bidder_pct, primary_dealer_pct, tail_indicator, as_of,
                    source_url
                  )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (cusip, auction_date, as_of) DO UPDATE SET
                  security_type = EXCLUDED.security_type,
                  security_term = EXCLUDED.security_term,
                  issue_date = EXCLUDED.issue_date,
                  offering_amount = EXCLUDED.offering_amount,
                  high_rate = EXCLUDED.high_rate,
                  bid_to_cover = EXCLUDED.bid_to_cover,
                  direct_bidder_pct = EXCLUDED.direct_bidder_pct,
                  indirect_bidder_pct = EXCLUDED.indirect_bidder_pct,
                  primary_dealer_pct = EXCLUDED.primary_dealer_pct,
                  tail_indicator = EXCLUDED.tail_indicator,
                  source_url = EXCLUDED.source_url
                """,
                values,
            )
        return len(values)

    def fetch_latest_rates_treasury_auction_rows(
        self, *, limit: int = 120
    ) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (cusip, auction_date)
                  cusip,
                  security_type,
                  security_term,
                  auction_date,
                  issue_date,
                  offering_amount,
                  high_rate,
                  bid_to_cover,
                  direct_bidder_pct,
                  indirect_bidder_pct,
                  primary_dealer_pct,
                  tail_indicator,
                  source_url
                FROM {self._schema}.rates_treasury_auctions
                ORDER BY cusip, auction_date, as_of DESC
                """
            )
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        return sorted(rows, key=lambda row: row["auction_date"], reverse=True)[:limit]

    def upsert_rates_fiscal_debt_record(
        self,
        row: dict[str, Any] | None,
        *,
        as_of: datetime,
    ) -> int:
        if row is None:
            return 0
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.rates_fiscal_debt_daily
                  (
                    record_date,
                    debt_held_public,
                    intragov_holdings,
                    total_public_debt,
                    as_of,
                    source_url
                  )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_date, as_of) DO UPDATE SET
                  debt_held_public = EXCLUDED.debt_held_public,
                  intragov_holdings = EXCLUDED.intragov_holdings,
                  total_public_debt = EXCLUDED.total_public_debt,
                  source_url = EXCLUDED.source_url
                """,
                (
                    row["record_date"],
                    row.get("debt_held_public"),
                    row.get("intragov_holdings"),
                    row.get("total_public_debt"),
                    as_of,
                    row.get("source_url"),
                ),
            )
        return 1

    def fetch_latest_rates_fiscal_debt_record(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT record_date,
                       debt_held_public,
                       intragov_holdings,
                       total_public_debt,
                       source_url
                FROM {self._schema}.rates_fiscal_debt_daily
                ORDER BY record_date DESC, as_of DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))

    def upsert_rates_policy_events(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        seen_at: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["event_date"],
                row["label"],
                Jsonb(_json_safe(row)),
                source,
                row.get("source_url"),
                seen_at,
                seen_at,
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_policy_events
                  (event_date, label, payload, source, source_url, first_seen_at, last_seen_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_date, source)
                DO UPDATE SET
                  label = EXCLUDED.label,
                  payload = EXCLUDED.payload,
                  source_url = EXCLUDED.source_url,
                  last_seen_at = EXCLUDED.last_seen_at
                """,
                values,
            )
        return len(values)

    def fetch_rates_policy_events(
        self,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if from_date is not None:
            clauses.append("event_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("event_date <= %s")
            params.append(to_date)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload
                FROM {self._schema}.rates_policy_events
                {where}
                ORDER BY event_date ASC, last_seen_at DESC
                """,
                params,
            )
            return [row[0] for row in cur.fetchall()]

    def upsert_rates_policy_path(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        snapshot_date: _date,
        seen_at: datetime,
        source: str,
    ) -> int:
        values = [
            (
                snapshot_date,
                row["meeting_date"],
                Jsonb(_json_safe(row)),
                source,
                seen_at,
                seen_at,
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.rates_policy_path
                  (snapshot_date, meeting_date, payload, source, first_seen_at, last_seen_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_date, meeting_date, source)
                DO UPDATE SET
                  payload = EXCLUDED.payload,
                  last_seen_at = EXCLUDED.last_seen_at
                """,
                values,
            )
        return len(values)

    def fetch_latest_rates_policy_path(self) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH latest AS (
                  SELECT max(snapshot_date) AS snapshot_date
                  FROM {self._schema}.rates_policy_path
                )
                SELECT path.payload
                FROM {self._schema}.rates_policy_path path
                JOIN latest ON latest.snapshot_date = path.snapshot_date
                ORDER BY path.meeting_date ASC, path.source
                """
            )
            return [row[0] for row in cur.fetchall()]


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))
