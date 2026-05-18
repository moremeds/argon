"""Print WGC/IFS central-bank gold reserve coverage from the warm store."""

from __future__ import annotations

import argparse
from typing import Any

import psycopg

from uw_scan.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--country",
        help="Optional ISO3 filter, e.g. CHN or USA.",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        _print_summary(conn, args.country.upper() if args.country else None)


def _print_summary(conn: psycopg.Connection[Any], country_iso3: str | None) -> None:
    country_filter = "WHERE country_iso3 = %s" if country_iso3 else ""
    params = (country_iso3,) if country_iso3 else ()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) AS rows,
                   count(DISTINCT country_iso3) AS countries,
                   min(obs_month) AS first_month,
                   max(obs_month) AS latest_month
            FROM uw_scan.cb_gold_reserves_monthly
            {country_filter}
            """,
            params,
        )
        rows, countries, first_month, latest_month = cur.fetchone()
        print(
            "summary "
            f"rows={rows} countries={countries} "
            f"first_month={first_month} latest_month={latest_month}"
        )

        cur.execute(
            f"""
            SELECT country_iso3, count(*) AS rows, min(obs_month), max(obs_month)
            FROM uw_scan.cb_gold_reserves_monthly
            {country_filter}
            GROUP BY country_iso3
            ORDER BY country_iso3
            """,
            params,
        )
        for iso3, row_count, first_obs, latest_obs in cur.fetchall():
            print(
                f"{iso3} rows={row_count} first_month={first_obs} "
                f"latest_month={latest_obs}"
            )


if __name__ == "__main__":
    main()
