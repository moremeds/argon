"""Catch up the 2 UW-alpha EVENT-LOG tables (uw_intraday_option_flow_bars,
uw_dark_lit_flow_prints) over a date range, and report per-dataset coverage.

The 3 DAILY tables (gex/volatility/short) catch up via the data_gap_healer
(`scripts/backfill/data_gap_healer.py execute`) — its audit->heal->verify IS the
backfill. The event logs have no (ticker,date) uniqueness the healer can audit,
so they backfill via a thin date-loop on the SAME capture fns the nightly cron
runs (no side-channel write path). Resumable: (ticker,date) pairs already present
are skipped, so re-running continues where a budget cap stopped.

Reproduce (local dry-run):
  uv run python scripts/backfill/uw_alpha_catchup.py backfill-eventlog \
      --datasets uw_intraday_option_flow_bars,uw_dark_lit_flow_prints \
      --start 2026-07-02 --end 2026-07-24

  uv run python scripts/backfill/uw_alpha_catchup.py coverage \
      --start 2026-07-02 --end 2026-07-24
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.reports.data_gap_healer import (  # reused session-spine + resume utils
    _calendar_dates,
    _missing_ticker_date_pairs,
)
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository
from uw_scan.worker.jobs.uw_alpha_capture import (
    capture_dark_lit_for,
    capture_intraday_flow_for,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uw_alpha_catchup")

DEFAULT_MAX_UW_CALLS = 20000  # matches DATA_GAP_HEALER_MAX_UW_CALLS

# Event-log tables only. calls_per_pair = UW requests one capture makes per
# (ticker, date): intraday = net_prem_ticks + greek_flow; dark_lit = darkpool +
# lit_flow. The 3 daily tables belong to data_gap_healer, not here.
_EVENTLOG = {
    "uw_intraday_option_flow_bars": (capture_intraday_flow_for, 2),
    "uw_dark_lit_flow_prints": (capture_dark_lit_for, 2),
}
# Every alpha table + its date col, for the read-only coverage trace.
_ALL_DATASETS = (
    "uw_gex_levels_daily",
    "uw_volatility_signal_daily",
    "uw_short_pressure_daily",
    "uw_intraday_option_flow_bars",
    "uw_dark_lit_flow_prints",
)
_RESEARCH_DIR = Path("docs/research/uw-historical-alpha-scan")


def _today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.rth_tz)).date()


def _parse_range(args, settings: Settings) -> tuple[date, date]:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else _today(settings)
    return start, end


def _watchlist(repo: Repository) -> list[str]:
    return [c.ticker.upper() for c in repo.list_watchlist_cards()]


def cmd_backfill_eventlog(args, settings: Settings) -> int:
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    bad = [d for d in datasets if d not in _EVENTLOG]
    if bad:
        logger.error("not event-log datasets (use data_gap_healer for daily): %s", bad)
        return 2
    if not args.confirm:
        logger.info("DRY RUN — pass --confirm to call UW. No requests made.")
    start, end = _parse_range(args, settings)

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        calendar = _calendar_dates(conn, settings.db_schema, start, end)
        tickers = _watchlist(repo)
    logger.info(
        "range %s..%s: %d sessions x %d tickers",
        start,
        end,
        len(calendar),
        len(tickers),
    )

    spent = 0
    summary: dict[str, dict[str, int]] = {}
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    conn = psycopg.connect(settings.db_dsn())
    try:
        repo = Repository(conn, schema=settings.db_schema)
        alpha = UwHistoricalAlphaRepository(conn, schema=settings.db_schema)
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            telemetry_recorder=recorder,
            job_name="uw_alpha_catchup",
        )
        for dataset in datasets:
            capture_fn, per_pair = _EVENTLOG[dataset]
            missing = _missing_ticker_date_pairs(
                conn,
                settings.db_schema,
                dataset,
                "market_date",
                "ticker",
                calendar,
                tickers,
            )
            done = rows = errors = skipped_budget = 0
            for md, ticker in missing:
                if spent + per_pair > args.max_uw_calls:
                    skipped_budget += 1
                    continue
                if not args.confirm:
                    spent += per_pair  # simulate the spend for the dry-run report
                    continue
                run_id = repo.insert_scan_run(
                    ticker, notes=f"uw_alpha_catchup:{dataset}"
                )
                try:
                    n = capture_fn(client, repo, alpha, run_id, ticker, md)
                    repo.finish_scan_run(run_id, status="ok")
                    conn.commit()
                    rows += n
                    done += 1
                    spent += per_pair
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    errors += 1
                    logger.warning(
                        "%s %s %s failed: %s", dataset, ticker, md, repr(exc)
                    )
            summary[dataset] = {
                "missing_pairs": len(missing),
                "captured_pairs": done,
                "rows": rows,
                "errors": errors,
                "skipped_budget": skipped_budget,
            }
            logger.info("%s: %s", dataset, summary[dataset])
    finally:
        recorder.close()
        conn.close()
    logger.info("catch-up complete (uw calls spent=%d): %s", spent, summary)
    return 0


def cmd_coverage(args, settings: Settings) -> int:
    start, end = _parse_range(args, settings)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        calendar = _calendar_dates(conn, settings.db_schema, start, end)
        tickers = _watchlist(repo)
        expected = len(calendar) * len(tickers)
        lines = [
            f"# UW alpha catch-up coverage — {start}..{end}",
            "",
            f"Reproduce: `uv run python scripts/backfill/uw_alpha_catchup.py coverage "
            f"--start {start} --end {end}`",
            "",
            f"Sessions: {len(calendar)} · Watchlist tickers: {len(tickers)} · "
            f"Expected (ticker,date) pairs: {expected}",
            "",
            "| dataset | covered_pairs | missing_pairs | coverage % |",
            "| --- | ---: | ---: | ---: |",
        ]
        for dataset in _ALL_DATASETS:
            missing = _missing_ticker_date_pairs(
                conn,
                settings.db_schema,
                dataset,
                "market_date",
                "ticker",
                calendar,
                tickers,
            )
            covered = expected - len(missing)
            pct = (covered / expected * 100) if expected else 0.0
            lines.append(f"| {dataset} | {covered} | {len(missing)} | {pct:.1f}% |")
    trace = "\n".join(lines) + "\n"
    print(trace)
    out = Path(args.out) if args.out else _RESEARCH_DIR / f"coverage-{end}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(trace)
    logger.info("coverage trace written to %s", out)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backfill-eventlog", help="date-loop backfill the 2 event logs")
    p.add_argument("--datasets", default=",".join(_EVENTLOG))
    p.add_argument("--start", default="2026-07-02")
    p.add_argument("--end", default="")
    p.add_argument("--max-uw-calls", type=int, default=DEFAULT_MAX_UW_CALLS)
    p.add_argument("--confirm", action="store_true", help="actually call UW")
    p.set_defaults(func=cmd_backfill_eventlog)

    p = sub.add_parser("coverage", help="read-only per-dataset coverage trace")
    p.add_argument("--start", default="2026-07-02")
    p.add_argument("--end", default="")
    p.add_argument("--out", default="", help="trace path; default docs/research/...")
    p.set_defaults(func=cmd_coverage)
    return ap


def main() -> int:
    args = _build_parser().parse_args()
    settings = Settings.from_env()  # bare Settings() lacks required api_key
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
