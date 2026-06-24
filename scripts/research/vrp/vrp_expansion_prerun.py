#!/usr/bin/env python
"""VRP research-expansion pre-run reporter (the "show me the output" demo).

Optionally ingests massive fundamentals (filing_date earnings leg) + corporate
actions, runs all five research axes, and prints every result table as an
aligned ASCII table — mirroring the original VRP note's §3 pre-run output.

Usage (MacBook against the local dev DB):
    UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_local \\
        uv run python scripts/research/vrp_expansion_prerun.py [--skip-ingest] [--horizons 5,20,60]

Honors UW_SCAN_ALLOW_DB_MISMATCH=1 for one-off mini browsing. Note: it WRITES the
research tables (full-rewrite), so point it at a DB you own.
"""

from __future__ import annotations

import argparse

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_directional import run_vrp_directional, run_vrp_dvrp_reversion
from uw_scan.reports.vrp_harvest_axes import (
    run_vrp_harvest_by_sector,
    run_vrp_harvest_multihorizon,
)
from uw_scan.reports.vrp_rv_validation import run_vrp_rv_validation
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once
from uw_scan.worker.jobs.fundamentals_jobs import fundamentals_refresh_once


def _fmt(v: object) -> str:
    if v is None:
        return "."
    if isinstance(v, float):
        return f"{v:+.4f}"
    return str(v)


def _print_table(title: str, rows: list[dict], cols: list[str]) -> None:
    print(f"\n=== {title} ({len(rows)} rows) ===")
    if not rows:
        print("(no rows)")
        return
    widths = {c: max(len(c), *(len(_fmt(r.get(c))) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(_fmt(r.get(c)).ljust(widths[c]) for c in cols))


def _maybe_ingest(repo: Repository, settings: Settings) -> None:
    if settings.massive_api_key is None:
        print("MASSIVE_API_KEY unset → skipping ingest (using existing data).")
        return
    from uw_scan.sources.massive_fundamentals import MassiveFundamentalsProvider

    provider = MassiveFundamentalsProvider(settings.massive_api_key.get_secret_value())
    try:
        nf = fundamentals_refresh_once(repo, provider)
        nc = corporate_actions_refresh_once(repo, provider)
        print(f"Ingest: fundamentals={nf} tickers, corporate-actions={nc} tickers.")
    finally:
        provider.close()


def _coverage_line(repo: Repository) -> None:
    universe = repo.fetch_distinct_vrp_tickers()
    with_ca = sum(1 for t in universe if repo.fetch_corporate_actions(t))
    with_earn = sum(1 for t in universe if repo.fetch_historical_earnings_dates(t))
    n = len(universe)
    print(
        f"\nCoverage: {n} vrp_daily tickers | "
        f"{with_ca} have ≥1 corporate action | {with_earn} have ≥1 earnings date."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--horizons", default="5,20,60")
    args = ap.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(","))

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        if not args.skip_ingest:
            _maybe_ingest(repo, settings)
        _coverage_line(repo)

        print("\nRunning research axes...")
        print("  rv_validation:", run_vrp_rv_validation(repo=repo, horizons=horizons))
        print("  by_sector:", run_vrp_harvest_by_sector(repo=repo))
        print(
            "  multihorizon:",
            run_vrp_harvest_multihorizon(repo=repo, horizons=horizons),
        )
        print("  directional:", run_vrp_directional(repo=repo, horizons=horizons))
        print("  dvrp:", run_vrp_dvrp_reversion(repo=repo, horizons=horizons))

        _print_table(
            "RV approximation-vs-exact validation (item 1)",
            repo.fetch_vrp_rv_validation(),
            ["ticker", "horizon", "n", "mean_abs_dev", "mean_signed_dev", "corr"],
        )
        _print_table(
            "Single-name harvest by sector (item 2)",
            repo.fetch_vrp_harvest_by_sector(),
            [
                "sector",
                "deviation_class",
                "verdict",
                "mean_realized_vrp",
                "rich_cheap_spread",
                "n",
            ],
        )
        _print_table(
            "Harvest decay by horizon (item 4)",
            repo.fetch_vrp_harvest_multihorizon(),
            [
                "asset_class",
                "deviation_class",
                "horizon",
                "verdict",
                "mean_realized_vrp",
                "n",
            ],
        )
        _print_table(
            "Directional RICH−CHEAP differential (item 5a)",
            repo.fetch_vrp_directional_verdicts(),
            [
                "asset_class",
                "horizon",
                "verdict",
                "mean_differential",
                "mean_rich_return",
                "mean_cheap_return",
                "n",
            ],
        )
        _print_table(
            "ΔVRP reversion (item 5b)",
            repo.fetch_vrp_dvrp_reversion(),
            [
                "asset_class",
                "deviation_class",
                "horizon",
                "verdict",
                "mean_fwd_dvrp",
                "n",
            ],
        )


if __name__ == "__main__":
    main()
