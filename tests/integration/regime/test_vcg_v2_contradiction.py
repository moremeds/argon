from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pandas as pd
import psycopg

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(conn: psycopg.Connection) -> None:
    vol_df = pd.read_parquet(FIXTURE_DIR / "seven_crisis_vol_complex.parquet")
    with conn.cursor() as cur:
        for _, row in vol_df.iterrows():
            trade_date = pd.Timestamp(row["trade_date"]).date()
            for symbol, value, adj_close in (
                ("VIX", row["vix"], None),
                ("VVIX", row["vvix"], None),
                ("SPX", row["spx_close"], None),
                ("HYG", row["hyg"], row["hyg"]),
            ):
                cur.execute(
                    "INSERT INTO uw_scan.vol_index_daily "
                    "(symbol, trade_date, close, adj_close) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (symbol, trade_date) DO UPDATE SET "
                    "close = EXCLUDED.close, adj_close = EXCLUDED.adj_close",
                    (symbol, trade_date, value, adj_close),
                )
    conn.commit()


def _subprocess_db_env(conn: psycopg.Connection) -> dict[str, str]:
    info = conn.info
    env = dict(os.environ)
    if info.host:
        env["UW_SCAN_DB_HOST"] = str(info.host)
    if info.port:
        env["UW_SCAN_DB_PORT"] = str(info.port)
    env["UW_SCAN_DB_NAME"] = str(info.dbname)
    env["UW_SCAN_DB_USER"] = str(info.user)
    if info.password:
        env["UW_SCAN_DB_PASSWORD"] = str(info.password)
    env.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return env


def _run_backtest_vcg(conn: psycopg.Connection) -> None:
    proc = subprocess.run(
        ["uv", "run", "scripts/backtest_vcg.py"],
        env=_subprocess_db_env(conn),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"backtest_vcg failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )


def _latest_v2_run_id(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM uw_scan.regime_backtest_runs "
            "WHERE indicator = 'vcg' AND composite_version = '2' "
            "  AND run_scope = 'production' AND completed_at IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None, "expected a completed v=2 production run"
    return int(row[0])


def test_vcg_v2_produces_zero_panic_suppressed_contradictions(
    seeded_db_empty_cards,
) -> None:
    conn = seeded_db_empty_cards.conn
    _load_fixture(conn)
    _run_backtest_vcg(conn)
    run_id = _latest_v2_run_id(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s AND payload->>'interpretation' IS NULL",
            (run_id,),
        )
        missing_interpretation = cur.fetchone()[0]
    assert missing_interpretation == 0

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s "
            "  AND payload->>'regime' = 'PANIC' "
            "  AND payload->>'interpretation' = 'SUPPRESSED'",
            (run_id,),
        )
        contradiction_count = cur.fetchone()[0]

    assert contradiction_count == 0
