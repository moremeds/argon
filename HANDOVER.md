# Handover — `feat/regime-gex-intraday-chart`

PR: <https://github.com/moremeds/argon/pull/121>
Branch: `feat/regime-gex-intraday-chart` (2 commits ahead of `main`)
Worktree: `/Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart/`

## What this branch does

1. **New backend endpoint** `GET /api/regime/gex/intraday?ticker=SPX&sessions=5&rth_only=true`.
   Returns the last N **ET trading sessions** of intraday `gex_snapshots` rows. Each
   point carries `ts` (UTC ISO), `spot`, `net_gex`, `gex_flip`, `iv30d`. Grouped by
   ET date so UTC `data_date` straddling doesn't bleed sessions into each other.

2. **New chart component** `GexIntradayChart` rendered above the existing daily
   `HistoryChart` on the GEX tab. Card frame, legend (SPOT / GEX FLIP / NET GEX /
   IV 30D), per-session date dividers (MM/DD), intraday tick marks at 09:30 /
   12:00 / 16:00 ET, dual y-axis.

3. **Daily HistoryChart upgraded** with the same visual frame: title, legend,
   x-axis date anchors, dual y-axis tick labels. SVG paths unchanged.

Files touched:

```
src/uw_scan/api/routers/regime.py              | +30 lines  (new route)
src/uw_scan/api/schemas.py                     | +30 lines  (GexIntradayResponse/Session/Point)
src/uw_scan/storage/gex.py                     | +67 lines  (fetch_intraday_sessions)
tests/integration/test_gex_repository.py       | +65 lines  (new integration test)
web/components/regime/GexSubTab.tsx            |   ±8 lines (mount intraday chart)
web/components/regime/HistoryChart.tsx         | rewritten  (card + legend + axes)
web/components/regime/gex/GexIntradayChart.tsx | NEW
web/lib/regime/api.ts                          |  +2 lines  (gex_intraday URL)
web/lib/regime/useGexIntraday.ts               | NEW
web/tests/unit/gexIntradayChart.test.tsx       | NEW (5 tests)
```

## Quick setup in a fresh session

The worktree is already provisioned. From any new shell:

```bash
cd /Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart

# Verify you're on the right branch
git branch --show-current        # → feat/regime-gex-intraday-chart
git log --oneline main..HEAD     # → 2 commits

# .env lives in the canonical worktree; the dev API + DB come from there.
ls -la ../../.env                # links via parent
```

## How to run locally (mirrors what the verification session did)

### 1. Start a worktree-coded FastAPI on port 8401

The main repo's API on port 8400 is the live production process — it doesn't
know about the new endpoint. Spin up a separate one against this branch's
code using the main repo's `.venv` (the worktree `.venv` lacks `psycopg-binary`).

```bash
cd /Users/moremeds/projects/argon
env $(grep -v '^#' .env | xargs) \
  PYTHONPATH=/Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart/src \
  /Users/moremeds/projects/argon/.venv/bin/python -c "
import uvicorn
from uw_scan.api.server import app
uvicorn.run(app, host='127.0.0.1', port=8401, log_level='info')
"
```

Smoke-test:

```bash
curl -s 'http://127.0.0.1:8401/api/regime/gex/intraday?ticker=SPX&sessions=5' \
  | python3 -m json.tool | head -40
# Expect 5 sessions (06/04, 06/05, 06/08, 06/09, 06/10 as of 2026-06-11),
# ~74-78 points each.
```

### 2. Start Next.js dev on port 3100, pointed at the worktree API

The worktree shares `web/node_modules` with the main repo via a symlink so no
`pnpm install` is needed.

```bash
cd /Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart/web
NEXT_INTERNAL_API_BASE=http://127.0.0.1:8401 \
  ./node_modules/.bin/next dev -p 3100
```

Open <http://localhost:3100/regime>, click the **GEX** tab.

### 3. What you should see on the GEX tab

Scroll past the live tiles and the GEX profile. The order is now:

```
… (existing live metrics + profile chart) …
┌──────────────────────────────────────────────────┐
│ SPX — INTRADAY GEX, LAST 5 SESSIONS (RTH)        │ ← NEW (card + legend top-right)
│ Legend: SPOT, GEX FLIP, NET GEX, IV 30D          │
│ … chart … 06/04 09:30 12:00 16:00 06/05 09:30 …  │
└──────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────┐
│ SPX — 90-DAY GEX HISTORY                         │ ← UPGRADED (was bare SVG)
│ Legend: NET GEX, GEX FLIP, SPOT                  │
│ … chart … 02/02 03/05 04/08 05/08 06/10 …        │
└──────────────────────────────────────────────────┘
(existing history table)
```

