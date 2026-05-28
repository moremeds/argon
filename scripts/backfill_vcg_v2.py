"""One-shot production backfill for VCG composite_version=2."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess

import psycopg

from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION
from uw_scan.config import Settings

log = logging.getLogger(__name__)

_LOCK_KEY = "vcg:v2:production:HYG:single_proxy"
_DB_ENV_WHITELIST = (
    "UW_SCAN_DB_NAME",
    "UW_SCAN_DB_HOST",
    "UW_SCAN_DB_PORT",
    "UW_SCAN_DB_USER",
    "UW_SCAN_DB_PASSWORD",
    "PATH",
    "HOME",
    "USER",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-shot VCG v2 backfill")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if a completed v2 production row already exists",
    )
    return parser.parse_args()


def _build_backtest_argv() -> list[str]:
    return ["uv", "run", "scripts/backtest_vcg.py"]


def _subprocess_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _DB_ENV_WHITELIST}
    env.setdefault("UW_SCAN_API_KEY", "backfill-dummy-not-used-by-db-only-job")
    return env


def _existing_v2_run_id(conn: psycopg.Connection) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM uw_scan.regime_backtest_runs
            WHERE indicator = 'vcg'
              AND composite_version = '2'
              AND run_scope = 'production'
              AND credit_proxy = 'HYG'
              AND composite_method = 'single_proxy'
              AND completed_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def _verify_gate1_integrity(conn: psycopg.Connection, run_id: int, n_days: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily WHERE run_id = %s",
            (run_id,),
        )
        actual_rows = int(cur.fetchone()[0])
        if actual_rows != n_days:
            log.error("daily row count %d != n_days %d for run_id=%d", actual_rows, n_days, run_id)
            return 3

        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s AND payload->>'interpretation' IS NULL",
            (run_id,),
        )
        null_interpretation = int(cur.fetchone()[0])
        if null_interpretation != 0:
            log.error("%d rows have NULL payload.interpretation", null_interpretation)
            return 4

        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s "
            "  AND payload->>'regime' = 'PANIC' "
            "  AND payload->>'interpretation' = 'SUPPRESSED'",
            (run_id,),
        )
        contradictions = int(cur.fetchone()[0])
        if contradictions != 0:
            log.error("Gate 1 failed post-backfill: %d contradictions", contradictions)
            return 5
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    if COMPOSITE_VERSION != 2:
        raise RuntimeError(
            "backfill_vcg_v2 requires vcg_scoring.COMPOSITE_VERSION == 2; "
            f"got {COMPOSITE_VERSION}"
        )

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (_LOCK_KEY,))
        conn.commit()
        try:
            existing_id = _existing_v2_run_id(conn)
            if existing_id is not None and not args.force:
                log.info("v2 production row already exists (run_id=%d)", existing_id)
                return 0

            log.info("running scripts/backtest_vcg.py with default production args")
            proc = subprocess.run(_build_backtest_argv(), env=_subprocess_env(), text=True)
            if proc.returncode != 0:
                log.error("backtest_vcg failed with exit %d", proc.returncode)
                return int(proc.returncode)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_LOCK_KEY,))
            conn.commit()

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, composite_version, run_scope, credit_proxy, composite_method, n_days
            FROM uw_scan.regime_backtest_runs
            WHERE indicator = 'vcg'
              AND composite_version = '2'
              AND run_scope = 'production'
              AND credit_proxy = 'HYG'
              AND composite_method = 'single_proxy'
              AND completed_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        log.error("no completed v2 row after backtest_vcg ran")
        return 2

    run_id, cv, rs, cp, cm, n_days = row
    if not (cv == "2" and rs == "production" and cp == "HYG" and cm == "single_proxy"):
        log.error("new row has wrong provenance: %s %s %s %s", cv, rs, cp, cm)
        return 6

    with psycopg.connect(settings.db_dsn()) as conn:
        rc = _verify_gate1_integrity(conn, int(run_id), int(n_days))
        if rc != 0:
            return rc

    log.info("v2 production backfill complete: run_id=%d n_days=%d", run_id, n_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
