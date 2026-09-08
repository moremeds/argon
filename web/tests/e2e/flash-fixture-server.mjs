// Serve exported Helium channel payloads to the REAL Next Flash routes.
// Local test adapter only; no database, network fetches, or generated market data.
// Usage: PORT=18407 node tests/e2e/flash-fixture-server.mjs <payload.json> [...]
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const rows = process.argv.slice(2).map((path) => {
  const row = JSON.parse(readFileSync(path, 'utf8'));
  if (!row.run_id || !row.view || !row.week_key) throw new Error(`not a channel payload: ${path}`);
  return { ...row, version_no: 1, created_at: row.run_day };
});
if (!rows.length) throw new Error('provide exported Flash payloads');
const index = rows.map((row) => Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'view' && key !== 'report')));
const tenant = rows[0].tenant;
const weeks = [...new Set(rows.map((row) => row.week_key))].sort().reverse().map((week_key) => {
  const group = rows.filter((row) => row.week_key === week_key);
  const days = group.map((row) => row.run_day).sort();
  return { week_key, first_day: days[0], last_day: days.at(-1), run_count: group.length, day_count: new Set(days).size };
});
const json = (res, body, status = 200) => {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
};
createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (req.method !== 'GET') return json(res, { detail: 'read-only fixture' }, 405);
  const path = url.pathname;
  if (path === '/health') return json(res, { fixture: true, runs: rows.length });
  if (path === '/api/agent-runs/weeks') return json(res, { tenant, weeks });
  if (path.startsWith('/api/agent-runs/week/')) {
    const week_key = path.split('/').at(-1);
    return json(res, { tenant, week_key, runs: index.filter((row) => row.week_key === week_key) });
  }
  if (path.startsWith('/api/agent-runs/run/')) {
    const [, , , , kind, day] = path.split('/');
    const row = rows.find((r) => r.kind === kind && r.run_day === day);
    return json(res, row ?? { detail: 'not recorded' }, row ? 200 : 404);
  }
  if (path === '/api/agent-runs/latest') {
    const row = rows.filter((r) => !url.searchParams.has('kind') || r.kind === url.searchParams.get('kind')).at(-1);
    return json(res, row ?? { detail: 'not recorded' }, row ? 200 : 404);
  }
  if (path === '/api/watchlist') return json(res, { tickers: [] });
  if (path === '/api/watchlist/spots') return json(res, { spots: [] });
  return json(res, {});
}).listen(Number(process.env.PORT ?? 18407), '127.0.0.1');