The orange GEX FLIP line on the intraday chart will look sparse / blocky —
this is **real data**: the scanner has been writing `gex_flip = null` on many
recent ticks. Not a chart bug.

The white SPX line on the **daily** chart visibly flat-lines at the right
edge. That's the `vol_index_lake_sync` regression — see "Known issues".

## How to run the test suites

```bash
# Frontend — full suite (~7s)
cd /Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart/web
./node_modules/.bin/tsc --noEmit          # strict typecheck
./node_modules/.bin/vitest run             # 372 tests, 0 failures
./node_modules/.bin/vitest run tests/unit/gexIntradayChart.test.tsx  # the new ones
./node_modules/.bin/next build             # production build green

# Backend — integration test (requires psql installed locally; runs in CI)
cd /Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart
pytest tests/integration/test_gex_repository.py -v
```

## Evidence already captured in this branch's `docs/`

Gitignored, so they live only on disk:

- `docs/intraday-card.png` — element screenshot of the new chart
- `docs/daily-card.png` — element screenshot of the upgraded daily chart
- `docs/regime-gex-fullpage.png` — full `/regime` page

If you want to regenerate them, see "How to run locally" then re-screenshot.

## Known issues outside this branch's scope

### `vol_index_lake_sync` is broken (P0)

Symptom: SPX / VIX / VIX3M / VVIX / COR1M last `trade_date` in
`vol_index_daily` is **2026-06-08** (3 days stale as of 2026-06-11).
Cascade: CRI / VCG / Canary snapshots also stuck at 06-08; the SPX line on
this branch's daily HistoryChart flat-lines.

Root cause:
```
ModuleNotFoundError: No module named 'pyarrow.pandas_compat'
  at src/uw_scan/sources/lake.py:174  df = table.to_pandas()
```
`pyarrow >= 15` removed that internal. Two fixes:
1. `cd /Users/moremeds/projects/argon && uv pip install pandas` then restart
   the worker (`launchctl kickstart -k gui/$(id -u)/com.argon.worker.uw-0`).
2. Or change `_rows_from_table` to use `table.to_pylist()` and skip the
   pandas detour entirely.

After either fix, backfill:
```python
# Inside the worktree venv with .env exported:
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
from uw_scan.worker.jobs.credit_etf_lake_sync import run_credit_etf_lake_sync
# … then trigger the regime scanners' recover_recent_gaps for CRI/VCG/Canary.
```

Full audit lives at:
`~/.claude/projects/-Users-moremeds-projects-argon/memory/regime-data-staleness-2026-06.md`

### Worker SSL bundle missing (P1)

`logs/worker-uw-0.err.log` shows recurring
`FileNotFoundError: [Errno 2] No such file or directory` in
`ssl.create_default_context`. The `regime_gex_scan` path still succeeds; the
ad-hoc rescan poll fails. Likely a stale `SSL_CERT_FILE` env or a removed
certifi bundle. Not blocking this PR.

## Verification I already performed in the previous session

- `next build` ✓ green, `/regime` listed as static.
- `tsc --noEmit` ✓ clean.
- `vitest run` ✓ 372 / 372 pass (including 5 new tests).
- Live-DB end-to-end via `TestClient`: 5 sessions × ~78 RTH ticks, `as_of` =
  last `ts`, unknown ticker returns `sessions: []` not 500.
- Real browser load on Next dev port 3100 via Playwright: both chart cards
  mounted, correct path counts (4 intraday, 3 daily), full legend text.
- Element screenshots captured (above).
- The CTE/RTH-filter alignment bug found and fixed mid-stream (ET 06-11
  ETH-only date was squeezing 06-04 out of the top-N window before the fix).

## When you're done testing

```bash
# Stop dev servers
kill $(lsof -ti :3100 :8401) 2>/dev/null

# Merge after approval
gh pr merge 121 --squash --delete-branch
# or interactive: gh pr view 121 --web

# Clean up the worktree once merged
git worktree remove /Users/moremeds/projects/argon/.worktrees/regime-gex-intraday-chart
```
