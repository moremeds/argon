"""Read-only DB input capture and offline replay; never benchmark write execution."""
from __future__ import annotations

import argparse
import cProfile
import copy
import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics
import inspect
import re
import time

import psycopg
import uw_scan
from uw_scan.config import Settings, _load_dotenv
from uw_scan.reports.volatility_series import assemble_volatility_series
from uw_scan.reports.vrp_macro_drawdown import _build_loaded
from uw_scan.storage.repository import Repository
from uw_scan.storage.rows import DailyOhlcRow
from uw_scan.reports.single_stock import assemble_single_stock_report

ROOT = Path(__file__).resolve().parents[2]


def encode(value):
    if isinstance(value, (date, datetime, Decimal)):
        return {'_profile_type': type(value).__name__, 'value': str(value)}
    if dataclasses.is_dataclass(value):
        return {'_profile_type': type(value).__name__, 'value': dataclasses.asdict(value)}
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    raise TypeError(type(value).__name__)


def decode(value):
    if set(value) != {'_profile_type', 'value'}:
        return value
    constructors = {'date': date.fromisoformat, 'datetime': datetime.fromisoformat,
                    'Decimal': Decimal, 'DailyOhlcRow': lambda x: DailyOhlcRow(**x)}
    return constructors[value['_profile_type']](value['value'])


class ObservedCursor(psycopg.Cursor):
    records = None

    def execute(self, query, params=None, **kwargs):
        sql = query.as_string(self.connection) if hasattr(query, 'as_string') else str(query)
        normalized = re.sub(r'\s+', ' ', sql).strip()
        # PostgreSQL READ ONLY additionally rejects writes nested in a WITH.
        statement = re.sub(r'--[^\n]*', '', sql).lstrip()
        schema_setting = bool(re.fullmatch(r'SET search_path TO [a-z_]+, public', normalized))
        if self.records is not None and not statement.upper().startswith(('SELECT', 'WITH')) and not schema_setting:
            self.records.append({'blocked_sql': normalized})
            raise RuntimeError('Non-SELECT blocked by stock query recorder')
        started = time.perf_counter()
        answer = super().execute(query, params, **kwargs)
        elapsed = time.perf_counter() - started
        if self.records is not None:
            callers = [f'{Path(f.filename).name}:{f.function}:{f.lineno}'
                       for f in inspect.stack()[1:8] if '/uw_scan/' in f.filename]
            self.records.append({'kind': 'session_setting' if schema_setting else 'select', 'sql': normalized, 'query_sha256': digest(normalized),
                'params_sha256': digest(params), 'rows': self.rowcount,
                'execute_seconds': elapsed, 'callers': callers})
        return answer


