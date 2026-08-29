"""Gold macro, positioning, options, and posture persistence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb



class _GoldMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_macro_series_daily(
        self,
        series_id: str,
        obs_date: _date,
        value: Decimal,
        as_of: datetime,
        release_date: _date | None,
        source: str,
        source_url: str | None,
    ) -> None:
        self.insert_macro_series_daily_rows(
            [
                {
                    "series_id": series_id,
                    "obs_date": obs_date,
                    "value": value,
                    "release_date": release_date,
                    "source_url": source_url,
                }
            ],
            as_of=as_of,
            source=source,
        )

    def insert_macro_series_daily_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["series_id"],
                row["obs_date"],
                row["value"],
                as_of,
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
                """
                INSERT INTO uw_scan.macro_series_daily
                  (series_id, obs_date, value, as_of, release_date, source, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_date, as_of) DO NOTHING
                """,
                values,
            )
        return len(values)

    def insert_macro_series_monthly(
        self,
        series_id: str,
        obs_month: _date,
        value: Decimal,
        as_of: datetime,
        release_date: _date | None,
        source: str,
        source_url: str | None,
    ) -> None:
        self.insert_macro_series_monthly_rows(
            [
                {
                    "series_id": series_id,
                    "obs_month": obs_month,
                    "value": value,
                    "release_date": release_date,
                    "source_url": source_url,
                }
            ],
            as_of=as_of,
            source=source,
        )

    def insert_macro_series_monthly_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["series_id"],
                row["obs_month"],
                row["value"],
                as_of,
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
                """
                INSERT INTO uw_scan.macro_series_monthly
                  (series_id, obs_month, value, as_of, release_date, source, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_month, as_of) DO NOTHING
                """,
                values,
            )
        return len(values)

    def fetch_macro_series_daily(
        self,
        series_id: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Latest-vintage values for a daily series. Respects optional date window
        and as-of cap (for replay/PIT queries)."""
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
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
                  obs_date, value, as_of, release_date, source
                FROM uw_scan.macro_series_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def fetch_macro_series_monthly(
        self,
        series_id: str,
        *,
        from_month: _date | None = None,
        to_month: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if from_month is not None:
            clauses.append("obs_month >= %s")
            params.append(from_month)
        if to_month is not None:
            clauses.append("obs_month <= %s")
            params.append(to_month)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_month)
                  obs_month, value, as_of, release_date, source
                FROM uw_scan.macro_series_monthly
                WHERE {where}
                ORDER BY obs_month ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def fetch_macro_series_vintages(
        self, series_id: str, *, obs_date: _date
    ) -> list[dict[str, Any]]:
        """All persisted vintages for a single observation (useful for audit)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT obs_date, value, as_of, release_date, source
                FROM uw_scan.macro_series_daily
                WHERE series_id = %s AND obs_date = %s
                ORDER BY as_of DESC
                """,
                (series_id, obs_date),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — ETF holdings ----

    def insert_etf_holdings_daily(
        self,
        *,
        ticker: str,
        obs_date: _date,
        holdings_oz: Decimal | None,
        shares_out: Decimal | None,
        nav_per_share: Decimal | None,
        premium_pct: Decimal | None,
        as_of: datetime,
        source: str,
    ) -> None:
        self.insert_etf_holdings_daily_rows(
            [
                {
                    "ticker": ticker,
                    "obs_date": obs_date,
                    "holdings_oz": holdings_oz,
                    "shares_out": shares_out,
                    "nav_per_share": nav_per_share,
                    "premium_pct": premium_pct,
                }
            ],
            as_of=as_of,
            source=source,
        )

    def insert_etf_holdings_daily_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        as_of: datetime,
        source: str,
    ) -> int:
        values = [
            (
                row["ticker"],
                row["obs_date"],
                row.get("holdings_oz"),
                row.get("shares_out"),
                row.get("nav_per_share"),
                row.get("premium_pct"),
                as_of,
                source,
            )
            for row in rows
        ]
        if not values:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO uw_scan.etf_holdings_daily
                  (ticker, obs_date, holdings_oz, shares_out, nav_per_share,
                   premium_pct, as_of, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, as_of) DO NOTHING
                """,
                values,
            )
        return len(values)

    def fetch_etf_holdings_daily(
        self,
        ticker: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
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
                  obs_date, holdings_oz, shares_out, nav_per_share, premium_pct,
                  as_of, source
                FROM uw_scan.etf_holdings_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — exchange inventory ----

    def insert_exchange_inventory_daily(
        self,
        *,
        exchange: str,
        obs_date: _date,
        registered_oz: Decimal | None,
        eligible_oz: Decimal | None,
        vault_oz: Decimal | None,
        as_of: datetime,
        source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.exchange_inventory_daily
                  (exchange, obs_date, registered_oz, eligible_oz, vault_oz,
                   as_of, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (exchange, obs_date, as_of) DO NOTHING
                """,
                (
                    exchange,
                    obs_date,
                    registered_oz,
                    eligible_oz,
                    vault_oz,
                    as_of,
                    source_url,
                ),
            )

    def fetch_exchange_inventory_daily(
        self,
        exchange: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["exchange = %s"]
        params: list[Any] = [exchange]
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
                  obs_date, registered_oz, eligible_oz, vault_oz, as_of, source_url
                FROM uw_scan.exchange_inventory_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — CB reserves ----

    def insert_cb_gold_reserves_monthly(
        self,
        *,
        country_iso3: str,
        obs_month: _date,
        reserves_t: Decimal | None,
        bucket: str,
        is_reported: bool,
        is_estimated: bool,
        as_of: datetime,
        release_date: _date | None,
        source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.cb_gold_reserves_monthly
                  (country_iso3, obs_month, reserves_t, bucket,
                   is_reported, is_estimated, as_of, release_date, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (country_iso3, obs_month, as_of) DO NOTHING
                """,
                (
                    country_iso3,
                    obs_month,
                    reserves_t,
                    bucket,
                    is_reported,
                    is_estimated,
                    as_of,
                    release_date,
                    source,
                ),
            )

    def fetch_cb_gold_reserves_monthly(
        self,
        *,
        bucket: str | None = None,
        country_iso3: str | None = None,
        from_month: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: list[Any] = []
        if bucket is not None:
            clauses.append("bucket = %s")
            params.append(bucket)
        if country_iso3 is not None:
            clauses.append("country_iso3 = %s")
            params.append(country_iso3)
        if from_month is not None:
            clauses.append("obs_month >= %s")
            params.append(from_month)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (country_iso3, obs_month)
                  country_iso3, obs_month, reserves_t, bucket,
                  is_reported, is_estimated, as_of, release_date, source
                FROM uw_scan.cb_gold_reserves_monthly
                WHERE {where}
                ORDER BY country_iso3, obs_month DESC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def fetch_cb_gold_reserves_history(
        self,
        *,
        country_iso3: str | None = None,
        from_month: _date | None = None,
        to_month: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: list[Any] = []
        if country_iso3 is not None:
            clauses.append("country_iso3 = %s")
            params.append(country_iso3)
        if from_month is not None:
            clauses.append("obs_month >= %s")
            params.append(from_month)
        if to_month is not None:
            clauses.append("obs_month <= %s")
            params.append(to_month)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (country_iso3, obs_month)
                  country_iso3, obs_month, reserves_t, bucket,
                  is_reported, is_estimated, as_of, release_date, source
                FROM uw_scan.cb_gold_reserves_monthly
                WHERE {where}
                ORDER BY country_iso3, obs_month ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — CFTC COT ----

    def insert_cot_gold_weekly(
        self,
        *,
        obs_date: _date,
        release_date: _date,
        mm_long: Decimal | None,
        mm_short: Decimal | None,
        mm_net: Decimal | None,
        comm_long: Decimal | None,
        comm_short: Decimal | None,
        comm_net: Decimal | None,
        open_interest: Decimal | None,
        as_of: datetime,
        source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.cot_gold_weekly
                  (obs_date, release_date, mm_long, mm_short, mm_net,
                   comm_long, comm_short, comm_net, open_interest,
                   as_of, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (obs_date, as_of) DO NOTHING
                """,
                (
                    obs_date,
                    release_date,
                    mm_long,
                    mm_short,
                    mm_net,
                    comm_long,
                    comm_short,
                    comm_net,
                    open_interest,
                    as_of,
                    source_url,
                ),
            )

    def fetch_cot_gold_weekly(
        self,
        *,
        from_release_date: _date | None = None,
        to_release_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: list[Any] = []
        if from_release_date is not None:
            clauses.append("release_date >= %s")
            params.append(from_release_date)
        if to_release_date is not None:
            clauses.append("release_date <= %s")
            params.append(to_release_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, release_date, mm_long, mm_short, mm_net,
                  comm_long, comm_short, comm_net, open_interest, as_of, source_url
                FROM uw_scan.cot_gold_weekly
                WHERE {where}
                ORDER BY obs_date DESC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — UW gold options snapshots ----

    def insert_uw_gold_options_daily(
        self,
        *,
        ticker: str,
        obs_date: _date,
        atm_iv_30d: Decimal | None,
        atm_iv_60d: Decimal | None,
        put_25d_iv_30d: Decimal | None,
        call_25d_iv_30d: Decimal | None,
        skew_25d_30d: Decimal | None,
        put_call_oi_ratio: Decimal | None,
        dealer_gamma_est: Decimal | None,
        as_of: datetime,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.uw_gold_options_daily
                  (ticker, obs_date, atm_iv_30d, atm_iv_60d,
                   put_25d_iv_30d, call_25d_iv_30d, skew_25d_30d,
                   put_call_oi_ratio, dealer_gamma_est, as_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, as_of) DO NOTHING
                """,
                (
                    ticker,
                    obs_date,
                    atm_iv_30d,
                    atm_iv_60d,
                    put_25d_iv_30d,
                    call_25d_iv_30d,
                    skew_25d_30d,
                    put_call_oi_ratio,
                    dealer_gamma_est,
                    as_of,
                ),
            )

    def fetch_uw_gold_options_daily(
        self,
        ticker: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
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
                  obs_date, atm_iv_30d, atm_iv_60d,
                  put_25d_iv_30d, call_25d_iv_30d, skew_25d_30d,
                  put_call_oi_ratio, dealer_gamma_est, as_of
                FROM uw_scan.uw_gold_options_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Gold (Phase A1) — posture row (replay scaffold) ----

    def insert_gold_posture_daily(
        self,
        *,
        obs_date: _date,
        computed_at: datetime,
        gauge_corr_60d: Decimal | None,
        gauge_corr_126d: Decimal | None,
        gauge_corr_252d: Decimal | None,
        gauge_corr_504d: Decimal | None,
        gauge_corr_252d_returns: Decimal | None,
        gauge_state: str,
        structural_state_label: str | None,
        cb_strategic_12m_sum_t: Decimal | None,
        cb_tactical_12m_sum_t: Decimal | None,
        cb_diversifier_12m_sum_t: Decimal | None,
        gld_holdings_t: Decimal | None,
        gld_30d_net_flow_t: Decimal | None,
        comex_registered_oz: Decimal | None,
        comex_20d_roc_pct: Decimal | None,
        cot_mm_net_pct: Decimal | None,
        cyclical_zone_label: str | None,
        cpi_yoy: Decimal | None,
        t5yifr: Decimal | None,
        dfii10: Decimal | None,
        dfii10_60d_change_bps: Decimal | None,
        factors_jsonb: dict[str, Any],
        valuation_flag: str | None,
        real_price_percentile: Decimal | None,
        gold_m2_ratio_percentile: Decimal | None,
        gold_spx_ratio_percentile: Decimal | None,
        structural_posture_text: str | None,
        cyclical_posture_text: str | None,
        valuation_posture_text: str | None,
        inputs_jsonb: dict[str, Any],
        # GOLD COMPASS extensions (all optional — orchestrator passes when computed)
        structural_posture_chip: str | None = None,
        cyclical_posture_chip: str | None = None,
        valuation_posture_chip: str | None = None,
        spot_jsonb: dict[str, Any] | None = None,
        data_freshness_jsonb: dict[str, Any] | None = None,
        decomposition_jsonb: list[dict[str, Any]] | None = None,
        correlation_history_jsonb: dict[str, Any] | None = None,
        gld_history_jsonb: list[dict[str, Any]] | None = None,
        gold_history_jsonb: list[dict[str, Any]] | None = None,
        # 044 extensions — orchestrator-derived metrics from DXY/GPR/UW/LBMA series
        lbma_30d_momentum_t: Decimal | None = None,
        uw_25d_skew_sigma: Decimal | None = None,
        fx_basket_dxy_z: Decimal | None = None,
        xau_cny_premium_pct: Decimal | None = None,
        cb_52w_pct: Decimal | None = None,
        cot_mm_4w_change_sigma: Decimal | None = None,
        t5yifr_pct_52w: Decimal | None = None,
        dxy: Decimal | None = None,
        dxy_60d_sigma: Decimal | None = None,
        gpr_value: Decimal | None = None,
        gpr_pct_52w: Decimal | None = None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.gold_posture_daily (
                  obs_date, computed_at,
                  gauge_corr_60d, gauge_corr_126d, gauge_corr_252d,
                  gauge_corr_504d, gauge_corr_252d_returns, gauge_state,
                  structural_state_label,
                  cb_strategic_12m_sum_t, cb_tactical_12m_sum_t,
                  cb_diversifier_12m_sum_t,
                  gld_holdings_t, gld_30d_net_flow_t,
                  comex_registered_oz, comex_20d_roc_pct, cot_mm_net_pct,
                  cyclical_zone_label, cpi_yoy, t5yifr, dfii10,
                  dfii10_60d_change_bps, factors_jsonb,
                  valuation_flag, real_price_percentile,
                  gold_m2_ratio_percentile, gold_spx_ratio_percentile,
                  structural_posture_text, cyclical_posture_text,
                  valuation_posture_text, inputs_jsonb,
                  structural_posture_chip, cyclical_posture_chip,
                  valuation_posture_chip,
                  spot_jsonb, data_freshness_jsonb,
                  decomposition_jsonb, correlation_history_jsonb,
                  gld_history_jsonb, gold_history_jsonb,
                  lbma_30d_momentum_t, uw_25d_skew_sigma,
                  fx_basket_dxy_z, xau_cny_premium_pct,
                  cb_52w_pct, cot_mm_4w_change_sigma,
                  t5yifr_pct_52w, dxy, dxy_60d_sigma,
                  gpr_value, gpr_pct_52w
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s,
                  %s, %s,
                  %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (obs_date, computed_at) DO NOTHING
                """,
                (
                    obs_date,
                    computed_at,
                    gauge_corr_60d,
                    gauge_corr_126d,
                    gauge_corr_252d,
                    gauge_corr_504d,
                    gauge_corr_252d_returns,
                    gauge_state,
                    structural_state_label,
                    cb_strategic_12m_sum_t,
                    cb_tactical_12m_sum_t,
                    cb_diversifier_12m_sum_t,
                    gld_holdings_t,
                    gld_30d_net_flow_t,
                    comex_registered_oz,
                    comex_20d_roc_pct,
                    cot_mm_net_pct,
                    cyclical_zone_label,
                    cpi_yoy,
                    t5yifr,
                    dfii10,
                    dfii10_60d_change_bps,
                    Jsonb(factors_jsonb),
                    valuation_flag,
                    real_price_percentile,
                    gold_m2_ratio_percentile,
                    gold_spx_ratio_percentile,
                    structural_posture_text,
                    cyclical_posture_text,
                    valuation_posture_text,
                    Jsonb(inputs_jsonb),
                    structural_posture_chip,
                    cyclical_posture_chip,
                    valuation_posture_chip,
                    Jsonb(spot_jsonb) if spot_jsonb is not None else None,
                    Jsonb(data_freshness_jsonb)
                    if data_freshness_jsonb is not None
                    else None,
                    Jsonb(decomposition_jsonb)
                    if decomposition_jsonb is not None
                    else None,
                    Jsonb(correlation_history_jsonb)
                    if correlation_history_jsonb is not None
                    else None,
                    Jsonb(gld_history_jsonb) if gld_history_jsonb is not None else None,
                    Jsonb(gold_history_jsonb)
                    if gold_history_jsonb is not None
                    else None,
                    lbma_30d_momentum_t,
                    uw_25d_skew_sigma,
                    fx_basket_dxy_z,
                    xau_cny_premium_pct,
                    cb_52w_pct,
                    cot_mm_4w_change_sigma,
                    t5yifr_pct_52w,
                    dxy,
                    dxy_60d_sigma,
                    gpr_value,
                    gpr_pct_52w,
                ),
            )

    def fetch_gold_posture_latest(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM uw_scan.gold_posture_daily
                WHERE row_status = 'active'
                ORDER BY obs_date DESC, computed_at DESC
                LIMIT 1
                """,
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))

    def fetch_gold_gauge_history(
        self,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
    ) -> list[dict[str, Any]]:
        """Return the first active persisted gauge reading for each market day."""
        clauses = ["row_status = 'active'"]
        params: list[Any] = []
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
                SELECT obs_date, gauge_corr_60d, gauge_corr_252d
                FROM (
                  SELECT DISTINCT ON (obs_date)
                    obs_date, computed_at, gauge_corr_60d, gauge_corr_252d
                  FROM {self._schema}.gold_posture_daily
                  WHERE {where}
                  ORDER BY obs_date ASC, computed_at ASC
                ) AS first_daily
                ORDER BY obs_date ASC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def fetch_gold_posture_as_of(self, as_of: _date) -> dict[str, Any] | None:
        """The newest active posture row for a date AT OR BEFORE ``as_of``.

        Neither existing reader answers this. ``fetch_gold_posture_latest`` returns the
        newest row regardless of the instant being answered for -- fine for the live page,
        lookahead for a replay -- and ``fetch_gold_posture_for_obs_date`` needs an exact
        date, so a state computed on a day the orchestrator did not run would find
        nothing and report UNKNOWN rather than reading the gauge that WAS in force.

        ``computed_at ASC`` within a date matches the replay discipline the exact-date
        reader already uses: the first non-invalidated computation is the one that stood.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM uw_scan.gold_posture_daily
                WHERE obs_date <= %s
                  AND row_status = 'active'
                ORDER BY obs_date DESC, computed_at ASC
                LIMIT 1
                """,
                (as_of,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))

    def fetch_gold_posture_for_obs_date(self, obs_date: _date) -> dict[str, Any] | None:
        """Replay discipline: return the first non-invalidated posture row."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM uw_scan.gold_posture_daily
                WHERE obs_date = %s
                  AND row_status = 'active'
                ORDER BY computed_at ASC
                LIMIT 1
                """,
                (obs_date,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))
