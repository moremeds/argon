"""One-shot backfill for CRI / VCG / 5% Canary snapshots over a date window.

Why this exists: between 2026-05-21 (last `vol_index_daily` row) and 2026-06-03
(today's latest aligned date) the macmini primary worker was offline, so the
CRI/VCG/Canary cron jobs never fired. The lake-sync has now caught
`vol_index_daily` up; this script loops the existing scanner.run paths once per
trading day in the gap so the regime page history is contiguous.

The scanners always compute against `common_dates[-1]`. To re-aim them at a
historical day we monkey-patch the two data loaders they use
(`VolIndexRepository.fetch_history` and `Repository.list_daily_ohlc`) so they
return rows up to and including `as_of` only. No scanner code changes; no
duplication of scoring logic.

Safe to re-run: cri / vcg use INSERT (multiple rows per day OK; latest wins in
the UI). canary uses ON CONFLICT DO NOTHING keyed on (data_date, composite_version).

Usage:
    uv run python scripts/oneshot/regime_backfill_2026_05.py
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.scanners import canary as canary_scanner
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.repository import Repository
from uw_scan.storage.vol_index_repository import VolIndexRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("regime_backfill")


def _patch_loaders(as_of: date):
    """Cap fetch_history / list_daily_ohlc so common_dates[-1] == as_of."""
    orig_fetch = VolIndexRepository.fetch_history
    orig_list_ohlc = Repository.list_daily_ohlc

    def fetch_history_capped(self, symbol, days):
        rows = orig_fetch(self, symbol, days * 2)
        rows = [r for r in rows if r["trade_date"] <= as_of]
        return rows[-days:] if days and len(rows) > days else rows

    def list_daily_ohlc_capped(self, ticker, limit=None):
        rows = orig_list_ohlc(self, ticker, limit=(limit * 2 if limit else None))
        rows = [r for r in rows if r.date <= as_of]
        return rows[:limit] if limit and len(rows) > limit else rows

    VolIndexRepository.fetch_history = fetch_history_capped
    Repository.list_daily_ohlc = list_daily_ohlc_capped

    def restore():
        VolIndexRepository.fetch_history = orig_fetch
        Repository.list_daily_ohlc = orig_list_ohlc

    return restore


def _trading_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            out.append(d)
        d += timedelta(days=1)
    return out


def main() -> int:
    settings = Settings.from_env()
    days = _trading_days(date(2026, 5, 20), date(2026, 6, 3))
    log.info("backfill window: %s → %s (%d trading days)", days[0], days[-1], len(days))

    conn = psycopg.connect(settings.db_dsn())
    try:
        for d in days:
            log.info("=== %s ===", d.isoformat())
            restore = _patch_loaders(d)
            try:
                # CRI: skip dates ≤ existing latest (2026-05-21) to avoid dup-day rows
                if d > date(2026, 5, 21):
                    try:
                        rid = cri_scanner.run(conn, schema=settings.db_schema)
                        log.info("  cri row_id=%s", rid)
                    except Exception as exc:
                        log.warning("  cri failed: %r", exc)
                        conn.rollback()
                # VCG: skip ≤ 2026-05-19
                if d > date(2026, 5, 19):
                    try:
                        rid = vcg_scanner.run(
                            conn,
                            proxy="HYG",
                            schema=settings.db_schema,
                        )
                        log.info("  vcg row_id=%s", rid)
                    except Exception as exc:
                        log.warning("  vcg failed: %r", exc)
                        conn.rollback()
                # Canary: skip ≤ 2026-05-21
                if d > date(2026, 5, 21):
                    try:
                        rid = canary_scanner.run(conn, schema=settings.db_schema)
                        log.info("  canary row_id=%s", rid)
                    except Exception as exc:
                        log.warning("  canary failed: %r", exc)
                        conn.rollback()
            finally:
                restore()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