def packed(value):
    return json.dumps(value, default=encode, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class CapturedRepo:
    """Capture actual read results; intercept the only authorized write intentions."""
    def __init__(self, repo=None, reads=None):
        self.repo = repo
        self.reads = reads if reads is not None else {}
        self.calls = []
        self.writes = []
        self.commits = 0
        self.conn = self

    def commit(self):
        self.commits += 1

    def __getattr__(self, name):
        if name in {'upsert_vrp_daily_rows', 'upsert_stock_analytics_rows'}:
            def intended(rows):
                rows = list(rows)
                self.writes.append({'method': name, 'rows': len(rows), 'sha256': digest(rows)})
                return len(rows)
            return intended
        if not name.startswith(('fetch_', 'list_', 'latest_')):
            raise AttributeError(f'Unapproved repository boundary: {name}')
        def read(*args, **kwargs):
            key = packed([name, args, kwargs])
            self.calls.append(name)
            if self.repo is not None:
                value = getattr(self.repo, name)(*args, **kwargs)
                self.reads[key] = copy.deepcopy(value)
            else:
                value = self.reads[key]
            return copy.deepcopy(value)
        return read


def measure(fn, repeats, profile_path):
    wall, cpu = [], []
    for _ in range(repeats):
        w, c = time.perf_counter(), time.process_time()
        fn()
        wall.append(time.perf_counter() - w)
        cpu.append(time.process_time() - c)
    profiler = cProfile.Profile()
    profiler.runcall(fn)
    profiler.dump_stats(str(profile_path))
    return {'wall_seconds': wall, 'cpu_seconds': cpu,
            'wall_median': statistics.median(wall), 'cpu_median': statistics.median(cpu)}


def stock_static_counts():
    # Explicit source-level duplicate sites; not a measured total query count.
    import ast
    files = ['src/uw_scan/reports/single_stock.py', 'src/uw_scan/cards/dealer_regime.py']
    names = {'fetch_realized_vol_latest', 'fetch_exposures_aggregate',
             'fetch_exposures_summary', 'get_strike_gex_curve'}
    result = {}
    for file in files:
        tree = ast.parse((ROOT / file).read_text())
        result[file] = [{'method': n.func.attr, 'line': n.lineno}
                        for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in names]
    return {'classification': 'static duplicate call sites, not observed SQL count', 'sites': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-root', type=Path, required=True)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--db-host')
    parser.add_argument('--db-name')
    parser.add_argument('--replay-from', type=Path)
    parser.add_argument('--capture-only', action='store_true')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert ROOT / 'src' / 'uw_scan' in Path(uw_scan.__file__).resolve().parents
    assert args.repeats > 0
    args.output.mkdir(parents=True, exist_ok=True)
    if args.replay_from:
        captured = json.loads((args.replay_from / 'captured-inputs.json').read_text(), object_hook=decode)
        result = json.loads((args.replay_from / 'results.json').read_text(), object_hook=decode)
        recorder = CapturedRepo(reads=captured['volatility_reads'])
        recorder.writes = result['volatility'].get('intended_writes', [])
        recorder.commits = result['volatility'].get('intercepted_commits', 0)
        finish(args, captured, result, recorder, captured['vrp_input'])
        return
    _load_dotenv(args.env_root / '.env.local')
    _load_dotenv(args.env_root / '.env')
    settings = Settings.from_env(env_path=args.env_root / '.env')
    overrides = {k: v for k, v in {'db_host': args.db_host, 'db_name': args.db_name}.items() if v}
    settings = settings.model_copy(update=overrides)
    captured = {}
    result = {'captured_at_utc': datetime.now(UTC).isoformat(),
              'calendar_date': date.today().isoformat(), 'source': {
        'host': settings.db_host, 'database': settings.db_name,
        'schema': settings.db_schema, 'ticker': args.ticker,
        'module': uw_scan.__file__}, 'limitations': [
        'Offline compute timings include copying captured inputs and model assembly.',
        'Persistence interception counts intent only; no INSERT/UPDATE/WAL timing.',
        'No HTTP, serialization transport, pool wait, or concurrent load timing.',
        'VRP compares historical feature construction, not full live endpoint/strike pricing.'],
        'stock': stock_static_counts()}
    with psycopg.connect(settings.db_dsn(),
                         options='-c default_transaction_read_only=on -c statement_timeout=8000',
                         autocommit=False, cursor_factory=ObservedCursor) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with conn.cursor() as cur:
            cur.execute('SHOW transaction_read_only')
            assert cur.fetchone()[0] == 'on'
            cur.execute('SELECT version(), current_database(), now()')
            version, database, db_now = cur.fetchone()
            result['source'].update(server=version, database=database, db_now=str(db_now))
        repo = Repository(conn, schema=settings.db_schema)
        recorder = CapturedRepo(repo)
        started = time.perf_counter()
        try:
            response = assemble_volatility_series(ticker=args.ticker, repo=recorder)
            result['volatility'] = {'capture_seconds': time.perf_counter() - started,
                'read_method_calls': recorder.calls, 'intended_writes': recorder.writes,
                'intercepted_commits': recorder.commits,
                'response_sha256': digest(response)}
            captured['volatility_reads'] = recorder.reads
        except Exception as exc:
            # Exception type only: DSNs/credentials never enter artifacts.
            result['volatility'] = {'blocked_exception_type': type(exc).__name__,
                                    'read_method_calls': recorder.calls}
            captured['volatility_reads'] = recorder.reads
        with conn.cursor() as cur:
            cur.execute('SELECT symbol, trade_date, close::float8 FROM '
                        'uw_scan.vol_index_daily WHERE symbol IN (%s,%s) '
                        'AND trade_date >= %s ORDER BY symbol, trade_date',
                        ('SPX', 'VIX', date(2006, 1, 1)))
            rows = cur.fetchall()
            captured['vrp_input'] = rows
        stock_records = []
        ObservedCursor.records = stock_records
        try:
            stock_run = repo.latest_run_id(args.ticker)
            stock_report = assemble_single_stock_report(args.ticker, stock_run, repo)
            result['stock']['observed'] = {'run_id': stock_run,
                'statement_count': len(stock_records),
                'select_count': sum(r.get('kind') == 'select' for r in stock_records),
                'session_setting_count': sum(r.get('kind') == 'session_setting' for r in stock_records), 'report_sha256': digest(stock_report),
                'queries': stock_records}
        except Exception as exc:
            result['stock']['observed'] = {'blocked_exception_type': type(exc).__name__,
                'statement_count': len(stock_records), 'queries': stock_records}
        finally:
            ObservedCursor.records = None
        conn.rollback()
    finish(args, captured, result, recorder, rows)


def finish(args, captured, result, recorder, rows):
    if args.capture_only:
        (args.output / 'captured-inputs.json').write_text(packed(captured) + '\n')
        result['input_sha256'] = digest(captured)
        (args.output / 'results.json').write_text(packed(result) + '\n')
        print(packed({'output': str(args.output), 'capture_only': True}))
        return
    if 'response_sha256' in result['volatility']:
        import uw_scan.reports.volatility_series as volatility_module

        # Older same-session captures predate this metadata; recover local date.
        result.setdefault('calendar_date', datetime.fromisoformat(
            result['captured_at_utc']).astimezone().date().isoformat())
        captured_day = date.fromisoformat(result['calendar_date'])

        class CapturedDate(date):
            @classmethod
            def today(cls):
                return captured_day

        volatility_module._date = CapturedDate

        def replay():
            r = CapturedRepo(reads=recorder.reads)
            response = assemble_volatility_series(ticker=args.ticker, repo=r)
            return response, r
        verified, replay_repo = replay()
        assert digest(verified) == result['volatility']['response_sha256']
        assert replay_repo.writes == recorder.writes
        assert replay_repo.commits == recorder.commits
        result['volatility']['replay'] = measure(replay, args.repeats, args.output / 'volatility.prof')
        result['volatility']['inputs'] = [
            {'method_key': key, 'rows': len(value) if isinstance(value, list) else None,
             'sha256': digest(value)} for key, value in recorder.reads.items()]
    spot = {d: v for s, d, v in rows if s == 'SPX' and v is not None}
    vol = {d: v for s, d, v in rows if s == 'VIX' and v is not None}
    dates = sorted(spot.keys() & vol.keys())
    result['vrp'] = {'spx_rows': len(spot), 'vix_rows': len(vol), 'aligned_rows': len(dates),
                     'asof': str(dates[-1]) if dates else None,
                     'first_date': str(dates[0]) if dates else None}
    if len(dates) < 272:
        result['vrp']['blocked'] = 'Need at least 272 aligned actual observations; no synthetic replacement.'
    else:
        short = dates[-272:]
        small_spot, small_vol = {d: spot[d] for d in short}, {d: vol[d] for d in short}
        def build(s, v):
            return _build_loaded(s, v, rv_window=20, z_window=252)
        full, bounded = build(spot, vol), build(small_spot, small_vol)
        # The first 20 aligned rows warm up RV; final 252 VRP values must match.
        a, b = full.rows[-252:], bounded.rows[-252:]
        assert all(x['market_date'] == y['market_date'] and x['vrp'] == y['vrp']
                   and x['rv'] == y['rv'] for x, y in zip(a, b, strict=True))
        assert full.rows[-1]['vrp_z_20'] == bounded.rows[-1]['vrp_z_20']
        result['vrp']['final_row_equal'] = full.rows[-1] == bounded.rows[-1]
        result['vrp']['full'] = measure(lambda: build(spot, vol), args.repeats, args.output / 'vrp-full.prof')
        result['vrp']['bounded'] = measure(lambda: build(small_spot, small_vol), args.repeats, args.output / 'vrp-bounded.prof')
        result['vrp']['bounded_rows'] = len(short)
        result['vrp']['last_row'] = full.rows[-1]
    (args.output / 'captured-inputs.json').write_text(packed(captured) + '\n')
    result['input_sha256'] = digest(captured)
    (args.output / 'results.json').write_text(packed(result) + '\n')
    print(packed({'output': str(args.output), 'vrp_rows': len(dates),
                  'volatility_ready': 'replay' in result['volatility']}))


if __name__ == '__main__':
    main()
