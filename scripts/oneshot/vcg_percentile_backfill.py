"""One-shot backfill for VCG snapshots missing vix/vvix percentile_rank fields.

Why this exists: between 2026-05-15 and 2026-06-03, every persisted
``vcg_snapshots`` row has ``payload->signal->vix_percentile_rank = null``
because ``scanners/vcg.py`` loaded ``LOOKBACK_DAYS=200`` while
``vcg_scoring.VOL_PERCENTILE_WINDOW=252``. The rolling window never had
enough bars and ``compute_rolling_percentile_rank`` silently returned NaN,
which ``_round_or_none`` then turned into ``None``. The constant was bumped
to ``LOOKBACK_DAYS=300`` so new scans populate the field — this script
re-runs the scanner once per distinct ``data_date`` so the historical rows
stop showing "—" on the regime page's Signal Detail tile.

The scanner always computes against ``common_dates[-1]``. To re-aim it at a
historical day we monkey-patch ``VolIndexRepository.fetch_history`` so it
returns rows up to and including ``as_of`` only. Same pattern as
``regime_backfill_2026_05.py``.

Safe to re-run: vcg uses INSERT (multiple rows per day OK; ``fetch_latest``
returns ORDER BY scanned_at DESC LIMIT 1, so the freshest backfill wins).

**Where to run:** the macmini launchd worker host (the canonical writer for
``option_wizard``). Running from the MacBook against the mini DB is allowed
by the tripwire if ``.env.local`` overrides both host and db name, but the
hourly cron on the mini will produce the same fix on its own — this script
just shortcuts that for the existing historical rows.

Usage:
    uv run python scripts/oneshot/vcg_percentile_backfill.py
    uv run python scripts/oneshot/vcg_percentile_backfill.py --dry-run
    uv run python scripts/oneshot/vcg_percentile_backfill.py --proxy HYG
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.storage.vol_index_repository import VolIndexRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("vcg_percentile_backfill")


def _patch_loader(as_of: date):
    """Cap ``VolIndexRepository.fetch_history`` so ``common_dates[-1] == as_of``."""
    orig_fetch = VolIndexRepository.fetch_history

    def fetch_history_capped(self, symbol, days):
        rows = orig_fetch(self, symbol, days * 2)
        rows = [r for r in rows if r["trade_date"] <= as_of]
        return rows[-days:] if days and len(rows) > days else rows

    VolIndexRepository.fetch_history = fetch_history_capped

    def restore():
        VolIndexRepository.fetch_history = orig_fetch

    return restore


def _stale_data_dates(conn: psycopg.Connection, schema: str, proxy: str) -> list[date]:
    """Distinct ``data_date`` values whose latest row for ``proxy`` lacks vix_pr."""
    sql = f"""
        SELECT data_date
          FROM {schema}.vcg_snapshots
         WHERE data_date IS NOT NULL
           AND credit_proxy = %s
         GROUP BY data_date
        HAVING bool_and(
                 payload->'signal'->>'vix_percentile_rank' IS NULL
              OR payload->'signal'->>'vix_percentile_rank' = 'null'
               )
         ORDER BY data_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (proxy,))
        return [r[0] for r in cur.fetchall()]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proxy", default=vcg_scanner.DEFAULT_PROXY)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List dates that would be backfilled without inserting.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    settings = Settings.from_env()
    log.info(
        "target: %s/%s schema=%s proxy=%s",
        settings.db_host,
        settings.db_name,
        settings.db_schema,
        args.proxy,
    )

    conn = psycopg.connect(settings.db_dsn())
    try:
        dates = _stale_data_dates(conn, settings.db_schema, args.proxy)
        log.info("found %d data_date(s) with all-null vix_percentile_rank", len(dates))
        for d in dates:
            log.info("  stale: %s", d.isoformat())
        if args.dry_run or not dates:
            return 0

        inserted = 0
        for d in dates:
            log.info("=== %s ===", d.isoformat())
            restore = _patch_loader(d)
            try:
                # The monkey-patch above caps fetch_history at as_of; vcg.run()
                # then aligns to common_dates[-1] = as_of with no as_of kwarg
                # needed. This keeps the script independent of the as_of-aware
                # scanner signature (added in a sibling branch / PR #115).
                row_id = vcg_scanner.run(
                    conn,
                    proxy=args.proxy,
                    schema=settings.db_schema,
                )
                if row_id is None:
                    log.warning("  skipped (thin data)")
                else:
                    log.info("  vcg row_id=%s inserted", row_id)
                    inserted += 1
            except Exception as exc:
                log.warning("  vcg failed: %r", exc)
                conn.rollback()
            finally:
                restore()
        log.info("backfill complete: %d/%d days re-scanned", inserted, len(dates))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
