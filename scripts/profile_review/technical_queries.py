"""Bounded read-only technical query plans and paired warm comparisons; no DDL."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import psycopg

from uw_scan.config import Settings, _load_dotenv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-root', type=Path, required=True)
    p.add_argument('--host', required=True)
    p.add_argument('--database', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    args = p.parse_args()
    assert 1 <= args.repeats <= 7
    _load_dotenv(args.env_root / '.env.local')
    s = Settings.from_env(args.env_root / '.env').model_copy(update={'db_host': args.host, 'db_name': args.database})
    report = {'captured_at': datetime.now(timezone.utc).isoformat(), 'host': args.host,
              'database': args.database, 'read_only': True, 'plans': {}}
    statements = {
        'latest_macd_all': ('SELECT DISTINCT ON (ticker) ticker, macd_hist_atr FROM uw_scan.technical_daily ORDER BY ticker, as_of DESC', ()),
        'spy_series_1300': ('''SELECT * FROM (SELECT as_of, open, high, low, close, volume,
            sma20, sma50, sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
            rsi14, macd_hist_atr, rs_ratio, metrics, detail, forward_returns
            FROM uw_scan.technical_daily WHERE ticker=%s ORDER BY as_of DESC LIMIT %s) t ORDER BY as_of ASC''', ('SPY', 1300)),
        'spy_latest_detail': ('''SELECT ticker, as_of, open, high, low, close, volume,
            sma20, sma50, sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
            rsi14, macd_hist_atr, rs_ratio, bars_n, detail, forward_returns
            FROM uw_scan.technical_daily WHERE ticker=%s
            ORDER BY (detail IS NOT NULL) DESC, as_of DESC LIMIT 1''', ('SPY',)),
    }
    with psycopg.connect(s.db_dsn(), connect_timeout=5, options='-c default_transaction_read_only=on -c statement_timeout=8000 -c lock_timeout=1500') as c:
        assert c.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        report['indexes'] = c.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='uw_scan' AND tablename='technical_daily'").fetchall()
        c.rollback()
        for name, (sql, params) in statements.items():
            try:
                plan = c.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, params).fetchone()[0]
                report['plans'][name] = {'sql': sql, 'params': params, 'explain': plan}
            except psycopg.Error as exc:
                report['plans'][name] = {'sql': sql, 'params': params, 'error_type': type(exc).__name__, 'sqlstate': exc.sqlstate}
            finally:
                c.rollback()
        # Diagnostic SQL alternative only; application query and schema unchanged.
        # Enumerate the same full ticker domain, then use the existing PK for
        # each latest row, rather than fetching every historical row from heap.
        candidate = '''SELECT tickers.ticker, latest.macd_hist_atr
            FROM (SELECT DISTINCT ticker FROM uw_scan.technical_daily) tickers
            CROSS JOIN LATERAL (
                SELECT macd_hist_atr FROM uw_scan.technical_daily d
                WHERE d.ticker=tickers.ticker ORDER BY d.as_of DESC LIMIT 1
            ) latest ORDER BY tickers.ticker'''
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        baseline_rows = c.execute(statements['latest_macd_all'][0]).fetchall()
        candidate_rows = c.execute(candidate).fetchall()
        assert baseline_rows == candidate_rows, 'Candidate changed latest-MACD output'
        candidate_plan = c.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + candidate).fetchone()[0]
        report['candidate'] = {'sql': candidate, 'rows': len(candidate_rows),
                               'exact_output_equal': True, 'explain': candidate_plan,
                               'limitation': 'single ordered warm-cache observation, not randomized benchmark'}
        report['paired_warm_plans'] = []
        variants = {'baseline': statements['latest_macd_all'][0], 'candidate': candidate}
        for repeat in range(args.repeats):
            order = ('baseline', 'candidate') if repeat % 2 == 0 else ('candidate', 'baseline')
            for variant in order:
                plan = c.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + variants[variant]).fetchone()[0]
                report['paired_warm_plans'].append({'repeat': repeat, 'variant': variant, 'explain': plan})
        c.rollback()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, default=str, indent=2) + '\n')
    print(json.dumps({name: data.get('explain', [{}])[0].get('Execution Time', data.get('error_type')) for name, data in report['plans'].items()}))


if __name__ == '__main__':
    main()
