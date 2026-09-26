"""Bounded read-only catalog and cumulative query observations; no workload changes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import psycopg
from psycopg.rows import dict_row

from uw_scan.config import Settings, _load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-root", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    _load_dotenv(args.env_root / ".env.local")
    settings = Settings.from_env(args.env_root / ".env")
    settings = settings.model_copy(update={"db_host": args.host, "db_name": args.database})
    import uw_scan.config

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "import_path": uw_scan.config.__file__,
        "host": args.host,
        "database": args.database,
        "scope": "read-only cumulative observations, not isolated benchmark or causal attribution",
        "queries": {},
    }
    queries = {
        "identity": "SELECT current_database(), current_user, version(), now(), current_setting('transaction_read_only') AS read_only",
        "table_stats": """SELECT relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd,
            n_tup_del, seq_scan, idx_scan, last_autovacuum, last_autoanalyze
            FROM pg_stat_user_tables WHERE schemaname = 'uw_scan'
            AND relname IN ('vrp_daily', 'stock_analytics_daily', 'technical_daily',
                'vol_index_daily', 'realized_volatility_history', 'uw_fetch_memo',
                'external_api_requests', 'option_surface_grid_daily') ORDER BY relname""",
        "stats_reset": "SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()",
        "statement_stats_info": "SELECT * FROM pg_stat_statements_info",
        "statement_summary": """SELECT queryid, calls, total_exec_time, mean_exec_time,
            rows, shared_blks_hit, shared_blks_read, wal_bytes,
            CASE WHEN query ILIKE '%stock_analytics_daily%' THEN 'stock_analytics_daily'
                 WHEN query ILIKE '%technical_daily%' THEN 'technical_daily'
                 WHEN query ILIKE '%vrp_daily%' THEN 'vrp_daily'
                 WHEN query ILIKE '%uw_fetch_memo%' THEN 'uw_fetch_memo'
                 ELSE 'vol_index_daily' END AS target,
            CASE WHEN ltrim(query) ILIKE 'INSERT%' THEN 'INSERT'
                 WHEN ltrim(query) ILIKE 'UPDATE%' THEN 'UPDATE'
                 WHEN ltrim(query) ILIKE 'SELECT%' THEN 'SELECT' ELSE 'OTHER' END AS verb
            FROM pg_stat_statements
            WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
              AND (query ILIKE '%stock_analytics_daily%' OR query ILIKE '%technical_daily%'
                OR query ILIKE '%vrp_daily%' OR query ILIKE '%uw_fetch_memo%'
                OR query ILIKE '%vol_index_daily%')
              AND query NOT ILIKE '%pg_stat_%'
            ORDER BY total_exec_time DESC LIMIT 25""",
        "index_vol_coverage": "SELECT symbol, count(*) AS rows, min(trade_date), max(trade_date) FROM uw_scan.vol_index_daily GROUP BY symbol ORDER BY symbol",
        "technical_coverage": "SELECT ticker, count(*) AS rows, min(as_of), max(as_of) FROM uw_scan.technical_daily WHERE ticker IN ('SPY','NVDA') GROUP BY ticker ORDER BY ticker",
    }
    for name, query in queries.items():
        # Independent connection prevents a failed optional extension read from
        # aborting the remaining observations. No secret-bearing query text saved.
        try:
            with psycopg.connect(
                settings.db_dsn(), connect_timeout=5, row_factory=dict_row,
                options="-c default_transaction_read_only=on -c statement_timeout=8000 -c lock_timeout=1500",
            ) as conn:
                rows = conn.execute(query).fetchall()
            report["queries"][name] = {"sql": query, "rows": rows}
        except psycopg.Error as exc:
            report["queries"][name] = {"sql": query, "error_type": type(exc).__name__, "sqlstate": exc.sqlstate}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, default=str, indent=2) + "\n")
    print(json.dumps({"out": str(args.out), "sections": {k: (len(v["rows"]) if "rows" in v else v) for k,v in report["queries"].items()}}, default=str))


if __name__ == "__main__":
    main()
