# UW Watchlist UI Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit prototype with a Next.js + FastAPI two-tier application that renders a card-grid watchlist landing page and tabbed regime-style detail page, backed by an out-of-process scheduler and Postgres cache.

**Architecture:** Three processes — Next.js (web), FastAPI (read-only API + watchlist CRUD), APScheduler worker (RTH spot-refresh / hourly UW scan / daily OHLC pull). All persistence in `option_wizard.uw_scan`. The existing `src/uw_scan/` pipeline is preserved unchanged; new work is additive (`api/`, `worker/`, `sources/`, `cards/` submodules).

**Tech Stack:** Python 3.13 + uv + FastAPI + psycopg 3 + Pydantic + APScheduler 3.11.x. Next.js 16 (App Router) + React 19 + Tailwind 3.4 + IBM Plex Mono + Inter + lucide-react + openapi-typescript. Postgres 15+. Reference image data provider: massive.com REST API (`api.massive.com`).

**Source spec:** [`docs/superpowers/specs/2026-05-12-uw-watchlist-ui-rework-design.md`](../specs/2026-05-12-uw-watchlist-ui-rework-design.md)
**Research note:** [`docs/superpowers/research/2026-05-12-spec-pct-and-skew-dte-research.md`](../research/2026-05-12-spec-pct-and-skew-dte-research.md)

---

## File structure

### Files this plan creates

```
src/uw_scan/
  api/
    __init__.py
    server.py                     # FastAPI app + routers
    routers/
      __init__.py
      watchlist.py                # /api/watchlist + CRUD
      stock.py                    # /api/stock/{ticker}
      ohlc.py                     # /api/ohlc/{ticker}
      jobs.py                     # /api/jobs/{job_id} + POST /watchlist/{t}/rescan
      health.py                   # /api/health
    schemas.py                    # Pydantic response models (over the wire)
  worker/
    __init__.py
    scheduler.py                  # APScheduler entry; reads cron config from Settings
    jobs/
      __init__.py
      spot_refresh.py             # 5-min spot pull from massive.com
      full_scan.py                # hourly UW deep-scan over watchlist
      ohlc_pull.py                # daily OHLC pull from massive.com
      rescan_loop.py              # 1s polling of jobs table
  sources/
    __init__.py
    ohlc.py                       # OhlcProvider protocol + MassiveOhlcProvider impl
  cards/
    __init__.py
    derive.py                     # compute_watchlist_card_row pure function
    gex.py                        # find_flip_strike, max_gex_strike, expiring_pct
    returns.py                    # ret_1d / ret_1w / ret_30d
    pcr.py                        # pcr_delta_30d
  storage/migrations/
    003_watchlist_tables.sql
    004_strike_gex_curve.sql
    005_jobs_table.sql
    006_seed_watchlist.sql
    007_aggregates_column.sql      # added in S2.5
data/
  watchlist_seed.json             # 54-ticker seed (provided in spec)
scripts/
  dev.sh                          # concurrently runs Next + uvicorn + scheduler
  migrate.sh                      # apply pending migrations idempotently
web/
  package.json
  tsconfig.json
  next.config.mjs
  tailwind.config.ts
  postcss.config.js
  app/
    layout.tsx
    page.tsx
    globals.css                   # copied verbatim from xenon
    watchlist/
      page.tsx
      loading.tsx
    stock/
      [ticker]/
        layout.tsx
        page.tsx
        [tab]/page.tsx
    admin/page.tsx
  components/
    watchlist/
      CardGrid.tsx
      TickerCard.tsx
      CardHeader.tsx
      SetupBadge.tsx
      SparklineRow.tsx
      AggressionGauge.tsx
      GammaBlock.tsx
      SkewBlock.tsx
      PositioningBlock.tsx
      FilterBar.tsx
      AddTickerDialog.tsx
    stock/
      DetailHeader.tsx
      TabBar.tsx
      tabs/
        MarketStructureTab.tsx
        VolatilityTab.tsx
        FlowTab.tsx
        VrpTab.tsx
        TradePlanTab.tsx
        TablesTab.tsx
      panels/
        MetricGrid.tsx
        MetricRow.tsx
        DataTable.tsx
        GexChart.tsx
    shared/
      InfoTooltip.tsx
      LiveBadge.tsx
      NumericValue.tsx
      RescanButton.tsx
  lib/
    api.ts
    formatters.ts
    freshness.ts
    types.ts                      # generated from FastAPI OpenAPI

tests/
  unit/cards/
    test_derive.py
    test_gex.py
    test_returns.py
    test_pcr.py
  unit/sources/
    test_ohlc.py
  integration/api/
    test_watchlist_endpoint.py
    test_stock_endpoint.py
    test_jobs_endpoint.py
    test_crud_endpoint.py
  integration/worker/
    test_spot_refresh.py
    test_full_scan.py
    test_ohlc_pull.py
    test_rescan_loop.py
  integration/storage/
    test_migrations.py
  fixtures/
    massive/
      daily_ohlc_AAPL.json
      quote_AAPL.json
web/tests/
  unit/formatters.test.ts
  unit/freshness.test.ts
  unit/setupBadge.test.tsx
  unit/sparkline.test.tsx
  integration/cardGrid.test.tsx
  integration/rescanButton.test.tsx
  e2e/golden-path.spec.ts         # Playwright
```

### Files this plan deletes (in S0)

```
app/                              # entire Streamlit directory
s1-card-full.png
s1-trade-plan-tab.png
s2-full-scan.png
```

### Files this plan moves (in S0)

```
docs/superpowers/specs/2026-05-11-uw-scan-design.md
  → docs/superpowers/archive/specs/2026-05-11-uw-scan-design.md
docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md
  → docs/superpowers/archive/plans/2026-05-11-uw-scan-rebuild-plan.md
docs/superpowers/plans/2026-05-12-uw-scan-s1.md
  → docs/superpowers/archive/plans/2026-05-12-uw-scan-s1.md
docs/superpowers/plans/2026-05-12-uw-scan-s2.md
  → docs/superpowers/archive/plans/2026-05-12-uw-scan-s2.md
```

### Files this plan modifies

| File | Change |
|---|---|
| `pyproject.toml` | Drop `streamlit`. Add `fastapi`, `uvicorn[standard]`, `apscheduler==3.11.*`, `httpx` (if not present), `pytest-asyncio`, `tzdata`. |
| `src/uw_scan/config.py` | Add `spot_refresh_seconds`, `full_scan_cron`, `ohlc_pull_cron`, `rth_tz`, `massive_api_key`, `massive_base_url`, plus `from_env()` updates. |
| `src/uw_scan/models.py` | Add `MarketAggregates` sub-model and `aggregates: MarketAggregates \| None` on `SingleStockReport`. Add `strike_gex_curve: list[StrikeGexBucket]` on `SingleStockReport`. |
| `src/uw_scan/pipeline.py` | (S2) After main scan, fetch bulk-screener row for ticker and write `MarketAggregates` + `strike_gex_curve` + append to `pcr_history`. |
| `src/uw_scan/storage/repository.py` | (S1, S2) New CRUD methods for `watchlist`, `watchlist_card`, `daily_ohlc`, `intraday_quote`, `pcr_history`, `jobs`. |
| `.env.example` | Add `MASSIVE_API_KEY`, `UW_SCAN_SPOT_REFRESH_SECONDS`, `UW_SCAN_FULL_SCAN_CRON`, `UW_SCAN_OHLC_PULL_CRON`, `UW_SCAN_RTH_TZ`. |
| `README.md` | Replace Streamlit section with `scripts/dev.sh` instructions. |

---

## Slice dependency graph

```
S0 ─┬─→ S1 ─→ S2 ─┐
    │             ├─→ S4 ─→ S5 ─→ S6 ─┐
    └─→ S3 ──────┘                    │
                                       ├─→ S12
              S5 ─→ S7 ─→ S8 ─→ S9 ───┤
                          │             │
                          └─→ S10 ─→ S11┘
```

Slices S0–S6 are backend-only; the project is shippable as an API-only deliverable at end of S6. S7–S12 build the frontend in parallel-friendly batches (S8/S9 and S10/S11 are independent).

---

## Slice S0 — Repo cleanup + new package skeleton

**Goal:** Delete Streamlit, archive old specs, scaffold the new sub-packages, scaffold an empty Next.js app, and set up `scripts/dev.sh`. After this slice, `git status` shows a clean repo with the new structure in place. No new behavior yet.

### Task S0.1 — Archive the previous specs and plans

**Files:**
- Move: `docs/superpowers/specs/2026-05-11-uw-scan-design.md` → `docs/superpowers/archive/specs/2026-05-11-uw-scan-design.md`
- Move: `docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md` → `docs/superpowers/archive/plans/2026-05-11-uw-scan-rebuild-plan.md`
- Move: `docs/superpowers/plans/2026-05-12-uw-scan-s1.md` → `docs/superpowers/archive/plans/2026-05-12-uw-scan-s1.md`
- Move: `docs/superpowers/plans/2026-05-12-uw-scan-s2.md` → `docs/superpowers/archive/plans/2026-05-12-uw-scan-s2.md`

- [ ] **Step 1: Create archive directories**

```bash
mkdir -p docs/superpowers/archive/specs docs/superpowers/archive/plans
```

- [ ] **Step 2: Move the four files with `git mv` to preserve history**

```bash
git mv docs/superpowers/specs/2026-05-11-uw-scan-design.md \
       docs/superpowers/archive/specs/2026-05-11-uw-scan-design.md
git mv docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md \
       docs/superpowers/archive/plans/2026-05-11-uw-scan-rebuild-plan.md
git mv docs/superpowers/plans/2026-05-12-uw-scan-s1.md \
       docs/superpowers/archive/plans/2026-05-12-uw-scan-s1.md
git mv docs/superpowers/plans/2026-05-12-uw-scan-s2.md \
       docs/superpowers/archive/plans/2026-05-12-uw-scan-s2.md
```

- [ ] **Step 3: Add a stub README inside the archive directory**

```bash
cat > docs/superpowers/archive/README.md <<'EOF'
# Archive

Historical specs and plans for prior iterations of the UW scanner.
The contracts in these documents (S1/S2 report shapes, Type C/F classification,
GEX/IV/VRP semantics, defined-risk trade plan rules) are still honored at the
model layer (`src/uw_scan/models.py`), even though the Streamlit UI they
described has been replaced.

The active spec is in
`docs/superpowers/specs/2026-05-12-uw-watchlist-ui-rework-design.md`.
EOF
```

- [ ] **Step 4: Verify with `git status`**

Run: `git status`
Expected: 4 renames, 1 untracked file (`docs/superpowers/archive/README.md`)

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/archive/README.md
git commit -m "docs: archive Streamlit-era specs and plans"
```

### Task S0.2 — Delete the Streamlit app and stale screenshots

**Files:**
- Delete: `app/streamlit_app.py`
- Delete: `app/views/__init__.py`, `app/views/scan_view.py`, `app/views/single_stock_view.py`
- Delete: `s1-card-full.png`, `s1-trade-plan-tab.png`, `s2-full-scan.png`

- [ ] **Step 1: Verify nothing else in the repo imports from `app/`**

Run: `grep -rn "from app\|import app\b" src/ tests/ scripts/ 2>/dev/null || echo "no imports of app/"`
Expected: `no imports of app/`

- [ ] **Step 2: Remove the Streamlit code and screenshots**

```bash
git rm -r app/
git rm s1-card-full.png s1-trade-plan-tab.png s2-full-scan.png
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove Streamlit prototype and stale screenshots"
```

### Task S0.3 — Remove the `streamlit` dependency from pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read the current `pyproject.toml`**

Run: `cat pyproject.toml`
Note the current `[project] dependencies` array. The exact streamlit version pin will appear there.

- [ ] **Step 2: Remove the `streamlit` line (and any streamlit-only dep, e.g. `altair` if only present for streamlit)**

Use the `Edit` tool to remove the line that contains `"streamlit"` (and any directly Streamlit-only transitive dep). Leave all other lines untouched.

- [ ] **Step 3: Run `uv sync` to recompute the lockfile**

Run: `uv sync --extra postgres`
Expected: completes cleanly; `uv.lock` updates; `streamlit` and its dep tree disappear from the lockfile.

- [ ] **Step 4: Confirm streamlit is gone**

Run: `uv run python -c "import streamlit"`
Expected: `ModuleNotFoundError: No module named 'streamlit'`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: drop streamlit dependency"
```

### Task S0.4 — Add the new Python dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new dependencies under `[project] dependencies`**

Use Edit to append (preserve existing entries — append, do not replace) these lines inside the dependencies array:

```toml
    "fastapi>=0.117,<1.0",
    "uvicorn[standard]>=0.32,<1.0",
    "APScheduler>=3.11,<4.0",
    "httpx>=0.27,<1.0",
    "tzdata>=2024.2",
```

(If `httpx` is already present, do not duplicate. If pinned at a lower bound, leave it.)

- [ ] **Step 2: Add the test deps under `[project.optional-dependencies] test` (or `dev`, matching the existing pattern)**

Append:

```toml
    "pytest-asyncio>=0.24,<1.0",
    "httpx>=0.27,<1.0",     # also as test dep for FastAPI TestClient
```

- [ ] **Step 3: Run `uv sync`**

Run: `uv sync --extra postgres`
Expected: completes; new packages resolved.

- [ ] **Step 4: Verify imports**

Run: `uv run python -c "import fastapi, uvicorn, apscheduler, httpx; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add fastapi, apscheduler, httpx, tzdata"
```

### Task S0.5 — Create the new Python sub-packages

**Files:**
- Create: `src/uw_scan/api/__init__.py` (empty)
- Create: `src/uw_scan/api/routers/__init__.py` (empty)
- Create: `src/uw_scan/worker/__init__.py` (empty)
- Create: `src/uw_scan/worker/jobs/__init__.py` (empty)
- Create: `src/uw_scan/sources/__init__.py` (empty — sources/ module already exists if `uw_sources.py` is there; verify before adding)
- Create: `src/uw_scan/cards/__init__.py` (empty)

- [ ] **Step 1: Check whether `src/uw_scan/sources/` already exists as a package**

Run: `ls src/uw_scan/sources/ 2>/dev/null || echo "not present"`

If `not present`, create it; otherwise leave its existing `__init__.py` alone.

- [ ] **Step 2: Create the new sub-package directories with empty `__init__.py` files**

```bash
mkdir -p src/uw_scan/api/routers \
         src/uw_scan/worker/jobs \
         src/uw_scan/cards
touch src/uw_scan/api/__init__.py \
      src/uw_scan/api/routers/__init__.py \
      src/uw_scan/worker/__init__.py \
      src/uw_scan/worker/jobs/__init__.py \
      src/uw_scan/cards/__init__.py
# Only create sources/__init__.py if Step 1 said "not present":
[ ! -d src/uw_scan/sources ] && mkdir src/uw_scan/sources && touch src/uw_scan/sources/__init__.py
```

- [ ] **Step 3: Verify the package layout**

Run: `find src/uw_scan -maxdepth 3 -name "__init__.py" -type f | sort`
Expected: includes the new files above plus existing `__init__.py`s.

- [ ] **Step 4: Verify Python can import each new sub-package**

Run: `uv run python -c "from uw_scan import api, worker, cards; from uw_scan.api import routers; from uw_scan.worker import jobs; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api src/uw_scan/worker src/uw_scan/cards
[ -d src/uw_scan/sources ] && git add src/uw_scan/sources
git commit -m "chore: scaffold api/, worker/, cards/, sources/ sub-packages"
```

### Task S0.6 — Scaffold the Next.js project under `web/`

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.mjs`
- Create: `web/postcss.config.js`
- Create: `web/tailwind.config.ts`
- Create: `web/app/layout.tsx`, `web/app/page.tsx`, `web/app/globals.css`
- Create: `web/.gitignore`

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "uw-watchlist-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "next dev --port 3001",
    "build": "next build",
    "start": "next start --port 3001",
    "typecheck": "tsc --noEmit",
    "lint": "next lint",
    "gen:types": "openapi-typescript http://127.0.0.1:8400/openapi.json -o lib/types.ts",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@fontsource/ibm-plex-mono": "^5.2.7",
    "@fontsource/inter": "^5.2.7",
    "lucide-react": "^0.544.0",
    "next": "^16.1.6",
    "react": "^19.2.4",
    "react-dom": "^19.2.4"
  },
  "devDependencies": {
    "@playwright/test": "^1.58.2",
    "@testing-library/dom": "^10.4.1",
    "@testing-library/react": "^16.3.2",
    "@types/node": "^22.10.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.21.0",
    "eslint-config-next": "^16.1.6",
    "openapi-typescript": "^7.5.0",
    "postcss": "^8.4.47",
    "prettier": "^3.8.1",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.6.3",
    "vitest": "^4.0.18"
  }
}
```

(Port 3001 deliberately — leaves xenon's :3000 available on the same machine.)

- [ ] **Step 2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create `web/next.config.mjs`**

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Cache Components opted-out; we use 'no-store' fetches.
  },
};
export default nextConfig;
```

- [ ] **Step 4: Create `web/postcss.config.js`**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 5: Create `web/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: ["class", "[data-theme='dark']"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
  plugins: [],
};
export default config;
```

- [ ] **Step 6: Create `web/app/globals.css` by copying from xenon**

```bash
cp ~/projects/xenon/web/app/globals.css web/app/globals.css
```

(If xenon isn't installed on the executing machine, copy the `:root` + `[data-theme="dark"]` blocks from the spec §6.4 verbatim. The full file at xenon includes 100+ KB of component-specific CSS we don't need yet — we'll let it stay until S9, where we either trim or keep depending on visible bloat.)

- [ ] **Step 7: Create `web/app/layout.tsx`**

```tsx
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/700.css";
import "./globals.css";

export const metadata = {
  title: "UW Watchlist",
  description: "Per-ticker options analytics, watchlist-driven",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <body style={{ fontFamily: "var(--font-sans)" }}>{children}</body>
    </html>
  );
}
```

- [ ] **Step 8: Create `web/app/page.tsx` (redirect to /watchlist)**

```tsx
import { redirect } from "next/navigation";
export default function Home() {
  redirect("/watchlist");
}
```

- [ ] **Step 9: Create `web/.gitignore`**

```
node_modules/
.next/
.env*.local
*.log
.DS_Store
playwright-report/
test-results/
```

- [ ] **Step 10: Install deps and verify a clean build**

```bash
cd web
npm install
npm run build
```

Expected: `npm run build` completes (will warn about missing `/watchlist` route — that's fine for now; Next.js doesn't fail the build on it, but if it does, add a stub `web/app/watchlist/page.tsx` containing `export default function Watchlist() { return <div>placeholder</div>; }`).

- [ ] **Step 11: Commit**

```bash
cd ..
git add web/
git commit -m "feat(web): scaffold Next.js 16 app with Tailwind + Inter/Plex Mono"
```

### Task S0.7 — Add `scripts/dev.sh` (concurrent process runner)

**Files:**
- Create: `scripts/dev.sh`

- [ ] **Step 1: Write the dev script**

```bash
#!/usr/bin/env bash
# scripts/dev.sh — run Next.js, FastAPI, and the worker scheduler concurrently.
# Uses npx concurrently from the web/ package so we don't add a top-level node dep.
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure web/ deps are installed (cheap if already cached).
if [ ! -d web/node_modules ]; then
  ( cd web && npm install )
fi

# Color-prefixed concurrent run. Press Ctrl-C to stop all three.
exec npx --prefix web concurrently \
  -n next,api,worker \
  -c cyan,green,yellow \
  "cd web && npm run dev" \
  "uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src" \
  "uv run python -m uw_scan.worker.scheduler"
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x scripts/dev.sh
```

- [ ] **Step 3: Verify the script's syntax (without running it — `server:app` doesn't exist yet)**

Run: `bash -n scripts/dev.sh && echo ok`
Expected: `ok`

- [ ] **Step 4: Add `concurrently` to `web/package.json` devDependencies**

Run: `cd web && npm install --save-dev concurrently@^9.2.1 && cd ..`

- [ ] **Step 5: Commit**

```bash
git add scripts/dev.sh web/package.json web/package-lock.json
git commit -m "feat: scripts/dev.sh runs next + uvicorn + scheduler concurrently"
```

### Task S0.8 — Update README.md to drop Streamlit instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

Run: `cat README.md`

- [ ] **Step 2: Replace the "Local Setup" section with the new dev flow**

Edit `README.md` to replace the existing setup block with:

```markdown
## Local Setup

```bash
uv sync --extra postgres
cp .env.example .env
# Fill in UW_SCAN_API_KEY and MASSIVE_API_KEY.

# Apply migrations against the local Postgres `option_wizard.uw_scan` schema:
bash scripts/migrate.sh

# Boot all three processes:
bash scripts/dev.sh
```

Next.js dev server: <http://127.0.0.1:3001>
FastAPI dev server: <http://127.0.0.1:8400>
FastAPI OpenAPI:    <http://127.0.0.1:8400/openapi.json>
```

(Leave the rest of the README — Database section, link to spec — unchanged.)

- [ ] **Step 3: Update the spec link to point at the new spec**

Edit the README's "Spec:" line to point at `docs/superpowers/specs/2026-05-12-uw-watchlist-ui-rework-design.md`. Update "Plan:" line to point at this file (`docs/superpowers/plans/2026-05-12-uw-watchlist-ui-rework-plan.md`).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README points at new dev flow + active spec"
```

### Task S0.9 — Verify the end-state of S0

- [ ] **Step 1: Verify the new tree**

Run: `tree -L 3 src/uw_scan web docs/superpowers 2>/dev/null | head -80`
Expected (substring match): sees `api/`, `worker/`, `cards/`, `sources/` under `src/uw_scan/`; sees `web/app/`; sees `archive/` under `docs/superpowers/`.

- [ ] **Step 2: Verify Streamlit is gone**

Run: `find . -path ./node_modules -prune -o -name "streamlit_app.py" -print 2>/dev/null`
Expected: no output.

- [ ] **Step 3: Verify `git status` is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

S0 is now complete. The repo has the new shape; nothing functional has changed yet.

---

## Slice S1 — DB migrations + watchlist seed

**Goal:** Add the 5 new tables (`watchlist`, `watchlist_card`, `daily_ohlc`, `intraday_quote`, `pcr_history`, `jobs`) and the `scan_runs.strike_gex_curve` JSONB column. Seed `watchlist` from the 54-ticker JSON. Integration test verifies the migration roundtrip against a real local Postgres.

### Task S1.1 — Inspect the existing migration runner

**Files:**
- Read: `src/uw_scan/storage/repository.py` (around lines that mention migrations or schema setup)
- Read: `src/uw_scan/storage/migrations/001_s1_core_tables.sql`
- Read: `src/uw_scan/storage/migrations/002_s2_scan_tables.sql`

- [ ] **Step 1: Find the migration runner**

Run: `grep -rn "migrations\|.sql\|run_migration\|apply_migration" src/uw_scan/storage/`
Expected: locates either a `Repository.run_migrations()` method or a standalone script that reads `*.sql` from the migrations dir in lexical order.

- [ ] **Step 2: Read the runner's contract**

Open the file from Step 1. Determine:
- Where it tracks which migrations have been applied (a `schema_migrations` table? a filename-based check?).
- Whether it runs each file inside a single transaction.
- Whether it tolerates re-running an already-applied migration.

- [ ] **Step 3: Record findings as a brief comment**

Write a 5-line note inside `src/uw_scan/storage/migrations/README.md` (create if missing) summarizing how migrations are applied, so any future contributor (or agent) doesn't have to re-discover.

### Task S1.2 — Write migration `003_watchlist_tables.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/003_watchlist_tables.sql`

- [ ] **Step 1: Write the SQL file**

```sql
-- 003_watchlist_tables.sql — canonical watchlist + denormalized card row + OHLC + intraday quote + PCR history.
SET search_path TO uw_scan;

-- 1. Canonical watchlist
CREATE TABLE IF NOT EXISTS watchlist (
  ticker        TEXT PRIMARY KEY,
  sector        TEXT NOT NULL,
  notes         TEXT,
  pinned        BOOLEAN NOT NULL DEFAULT FALSE,
  sort_rank     INTEGER NOT NULL DEFAULT 0,
  added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  removed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_watchlist_active
  ON watchlist (sector, sort_rank)
  WHERE removed_at IS NULL;

-- 2. Latest denormalized card row per ticker
CREATE TABLE IF NOT EXISTS watchlist_card (
  ticker            TEXT PRIMARY KEY REFERENCES watchlist(ticker),
  run_id            BIGINT NOT NULL REFERENCES scan_runs(run_id) ON DELETE RESTRICT,
  scanned_at        TIMESTAMPTZ NOT NULL,
  spot              NUMERIC(18,4),
  spot_quoted_at    TIMESTAMPTZ,
  spot_source       TEXT,

  iv_atm            NUMERIC(8,4),
  iv_rank           NUMERIC(6,2),

  setup_type        TEXT,
  setup_direction   TEXT,
  setup_score       NUMERIC(8,4),

  aggression_pct    NUMERIC(6,4),

  ret_1d            NUMERIC(8,4),
  ret_1w            NUMERIC(8,4),
  ret_30d           NUMERIC(8,4),

  gex_flip_distance NUMERIC(8,4),
  gex_flip_price    NUMERIC(18,4),
  gex_per_1pct_move NUMERIC(18,2),
  max_gex_strike    NUMERIC(18,4),
  gex_expiring_pct  NUMERIC(8,4),
  gex_expiring_date DATE,

  skew_25d_30dte    NUMERIC(8,4),

  call_oi_total     BIGINT,
  put_oi_total      BIGINT,
  pcr_oi            NUMERIC(8,4),
  pcr_vol           NUMERIC(8,4),
  pcr_delta_30d    NUMERIC(8,4),

  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Daily OHLC cache (massive.com is v1 provider)
CREATE TABLE IF NOT EXISTS daily_ohlc (
  ticker     TEXT NOT NULL,
  date       DATE NOT NULL,
  open       NUMERIC(18,4),
  high       NUMERIC(18,4),
  low        NUMERIC(18,4),
  close      NUMERIC(18,4) NOT NULL,
  volume     BIGINT,
  source     TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_ohlc_recent
  ON daily_ohlc (ticker, date DESC);

-- 4. Rolling intraday quote (one row per ticker)
CREATE TABLE IF NOT EXISTS intraday_quote (
  ticker     TEXT PRIMARY KEY REFERENCES watchlist(ticker),
  price      NUMERIC(18,4) NOT NULL,
  quoted_at  TIMESTAMPTZ NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. PCR daily snapshot (for 30d delta)
CREATE TABLE IF NOT EXISTS pcr_history (
  ticker        TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  pcr_oi        NUMERIC(8,4),
  pcr_vol       NUMERIC(8,4),
  PRIMARY KEY (ticker, snapshot_date)
);
```

- [ ] **Step 2: Apply migration manually against a local Postgres for first-pass validation**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -f src/uw_scan/storage/migrations/003_watchlist_tables.sql
```

Expected: `CREATE TABLE` / `CREATE INDEX` lines, no errors.

- [ ] **Step 3: Verify the tables exist**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "\dt uw_scan.*" | grep -E "watchlist|watchlist_card|daily_ohlc|intraday_quote|pcr_history"
```

Expected: all 5 names appear.

- [ ] **Step 4: Drop the tables (we'll re-apply through the migration runner in the integration test)**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "DROP TABLE IF EXISTS uw_scan.pcr_history, uw_scan.intraday_quote, uw_scan.daily_ohlc, uw_scan.watchlist_card, uw_scan.watchlist CASCADE;"
```

- [ ] **Step 5: Commit (don't apply via the runner yet — that's step S1.5)**

```bash
git add src/uw_scan/storage/migrations/003_watchlist_tables.sql
git commit -m "feat(db): migration 003 — watchlist + card + ohlc + intraday + pcr tables"
```

### Task S1.3 — Write migration `004_strike_gex_curve.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/004_strike_gex_curve.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 004_strike_gex_curve.sql — persist per-strike, per-expiry GEX as JSONB on each scan run.
SET search_path TO uw_scan;

ALTER TABLE scan_runs
  ADD COLUMN IF NOT EXISTS strike_gex_curve JSONB;
COMMENT ON COLUMN scan_runs.strike_gex_curve IS
  'Per-strike, per-expiry GEX curve. Array of {strike, expiry, net_gex, call_gex, put_gex}. Nullable; old rows pre-006 stay valid.';
```

- [ ] **Step 2: Apply manually and verify**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -f src/uw_scan/storage/migrations/004_strike_gex_curve.sql

psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "\d+ uw_scan.scan_runs" | grep strike_gex_curve
```

Expected: column appears as `jsonb`.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/004_strike_gex_curve.sql
git commit -m "feat(db): migration 004 — scan_runs.strike_gex_curve JSONB"
```

### Task S1.4 — Write migration `005_jobs_table.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/005_jobs_table.sql`

- [ ] **Step 1: Write the SQL**

```sql
-- 005_jobs_table.sql — ad-hoc rescan jobs for the Rescan button.
SET search_path TO uw_scan;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker        TEXT NOT NULL REFERENCES watchlist(ticker),
  status        TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  run_id        BIGINT,
  error         TEXT,
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_queued
  ON jobs (status, requested_at)
  WHERE status IN ('queued','running');
```

- [ ] **Step 2: Apply manually and verify**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -f src/uw_scan/storage/migrations/005_jobs_table.sql

psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "\d uw_scan.jobs"
```

Expected: shows the new table with the CHECK constraint.

- [ ] **Step 3: Drop the table to keep the DB clean before the integration test**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "DROP TABLE IF EXISTS uw_scan.jobs;"
```

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/005_jobs_table.sql
git commit -m "feat(db): migration 005 — uw_scan.jobs table for ad-hoc rescans"
```

### Task S1.5 — Write migration `006_seed_watchlist.sql`

**Files:**
- Create: `data/watchlist_seed.json`
- Create: `src/uw_scan/storage/migrations/006_seed_watchlist.sql`

- [ ] **Step 1: Save the watchlist seed JSON**

Write `data/watchlist_seed.json` with the 54-ticker payload provided in the brainstorming session (copy the exact `{ "last_updated": ..., "tickers": [...] }` JSON from the conversation history).

- [ ] **Step 2: Write the seed migration that inserts each ticker**

The migration writes an `INSERT ... ON CONFLICT (ticker) DO NOTHING` for every ticker. Inline the rows in the SQL (the migration runs once, no need for the JSON file at runtime).

```sql
-- 006_seed_watchlist.sql — seed the canonical watchlist from data/watchlist_seed.json.
-- Idempotent: ON CONFLICT DO NOTHING so re-running is safe.
SET search_path TO uw_scan;

INSERT INTO watchlist (ticker, sector, notes, sort_rank) VALUES
  ('AAPL',  'Technology',              'M7', 1),
  ('MSFT',  'Technology',              'M7', 2),
  ('NVDA',  'Technology',              'M7', 3),
  ('AMZN',  'Consumer Discretionary',  'M7', 4),
  ('META',  'Communication Services',  'M7', 5),
  ('GOOGL', 'Communication Services',  'M7', 6),
  ('TSLA',  'Consumer Discretionary',  'M7', 7),
  ('AMD',   'Technology',              'Semiconductor', 10),
  ('AVGO',  'Technology',              'Semiconductor', 11),
  ('INTC',  'Technology',              'Semiconductor', 12),
  ('MU',    'Technology',              'Semiconductor — memory', 13),
  ('MRVL',  'Technology',              'Semiconductor — custom silicon', 14),
  ('TSM',   'Technology',              'Semiconductor — foundry', 15),
  ('QCOM',  'Technology',              'Semiconductor — mobile', 16),
  ('CRWV',  'Technology',              'Semiconductor — AI inference', 17),
  ('NBIS',  'Technology',              'Semiconductor — data center', 18),
  ('IREN',  'Technology',              'Semiconductor — data center / mining', 19),
  ('CRDO',  'Technology',              'Semiconductor — connectivity', 20),
  ('SNDK',  'Technology',              'Semiconductor — storage', 21),
  ('LITE',  'Technology',              'Semiconductor — photonics', 22),
  ('GLW',   'Technology',              'Semiconductor — optical fiber', 23),
  ('NOK',   'Technology',              'Semiconductor — telecom infra', 24),
  ('TSEM',  'Technology',              'Semiconductor — foundry', 25),
  ('PLTR',  'Technology',              'Growth / tech — data analytics', 30),
  ('HIMS',  'Healthcare',              'Growth / tech — telehealth', 31),
  ('HOOD',  'Financials',              'Growth / tech — fintech', 32),
  ('SOFI',  'Financials',              'Growth / tech — fintech', 33),
  ('ASTS',  'Communication Services',  'Growth / tech — satellite', 34),
  ('RKLB',  'Industrials',             'Growth / tech — space', 35),
  ('NET',   'Technology',              'Growth / tech — cloud infra', 36),
  ('PANW',  'Technology',              'Growth / tech — cybersecurity', 37),
  ('BKSY',  'Technology',              'Growth / tech — geospatial', 38),
  ('KO',    'Consumer Staples',        'Industrials / value', 40),
  ('MCD',   'Consumer Discretionary',  'Industrials / value', 41),
  ('LLY',   'Healthcare',              'Industrials / value — pharma', 42),
  ('JPM',   'Financials',              'Industrials / value — bank', 43),
  ('GS',    'Financials',              'Industrials / value — bank', 44),
  ('BA',    'Industrials',             'Industrials / value — aerospace', 45),
  ('COST',  'Consumer Staples',        'Industrials / value — retail', 46),
  ('WMT',   'Consumer Staples',        'Industrials / value — retail', 47),
  ('MS',    'Financials',              'Industrials / value — bank', 48),
  ('DAL',   'Industrials',             'Industrials / value — airline', 49),
  ('XOM',   'Energy',                  'Industrials / value — energy', 50),
  ('OXY',   'Energy',                  'Industrials / value — energy', 51),
  ('CVX',   'Energy',                  'Industrials / value — energy', 52),
  ('CRS',   'Industrials',             'Industrials / value — specialty alloys', 53),
  ('FLY',   'Industrials',             'Industrials / value — aircraft leasing', 54),
  ('PL',    'Technology',              'Industrials / value — satellite imaging', 55),
  ('COIN',  'Financials',              'Crypto proxy', 60),
  ('MSTR',  'Technology',              'Crypto proxy — BTC treasury', 61),
  ('CRCL',  'Financials',              'Crypto proxy — USDC issuer', 62),
  ('SPY',   'ETF',                     'Broad market ETF', 70),
  ('QQQ',   'ETF',                     'Nasdaq 100 ETF', 71),
  ('IWM',   'ETF',                     'Russell 2000 ETF', 72)
ON CONFLICT (ticker) DO NOTHING;
```

- [ ] **Step 3: Verify count matches the seed JSON**

After applying once locally:

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "SELECT COUNT(*) FROM uw_scan.watchlist;"
```

Expected: `count: 54`

- [ ] **Step 4: Commit**

```bash
git add data/watchlist_seed.json src/uw_scan/storage/migrations/006_seed_watchlist.sql
git commit -m "feat(db): migration 006 — seed 54-ticker watchlist"
```

### Task S1.6 — Write `scripts/migrate.sh`

**Files:**
- Create: `scripts/migrate.sh`

- [ ] **Step 1: Write the script (uses the runner found in S1.1, or applies *.sql in order if there's no runner yet)**

```bash
#!/usr/bin/env bash
# scripts/migrate.sh — apply all SQL migrations under src/uw_scan/storage/migrations/
# in lexical order against the configured Postgres. Idempotent: every migration uses
# IF NOT EXISTS / ON CONFLICT, so re-running is a no-op.
set -euo pipefail

cd "$(dirname "$0")/.."

DSN=$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')

for f in src/uw_scan/storage/migrations/*.sql; do
  echo "Applying $f..."
  psql "$DSN" -v ON_ERROR_STOP=1 -f "$f"
done

echo "All migrations applied."
```

- [ ] **Step 2: Make executable and run it end-to-end against a fresh local DB**

```bash
chmod +x scripts/migrate.sh
# Reset local schema first if you want a clean check:
# psql "$DSN" -c "DROP SCHEMA IF EXISTS uw_scan CASCADE; CREATE SCHEMA uw_scan;"
bash scripts/migrate.sh
```

Expected: all 6 migrations apply cleanly; `\dt uw_scan.*` lists every table; `SELECT COUNT(*) FROM uw_scan.watchlist;` returns 54.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate.sh
git commit -m "feat: scripts/migrate.sh applies SQL migrations in order"
```

### Task S1.7 — Write the migration integration test

**Files:**
- Create: `tests/integration/storage/__init__.py` (empty)
- Create: `tests/integration/storage/test_migrations.py`

- [ ] **Step 1: Write the failing test**

```python
"""Verify migrations 003-006 produce the expected schema and seed against an
ISOLATED test database — never against the developer's real `option_wizard` DB.

Requires `UW_SCAN_TEST_DB_NAME` env var to point at a dedicated test database
(e.g. `option_wizard_test`). The fixture refuses to run if it isn't set, so
running `pytest` cannot destroy local scan data by accident."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    """Return a Settings instance pointing at the isolated test DB.

    HARD REQUIREMENT: the developer must set UW_SCAN_TEST_DB_NAME to a database
    name that is NOT their working `option_wizard` DB. The fixture refuses to
    run otherwise — protects against `DROP SCHEMA` against the wrong target.
    """
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set. Create a dedicated test DB "
            "(e.g. `createdb option_wizard_test`) and export "
            "`UW_SCAN_TEST_DB_NAME=option_wizard_test` before running pytest. "
            "This fixture refuses to operate on the working DB because it "
            "performs `DROP SCHEMA uw_scan CASCADE`.",
            pytrace=False,
        )
    base = Settings.from_env()
    # Build a fresh Settings instance that overrides only the DB name.
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def fresh_schema():
    """DROP + CREATE uw_scan schema on the TEST database, then re-apply all
    migrations. Yields a connection."""
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    # Pass the test DB through to the migration runner via env override.
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        yield conn


def test_all_new_tables_exist(fresh_schema):
    expected = {
        "watchlist", "watchlist_card", "daily_ohlc",
        "intraday_quote", "pcr_history", "jobs",
    }
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='uw_scan'"
        )
        actual = {row[0] for row in cur.fetchall()}
    assert expected <= actual, f"missing: {expected - actual}"


def test_strike_gex_curve_column_added(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema='uw_scan'
              AND table_name='scan_runs'
              AND column_name='strike_gex_curve'
        """)
        row = cur.fetchone()
    assert row is not None, "strike_gex_curve column missing"
    assert row[0] == "jsonb"


def test_watchlist_seeded(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM uw_scan.watchlist WHERE removed_at IS NULL")
        count = cur.fetchone()[0]
    assert count == 54


def test_watchlist_card_fk_to_scan_runs(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT confrelid::regclass::text
            FROM pg_constraint
            WHERE conrelid = 'uw_scan.watchlist_card'::regclass
              AND contype = 'f'
              AND 'run_id' = ANY(
                SELECT attname FROM pg_attribute
                WHERE attrelid = 'uw_scan.watchlist_card'::regclass
                  AND attnum = ANY(conkey)
              )
        """)
        targets = [row[0] for row in cur.fetchall()]
    assert "uw_scan.scan_runs" in targets, \
        f"watchlist_card.run_id FK missing or wrong target: {targets}"


def test_jobs_status_check_constraint(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            INSERT INTO uw_scan.watchlist(ticker, sector) VALUES ('TEST', 'ETF')
            ON CONFLICT (ticker) DO NOTHING
        """)
        fresh_schema.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO uw_scan.jobs(ticker, status) VALUES (%s, %s)",
                ("TEST", "bogus_status"),
            )
            fresh_schema.commit()
```

- [ ] **Step 2: Run the test to verify it fails before migrations run cleanly (sanity check)**

Run: `uv run pytest tests/integration/storage/test_migrations.py -v`
Expected: PASS (migrations from S1.2–S1.5 should be applied and the schema correct).

If FAIL, fix the migration that doesn't match the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/storage/__init__.py tests/integration/storage/test_migrations.py
git commit -m "test(db): integration test verifies migration 003-006 schema + seed"
```

### Task S1.8 — Add repository methods for the new tables

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Create: `tests/integration/storage/test_repository_watchlist.py`

- [ ] **Step 1: Write the failing repository tests**

```python
"""Integration tests for the new Repository methods on watchlist + watchlist_card + ohlc + intraday + pcr_history + jobs."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo():
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        r = Repository(conn, schema=settings.db_schema)
        yield r
        conn.rollback()  # tests run inside a transaction we can rollback


def test_list_active_watchlist_excludes_soft_deleted(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    repo.soft_delete_watchlist_ticker("ZZTEST")
    actives = [t.ticker for t in repo.list_active_watchlist()]
    assert "ZZTEST" not in actives


def test_upsert_watchlist_card_idempotent(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    repo.upsert_watchlist_card(
        ticker="ZZTEST",
        run_id=1,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("100.00"),
        iv_atm=Decimal("0.25"),
        # ...minimal field set; nulls accepted for everything else
    )
    repo.upsert_watchlist_card(
        ticker="ZZTEST",
        run_id=2,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("101.00"),
        iv_atm=Decimal("0.27"),
    )
    card = repo.get_watchlist_card("ZZTEST")
    assert card.run_id == 2
    assert card.spot == Decimal("101.00")


def test_upsert_daily_ohlc_dedupe_by_date(repo):
    repo.upsert_daily_ohlc(
        ticker="ZZTEST", date=date(2026, 5, 1),
        open=Decimal("100"), high=Decimal("102"), low=Decimal("99"),
        close=Decimal("101"), volume=10_000, source="massive.com",
    )
    repo.upsert_daily_ohlc(
        ticker="ZZTEST", date=date(2026, 5, 1),
        open=Decimal("100"), high=Decimal("103"), low=Decimal("99"),
        close=Decimal("102"), volume=15_000, source="massive.com",
    )
    rows = repo.list_daily_ohlc("ZZTEST", limit=10)
    same_date = [r for r in rows if r.date == date(2026, 5, 1)]
    assert len(same_date) == 1
    assert same_date[0].close == Decimal("102")  # second upsert wins


def test_enqueue_and_claim_job(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    job_id = repo.enqueue_rescan_job("ZZTEST")
    claimed = repo.claim_next_queued_job()
    assert claimed.id == job_id
    assert claimed.status == "running"
    # Re-claim returns None
    assert repo.claim_next_queued_job() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/storage/test_repository_watchlist.py -v`
Expected: FAIL with `AttributeError: 'Repository' has no attribute 'list_active_watchlist'` (or similar).

- [ ] **Step 3: Implement the repository methods**

Open `src/uw_scan/storage/repository.py` and add the following methods (preserve existing code; append at the end of the `Repository` class):

```python
    # ---- watchlist CRUD ----
    def list_active_watchlist(self) -> list["WatchlistRow"]:
        with self.conn.cursor() as cur:
            cur.execute(f"""
                SELECT ticker, sector, notes, pinned, sort_rank, added_at, removed_at
                FROM {self.schema}.watchlist
                WHERE removed_at IS NULL
                ORDER BY sort_rank, ticker
            """)
            return [WatchlistRow(*row) for row in cur.fetchall()]

    def add_watchlist_ticker(
        self, *, ticker: str, sector: str, notes: str | None = None,
        sort_rank: int = 0, pinned: bool = False,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.watchlist
                  (ticker, sector, notes, sort_rank, pinned)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET sector=EXCLUDED.sector, notes=EXCLUDED.notes,
                      sort_rank=EXCLUDED.sort_rank, pinned=EXCLUDED.pinned,
                      removed_at=NULL
            """, (ticker, sector, notes, sort_rank, pinned))
        self.conn.commit()

    def soft_delete_watchlist_ticker(self, ticker: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.watchlist SET removed_at=NOW() WHERE ticker=%s",
                (ticker,),
            )
        self.conn.commit()

    def patch_watchlist_ticker(
        self, ticker: str, *, sector: str | None = None, notes: str | None = None,
        pinned: bool | None = None, sort_rank: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list = []
        for col, val in (
            ("sector", sector), ("notes", notes),
            ("pinned", pinned), ("sort_rank", sort_rank),
        ):
            if val is not None:
                sets.append(f"{col}=%s")
                vals.append(val)
        if not sets:
            return
        vals.append(ticker)
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.watchlist SET {', '.join(sets)} WHERE ticker=%s",
                vals,
            )
        self.conn.commit()

    # ---- watchlist_card ----
    def upsert_watchlist_card(self, *, ticker: str, run_id: int,
                              scanned_at, spot=None, **fields) -> None:
        cols = ["ticker", "run_id", "scanned_at", "spot", *fields.keys()]
        vals = [ticker, run_id, scanned_at, spot, *fields.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "ticker")
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.watchlist_card ({', '.join(cols)}, updated_at)
                VALUES ({placeholders}, NOW())
                ON CONFLICT (ticker) DO UPDATE SET {updates}, updated_at=NOW()
                """,
                vals,
            )
        self.conn.commit()

    def get_watchlist_card(self, ticker: str) -> "WatchlistCardRow | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self.schema}.watchlist_card WHERE ticker=%s",
                (ticker,),
            )
            row = cur.fetchone()
        return WatchlistCardRow.from_db(row, cur.description) if row else None

    def list_watchlist_cards(self) -> list["WatchlistCardRow"]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT c.*, w.sector, w.pinned, w.sort_rank
                FROM {self.schema}.watchlist_card c
                JOIN {self.schema}.watchlist w ON w.ticker = c.ticker
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, c.ticker
                """
            )
            return [WatchlistCardRow.from_db(row, cur.description) for row in cur.fetchall()]

    # ---- daily_ohlc ----
    def upsert_daily_ohlc(self, *, ticker: str, date, open, high, low,
                          close, volume, source: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.daily_ohlc
                  (ticker, date, open, high, low, close, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, date) DO UPDATE
                  SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume,
                      source=EXCLUDED.source, fetched_at=NOW()
                """,
                (ticker, date, open, high, low, close, volume, source),
            )
        self.conn.commit()

    def list_daily_ohlc(self, ticker: str, *, limit: int = 30) -> list["DailyOhlcRow"]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, date, open, high, low, close, volume, source, fetched_at
                FROM {self.schema}.daily_ohlc
                WHERE ticker=%s
                ORDER BY date DESC
                LIMIT %s
                """,
                (ticker, limit),
            )
            return [DailyOhlcRow(*row) for row in cur.fetchall()]

    # ---- intraday_quote ----
    def upsert_intraday_quote(self, ticker: str, price, quoted_at) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.intraday_quote (ticker, price, quoted_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price, quoted_at=EXCLUDED.quoted_at, fetched_at=NOW()
                """,
                (ticker, price, quoted_at),
            )
        self.conn.commit()

    def get_intraday_quote(self, ticker: str) -> "IntradayQuoteRow | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker, price, quoted_at, fetched_at FROM {self.schema}.intraday_quote WHERE ticker=%s",
                (ticker,),
            )
            row = cur.fetchone()
        return IntradayQuoteRow(*row) if row else None

    # ---- pcr_history ----
    def append_pcr_history(self, ticker: str, snapshot_date, pcr_oi, pcr_vol) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.pcr_history (ticker, snapshot_date, pcr_oi, pcr_vol)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker, snapshot_date) DO UPDATE
                  SET pcr_oi=EXCLUDED.pcr_oi, pcr_vol=EXCLUDED.pcr_vol
                """,
                (ticker, snapshot_date, pcr_oi, pcr_vol),
            )
        self.conn.commit()

    def get_pcr_history_30d_ago(self, ticker: str, today) -> "PcrHistoryRow | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, snapshot_date, pcr_oi, pcr_vol
                FROM {self.schema}.pcr_history
                WHERE ticker=%s AND snapshot_date <= %s - INTERVAL '30 days'
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (ticker, today),
            )
            row = cur.fetchone()
        return PcrHistoryRow(*row) if row else None

    # ---- jobs ----
    def enqueue_rescan_job(self, ticker: str) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.schema}.jobs (ticker, status) VALUES (%s, 'queued') RETURNING id",
                (ticker,),
            )
            job_id = cur.fetchone()[0]
        self.conn.commit()
        return str(job_id)

    def claim_next_queued_job(self) -> "JobRow | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.schema}.jobs
                SET status='running', started_at=NOW()
                WHERE id = (
                  SELECT id FROM {self.schema}.jobs
                  WHERE status='queued'
                  ORDER BY requested_at
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error, requested_at, started_at, finished_at
                """
            )
            row = cur.fetchone()
        self.conn.commit()
        return JobRow(*row) if row else None

    def mark_job_done(self, job_id: str, run_id: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.jobs SET status='done', run_id=%s, finished_at=NOW() WHERE id=%s",
                (run_id, job_id),
            )
        self.conn.commit()

    def mark_job_failed(self, job_id: str, error: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.jobs SET status='failed', error=%s, finished_at=NOW() WHERE id=%s",
                (error[:2000], job_id),
            )
        self.conn.commit()

    def get_job(self, job_id: str) -> "JobRow | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, status, run_id, error, requested_at, started_at, finished_at
                FROM {self.schema}.jobs WHERE id=%s
                """,
                (job_id,),
            )
            row = cur.fetchone()
        return JobRow(*row) if row else None
```

At the top of `repository.py` add the simple row dataclasses (or use Pydantic if that's the file's existing convention; check before deciding):

```python
from dataclasses import dataclass
from datetime import date as _date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class WatchlistRow:
    ticker: str
    sector: str
    notes: str | None
    pinned: bool
    sort_rank: int
    added_at: datetime
    removed_at: datetime | None


@dataclass(frozen=True)
class DailyOhlcRow:
    ticker: str
    date: _date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class IntradayQuoteRow:
    ticker: str
    price: Decimal
    quoted_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class PcrHistoryRow:
    ticker: str
    snapshot_date: _date
    pcr_oi: Decimal | None
    pcr_vol: Decimal | None


@dataclass(frozen=True)
class JobRow:
    id: str
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WatchlistCardRow:
    """Variable-shaped: 25+ fields, many nullable. Wraps a dict for forward-compat
    when the card schema grows. Use .from_db(row, cursor.description) to construct."""
    def __init__(self, data: dict):
        self._data = data
    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        raise AttributeError(name)
    @classmethod
    def from_db(cls, row: tuple, description) -> "WatchlistCardRow":
        return cls({col.name: val for col, val in zip(description, row)})
    def to_dict(self) -> dict:
        return dict(self._data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/storage/test_repository_watchlist.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_repository_watchlist.py
git commit -m "feat(repo): CRUD methods for watchlist / card / ohlc / intraday / pcr / jobs"
```

### Task S1.9 — Verify S1 end-state

- [ ] **Step 1: Re-run all storage integration tests**

Run: `uv run pytest tests/integration/storage/ -v`
Expected: all tests pass.

- [ ] **Step 2: Verify the DB schema matches the spec**

Run: `psql "$DSN" -c "\dt uw_scan.*" | sort`
Expected: lists watchlist, watchlist_card, daily_ohlc, intraday_quote, pcr_history, jobs, plus all pre-existing tables.

S1 done. Persistence layer is ready.

---

## Slice S2 — Pipeline extensions

**Goal:** Extend `SingleStockReport` and the S1 pipeline (`pipeline.run_single_stock`) with: (1) the `strike_gex_curve` JSONB payload, (2) a new `MarketAggregates` sub-model carrying call/put OI/volume totals + PCR fields from the bulk-screener, (3) verification (and normalisation, if needed) of `volatility.skew_25d` to a 30-DTE 25Δ RR, (4) an end-of-scan `pcr_history` write. All changes are additive: old persisted rows remain readable.

### Task S2.1 — Add `MarketAggregates` to the model

**Files:**
- Modify: `src/uw_scan/models.py`
- Create: `tests/unit/test_models_aggregates.py`

- [ ] **Step 1: Write the failing model test**

```python
"""MarketAggregates and SingleStockReport.aggregates must round-trip through pydantic."""
from decimal import Decimal
from uw_scan.models import MarketAggregates, SingleStockReport

def test_market_aggregates_defaults_to_none():
    agg = MarketAggregates()
    assert agg.call_oi_total is None
    assert agg.put_oi_total is None
    assert agg.pcr_oi is None
    assert agg.pcr_vol is None

def test_market_aggregates_construct_from_screener_fields():
    agg = MarketAggregates(
        call_oi_total=1_000_000,
        put_oi_total=2_000_000,
        call_volume_total=500_000,
        put_volume_total=800_000,
        call_volume_ask_side=300_000,
        call_volume_bid_side=200_000,
        put_volume_ask_side=400_000,
        put_volume_bid_side=400_000,
        pcr_oi=Decimal("2.00"),
        pcr_vol=Decimal("1.60"),
        iv30d=Decimal("0.42"),
    )
    assert agg.pcr_oi == Decimal("2.00")
    assert agg.iv30d == Decimal("0.42")

def test_single_stock_report_aggregates_field_optional():
    """Existing test fixtures shouldn't break — aggregates is optional."""
    # Real construction is via Repository; here we just verify the model accepts None.
    assert "aggregates" in SingleStockReport.model_fields
    assert SingleStockReport.model_fields["aggregates"].default is None
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/unit/test_models_aggregates.py -v`
Expected: FAIL with `ImportError: cannot import name 'MarketAggregates'`.

- [ ] **Step 3: Add `MarketAggregates` to `src/uw_scan/models.py`**

Insert this class **before** `class SingleStockReport(_UwBase):`:

```python
class MarketAggregates(_UwBase):
    """Per-ticker aggregate fields sourced from the bulk-screener endpoint.

    Populated by pipeline.run_single_stock alongside the existing per-section
    sub-models. Used to feed the watchlist card POSITIONING and SKEW blocks.
    """
    call_oi_total: int | None = None
    put_oi_total: int | None = None
    call_volume_total: int | None = None
    put_volume_total: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side: int | None = None
    put_volume_bid_side: int | None = None
    pcr_oi: Decimal | None = None
    pcr_vol: Decimal | None = None
    iv30d: Decimal | None = None
```

Then on the `SingleStockReport` class, add the optional field:

```python
class SingleStockReport(_UwBase):
    # ... existing fields ...
    aggregates: MarketAggregates | None = None
    strike_gex_curve: list["StrikeGexBucket"] = []
    # ... etc ...
```

And define `StrikeGexBucket` alongside `MarketAggregates`:

```python
class StrikeGexBucket(_UwBase):
    """One row of the per-strike, per-expiry GEX curve persisted on each scan run."""
    strike: Decimal
    expiry: _date
    net_gex: Decimal | None = None
    call_gex: Decimal | None = None
    put_gex: Decimal | None = None
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/unit/test_models_aggregates.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Run the full unit suite to verify nothing else regressed**

Run: `uv run pytest tests/unit/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models.py tests/unit/test_models_aggregates.py
git commit -m "feat(models): add MarketAggregates and StrikeGexBucket; SingleStockReport gains optional aggregates + strike_gex_curve"
```

### Task S2.2 — Source per-ticker bulk-screener row

**Files:**
- Modify: `src/uw_scan/sources/uw_sources.py` (or wherever the existing UW source fetchers live — check S1.1's findings)
- Create: `tests/unit/test_uw_sources_bulk_screener_ticker.py`

- [ ] **Step 1: Find where the existing `fetch_*` source functions live**

Run: `grep -rn "fetch_max_pain\|fetch_skew\|fetch_term_structure" src/uw_scan/`
Expected: locates a module like `src/uw_scan/sources/uw_sources.py` or similar.

- [ ] **Step 2: Write the failing test**

```python
"""fetch_bulk_screener_ticker should normalize a single-row screener response to BulkScreenerRow."""
from decimal import Decimal
from unittest.mock import MagicMock

from uw_scan.models import BulkScreenerRow
from uw_scan.sources import uw_sources  # adjust import path to actual module


def test_fetch_bulk_screener_ticker_normalises_one_row():
    client = MagicMock()
    client.get.return_value = {
        "data": [{
            "ticker": "TSLA",
            "marketcap": "1500000000000",
            "close": "445.12",
            "prev_close": "446.00",
            "call_premium": "50000000",
            "put_premium": "30000000",
            "call_open_interest": "1200000",
            "put_open_interest": "2100000",
            "call_volume": "500000",
            "put_volume": "800000",
            "call_volume_ask_side": "300000",
            "call_volume_bid_side": "200000",
            "put_volume_ask_side": "400000",
            "put_volume_bid_side": "400000",
            "put_call_ratio": "1.75",
            "iv30d": "0.42",
            "iv_rank": "39.0",
            "gex_net_change": "-224890.0196",
            "variance_risk_premium": "-0.0212",
            "sector": "Consumer Discretionary",
        }]
    }
    repo = MagicMock()
    row = uw_sources.fetch_bulk_screener_ticker(client, repo, run_id=42, ticker="TSLA")
    assert isinstance(row, BulkScreenerRow)
    assert row.ticker == "TSLA"
    assert row.call_open_interest == 1_200_000
    assert row.put_call_ratio == Decimal("1.75")
    assert row.put_volume_ask_side == 400_000


def test_fetch_bulk_screener_ticker_returns_none_when_empty():
    client = MagicMock()
    client.get.return_value = {"data": []}
    repo = MagicMock()
    row = uw_sources.fetch_bulk_screener_ticker(client, repo, run_id=42, ticker="ZZZZ")
    assert row is None
```

- [ ] **Step 3: Run and verify failure**

Run: `uv run pytest tests/unit/test_uw_sources_bulk_screener_ticker.py -v`
Expected: FAIL — `fetch_bulk_screener_ticker` doesn't exist.

- [ ] **Step 4: Implement `fetch_bulk_screener_ticker`**

Add to `src/uw_scan/sources/uw_sources.py`:

```python
def fetch_bulk_screener_ticker(client, repo, run_id: int, ticker: str) -> BulkScreenerRow | None:
    """Fetch one row from /api/screener/stocks for the given ticker.

    The bulk screener endpoint accepts a `ticker` query param to scope to a single
    symbol; returns the same schema as the S2 universe scan but with one element.
    """
    resp = client.get("/api/screener/stocks", params={"ticker": ticker})
    rows = resp.get("data", []) or []
    if not rows:
        return None
    row = normalize.coerce_bulk_screener_row(rows[0])
    # Persist raw payload for audit (matches existing pattern of other fetchers).
    repo.insert_raw_screener_row(run_id, ticker, rows[0])
    return row
```

(Verify the `normalize.coerce_bulk_screener_row` helper exists; if not, add an entry to `normalize.py` that maps the raw dict into a `BulkScreenerRow`. Look at the existing `coerce_*` helpers for the pattern — they call `Decimal(str(v))` on numerics and tolerate missing keys.)

If `Repository.insert_raw_screener_row` doesn't exist, either:
- Add it (table `raw_screener_rows`, one new migration if not present), OR
- Use whichever raw-payload pattern already exists in `repository.py` (look for `insert_raw_*` methods).

- [ ] **Step 5: Run and verify pass**

Run: `uv run pytest tests/unit/test_uw_sources_bulk_screener_ticker.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/sources/uw_sources.py src/uw_scan/normalize.py \
        tests/unit/test_uw_sources_bulk_screener_ticker.py
git commit -m "feat(sources): fetch_bulk_screener_ticker — per-ticker screener row"
```

### Task S2.3 — Persist `strike_gex_curve` JSONB on each run

**Files:**
- Modify: `src/uw_scan/pipeline.py`
- Modify: `src/uw_scan/storage/repository.py`
- Modify: `src/uw_scan/reports/single_stock.py` (the assembler reads `strike_gex_curve` back into the report)

- [ ] **Step 1: Write a failing integration test**

`tests/integration/test_pipeline_strike_gex.py`:

```python
"""After run_single_stock, scan_runs.strike_gex_curve should be populated
and assemble_single_stock_report should round-trip it into the report."""
from decimal import Decimal
from unittest.mock import patch

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.reports.single_stock import assemble_single_stock_report


@pytest.mark.integration
def test_strike_gex_curve_persisted_and_round_trips():
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        # Insert a fake run with a curve payload
        run_id = repo.start_scan_run(ticker="ZZTEST", scan_type="single_stock")
        repo.set_strike_gex_curve(run_id, [
            {"strike": "100", "expiry": "2026-05-30", "net_gex": "12.5",
             "call_gex": "20", "put_gex": "-7.5"},
            {"strike": "110", "expiry": "2026-05-30", "net_gex": "-5",
             "call_gex": "10", "put_gex": "-15"},
        ])
        repo.finish_scan_run(run_id, status="ok")
        conn.commit()

        report = assemble_single_stock_report("ZZTEST", run_id, repo)
        assert len(report.strike_gex_curve) == 2
        assert report.strike_gex_curve[0].strike == Decimal("100")
        assert report.strike_gex_curve[1].net_gex == Decimal("-5")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_pipeline_strike_gex.py -v`
Expected: FAIL — `Repository.set_strike_gex_curve` doesn't exist.

- [ ] **Step 3: Add the repo method**

In `repository.py`:

```python
    def set_strike_gex_curve(self, run_id: int, curve: list[dict]) -> None:
        """Persist the per-strike, per-expiry GEX curve as JSONB on the run row."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.scan_runs SET strike_gex_curve=%s WHERE run_id=%s",
                (psycopg.types.json.Json(curve), run_id),
            )
        self.conn.commit()

    def get_strike_gex_curve(self, run_id: int) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT strike_gex_curve FROM {self.schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else []
```

- [ ] **Step 4: Update `assemble_single_stock_report` to populate `strike_gex_curve` on the report**

In `src/uw_scan/reports/single_stock.py`, near the bottom where the report is constructed, add:

```python
    curve_raw = repo.get_strike_gex_curve(run_id)
    report.strike_gex_curve = [StrikeGexBucket(**row) for row in curve_raw]
```

Add the import for `StrikeGexBucket` at the top of the file.

- [ ] **Step 5: Update `pipeline.run_single_stock` to build the curve and call `set_strike_gex_curve`**

After the existing greek-exposure fetch (around `# 8. Greek exposure (strike-expiry)`), aggregate the per-strike rows by (strike, expiry) and persist:

```python
        # 8b. Build and persist the strike_gex_curve for this run
        curve = []
        for r in ge_rows:
            curve.append({
                "strike": str(r.strike),
                "expiry": r.expiry.isoformat(),
                "net_gex": str((r.call_gex or 0) + (r.put_gex or 0)) if r.call_gex is not None or r.put_gex is not None else None,
                "call_gex": str(r.call_gex) if r.call_gex is not None else None,
                "put_gex":  str(r.put_gex)  if r.put_gex  is not None else None,
            })
        repo.set_strike_gex_curve(run_id, curve)
```

(`Decimal` values are stringified for JSONB — they round-trip through `Decimal(str(...))` later in `assemble_single_stock_report`.)

- [ ] **Step 6: Run the test and verify pass**

Run: `uv run pytest tests/integration/test_pipeline_strike_gex.py -v`
Expected: PASS.

- [ ] **Step 7: Run the existing pipeline tests to verify no regression**

Run: `uv run pytest tests/integration/ -v -k "pipeline"`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/pipeline.py src/uw_scan/storage/repository.py \
        src/uw_scan/reports/single_stock.py \
        tests/integration/test_pipeline_strike_gex.py
git commit -m "feat(pipeline): persist strike_gex_curve JSONB per run"
```

### Task S2.4 — Verify or normalise `volatility.skew_25d` to 30 DTE

**Files:**
- Read: `src/uw_scan/pipeline.py` (the skew fetch section)
- Read: `src/uw_scan/sources/uw_sources.py` (`fetch_skew`)
- Read: `src/uw_scan/reports/single_stock.py` (where `skew_25d` lands on the report)

- [ ] **Step 1: Find which DTE the current pipeline picks for `skew_25d`**

Run: `grep -n "skew_25d\|fetch_skew\|SkewRow" src/uw_scan/`

Trace the code path:
- Where does `fetch_skew` choose the expiry? (currently uses `nearest_expiry`, per pipeline.py)
- How is the chosen `SkewRow.risk_reversal` written to `volatility.skew_25d`?

- [ ] **Step 2: Decide the action**

Two outcomes possible:
- **(A) Current pipeline picks nearest expiry, not 30 DTE.** Need to interpolate. Implement S2.4 steps 3–6 below.
- **(B) Current pipeline already picks ~30 DTE.** Document the existing behavior and skip to S2.5.

Record the outcome as a one-paragraph note in `docs/superpowers/research/2026-05-12-skew-dte-verification.md`.

- [ ] **Step 3: (If A) Add `SKEW_TARGET_DTE_DAYS` to config**

In `src/uw_scan/config.py` `Settings`:

```python
    skew_target_dte_days: int = 30
```

(No `.env` override needed — this is a structural constant; users won't tune it.)

- [ ] **Step 4: (If A) Add a helper `pick_skew_at_30dte` that interpolates**

In `src/uw_scan/normalize.py`:

```python
def pick_skew_at_30dte(skew_rows: list[SkewRow], target_dte: int = 30) -> Decimal | None:
    """Pick or linearly-interpolate the 25Δ RR at `target_dte` days from `skew_rows`.

    Each input row has a per-expiry 25Δ risk_reversal. We select the two
    expiries straddling target_dte and interpolate linearly on DTE. If only
    one expiry is on one side of target_dte, return its risk_reversal as-is
    (no extrapolation). Returns None if skew_rows is empty.
    """
    twenty_fives = [r for r in skew_rows if r.delta == 25 and r.risk_reversal is not None and r.expiry is not None]
    if not twenty_fives:
        return None
    today = _date.today()
    by_dte = sorted(
        ((max(0, (r.expiry - today).days), r.risk_reversal) for r in twenty_fives),
        key=lambda p: p[0],
    )
    # exact match
    for dte, rr in by_dte:
        if dte == target_dte:
            return rr
    lower = [(d, rr) for d, rr in by_dte if d < target_dte]
    upper = [(d, rr) for d, rr in by_dte if d > target_dte]
    if lower and upper:
        d_lo, rr_lo = lower[-1]
        d_hi, rr_hi = upper[0]
        w = Decimal(target_dte - d_lo) / Decimal(d_hi - d_lo)
        return rr_lo + (rr_hi - rr_lo) * w
    # No straddle — fall back to nearest
    return by_dte[0][1]
```

- [ ] **Step 5: (If A) Wire it into the pipeline**

In `pipeline.py` where `volatility.skew_25d` is currently populated, replace the nearest-expiry pick with `normalize.pick_skew_at_30dte(skew_rows, settings.skew_target_dte_days)`.

- [ ] **Step 6: (If A) Add a unit test**

`tests/unit/test_skew_interpolation.py`:

```python
from datetime import date, timedelta
from decimal import Decimal
from uw_scan.models import SkewRow
from uw_scan.normalize import pick_skew_at_30dte


def _row(dte: int, rr: str) -> SkewRow:
    return SkewRow(
        ticker="TSLA", date=date.today(), delta=25,
        risk_reversal=Decimal(rr),
        expiry=date.today() + timedelta(days=dte),
    )


def test_pick_skew_at_30dte_exact_match():
    rows = [_row(15, "-0.01"), _row(30, "-0.02"), _row(45, "-0.03")]
    assert pick_skew_at_30dte(rows, 30) == Decimal("-0.02")


def test_pick_skew_at_30dte_interpolates_straddle():
    rows = [_row(20, "-0.010"), _row(40, "-0.030")]
    # halfway between 20 and 40 → halfway between -0.010 and -0.030 = -0.020
    assert pick_skew_at_30dte(rows, 30) == Decimal("-0.020")


def test_pick_skew_at_30dte_fallback_nearest_when_no_straddle():
    rows = [_row(45, "-0.025"), _row(60, "-0.030")]
    # No DTE below 30 — return nearest = DTE 45.
    assert pick_skew_at_30dte(rows, 30) == Decimal("-0.025")


def test_pick_skew_at_30dte_returns_none_for_empty():
    assert pick_skew_at_30dte([], 30) is None
```

Run: `uv run pytest tests/unit/test_skew_interpolation.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/normalize.py src/uw_scan/pipeline.py \
        docs/superpowers/research/2026-05-12-skew-dte-verification.md \
        tests/unit/test_skew_interpolation.py
git commit -m "feat(skew): normalise volatility.skew_25d to 30 DTE via interpolation"
```

### Task S2.5 — Wire `MarketAggregates` into the pipeline

**Files:**
- Modify: `src/uw_scan/pipeline.py`
- Modify: `src/uw_scan/reports/single_stock.py`

- [ ] **Step 1: Update `run_single_stock` to fetch the screener row and attach to the report**

In `pipeline.py`, after the trade-plan construction (right before `repo.finish_scan_run(...)`):

```python
        # 18. Per-ticker bulk screener — feeds MarketAggregates on the report
        screener_row = uw_sources.fetch_bulk_screener_ticker(client, repo, run_id, ticker)
        if screener_row is not None:
            report.aggregates = MarketAggregates(
                call_oi_total=screener_row.call_open_interest,
                put_oi_total=screener_row.put_open_interest,
                call_volume_total=screener_row.call_volume,
                put_volume_total=screener_row.put_volume,
                call_volume_ask_side=screener_row.call_volume_ask_side,
                call_volume_bid_side=screener_row.call_volume_bid_side,
                put_volume_ask_side=screener_row.put_volume_ask_side,
                put_volume_bid_side=screener_row.put_volume_bid_side,
                pcr_oi=screener_row.put_call_ratio,
                pcr_vol=(
                    Decimal(screener_row.put_volume) / Decimal(screener_row.call_volume)
                    if screener_row.put_volume and screener_row.call_volume else None
                ),
                iv30d=screener_row.iv30d,
            )
            repo.set_aggregates(run_id, report.aggregates)
```

Add `from uw_scan.models import MarketAggregates` at the top.

- [ ] **Step 2: Add `Repository.set_aggregates` (writes JSONB to a new column or to an `aggregates` table)**

The simplest path: add another nullable JSONB column to `scan_runs` via a 7th migration.

`src/uw_scan/storage/migrations/007_aggregates_column.sql`:

```sql
SET search_path TO uw_scan;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS aggregates JSONB;
```

Apply:

```bash
bash scripts/migrate.sh
```

Repository:

```python
    def set_aggregates(self, run_id: int, agg: "MarketAggregates") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.scan_runs SET aggregates=%s WHERE run_id=%s",
                (psycopg.types.json.Json(agg.model_dump(mode="json")), run_id),
            )
        self.conn.commit()

    def get_aggregates(self, run_id: int) -> "MarketAggregates | None":
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT aggregates FROM {self.schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        from uw_scan.models import MarketAggregates
        return MarketAggregates.model_validate(row[0])
```

- [ ] **Step 3: Update `assemble_single_stock_report` to load `aggregates` from the run row**

In `src/uw_scan/reports/single_stock.py`, near the end (next to the `strike_gex_curve` load from S2.3):

```python
    report.aggregates = repo.get_aggregates(run_id)
```

- [ ] **Step 4: Write the integration test**

`tests/integration/test_pipeline_aggregates.py`:

```python
"""run_single_stock should populate MarketAggregates from the screener row,
and assemble_single_stock_report should round-trip it."""
from decimal import Decimal
from unittest.mock import patch

import pytest

# Reuse the existing live-pipeline fixture pattern from tests/integration/
# (look at any existing tests in that dir for the canonical setup).


@pytest.mark.integration
def test_aggregates_round_trip(live_repo, live_client):
    from uw_scan.pipeline import run_single_stock
    from uw_scan.reports.single_stock import assemble_single_stock_report

    report = run_single_stock("AAPL", live_client, live_repo)
    assert report.aggregates is not None
    assert report.aggregates.call_oi_total is not None
    assert report.aggregates.pcr_oi is not None

    # Re-assemble from DB and verify equality of the aggregates payload.
    again = assemble_single_stock_report("AAPL", report.run_id, live_repo)
    assert again.aggregates.call_oi_total == report.aggregates.call_oi_total
    assert again.aggregates.pcr_oi == report.aggregates.pcr_oi
```

- [ ] **Step 5: Run the test (skip if no UW API key is configured locally)**

Run: `uv run pytest tests/integration/test_pipeline_aggregates.py -v`
Expected: PASS (or SKIP if marked accordingly).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/pipeline.py src/uw_scan/reports/single_stock.py \
        src/uw_scan/storage/repository.py \
        src/uw_scan/storage/migrations/007_aggregates_column.sql \
        tests/integration/test_pipeline_aggregates.py
git commit -m "feat(pipeline): wire MarketAggregates into run_single_stock via bulk-screener"
```

### Task S2.6 — Append to `pcr_history` at end of each scan

**Files:**
- Modify: `src/uw_scan/pipeline.py`

- [ ] **Step 1: After the aggregates wiring in S2.5, add the PCR history write**

```python
        # 19. Append PCR snapshot for 30d-delta computation later.
        if report.aggregates and (report.aggregates.pcr_oi is not None or report.aggregates.pcr_vol is not None):
            repo.append_pcr_history(
                ticker=ticker,
                snapshot_date=_date.today(),
                pcr_oi=report.aggregates.pcr_oi,
                pcr_vol=report.aggregates.pcr_vol,
            )
```

- [ ] **Step 2: Write an integration test verifying the row appears**

`tests/integration/test_pcr_history_append.py`:

```python
from datetime import date
import pytest


@pytest.mark.integration
def test_pcr_history_appended_after_scan(live_repo, live_client):
    from uw_scan.pipeline import run_single_stock
    run_single_stock("AAPL", live_client, live_repo)
    row = live_repo.get_pcr_history_row("AAPL", date.today())
    assert row is not None
    assert row.pcr_oi is not None or row.pcr_vol is not None
```

(Add `Repository.get_pcr_history_row` if missing — straightforward `SELECT WHERE ticker=%s AND snapshot_date=%s`.)

- [ ] **Step 3: Run + verify**

Run: `uv run pytest tests/integration/test_pcr_history_append.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/pipeline.py src/uw_scan/storage/repository.py \
        tests/integration/test_pcr_history_append.py
git commit -m "feat(pipeline): append pcr_history snapshot at end of each scan"
```

### Task S2.7 — Verify S2 end-state

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest tests/ -v`
Expected: green.

- [ ] **Step 2: Smoke-test a live single-stock run**

Run: `uv run python -c "
from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock
from uw_scan.storage.repository import Repository
import psycopg

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, UwClient(api_key=s.api_key.get_secret_value(), base_url=s.base_url, timeout=s.request_timeout_seconds) as c:
    repo = Repository(conn, schema=s.db_schema)
    report = run_single_stock('AAPL', c, repo)
    print('run_id:', report.run_id)
    print('aggregates.pcr_oi:', report.aggregates.pcr_oi if report.aggregates else None)
    print('strike_gex_curve rows:', len(report.strike_gex_curve))
    print('volatility.skew_25d:', report.volatility.skew_25d)
"`

Expected: prints non-null `pcr_oi`, non-zero `strike_gex_curve` rows, a `skew_25d` value.

S2 done. The pipeline now produces every field the watchlist card needs (modulo OHLC, which S3 adds).

---

## Slice S3 — Massive.com OHLC provider

**Goal:** Implement a clean `OhlcProvider` protocol with a `MassiveOhlcProvider` concrete implementation that talks to `api.massive.com`. Two operations: fetch a daily OHLC range, and fetch the latest (15-min delayed) intraday quote. All behind a typed interface so we can swap providers later.

**S3 starts with a discovery spike** — the assumed endpoint shapes from web search need to be confirmed against the live API before we commit them as final.

### Task S3.1 — Discovery spike: verify massive.com endpoints

**Files:**
- Create: `scripts/spikes/massive_spike.py`
- Create: `docs/superpowers/research/2026-05-12-massive-com-api-spike.md`

- [ ] **Step 1: Get a working `MASSIVE_API_KEY` from the user**

If not yet present in `.env`, ask the user to add `MASSIVE_API_KEY=<their-key>`. Confirm by:

```bash
grep -q "^MASSIVE_API_KEY=." .env || echo "MISSING — ask the user to add MASSIVE_API_KEY to .env"
```

- [ ] **Step 2: Write a tiny spike script that hits the three candidate endpoints**

```python
# scripts/spikes/massive_spike.py
"""Probe the massive.com REST API to confirm endpoint shape, auth header,
and JSON keys. Run manually; not part of the test suite. Output is captured
into docs/superpowers/research/2026-05-12-massive-com-api-spike.md."""
import os
import sys
import json
import httpx
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from uw_scan.config import Settings  # noqa: E402

s = Settings.from_env()
api_key = os.environ["MASSIVE_API_KEY"]
base = "https://api.massive.com"

with httpx.Client(headers={"Authorization": f"Bearer {api_key}"}, timeout=10.0) as c:
    # 1) Daily ticker summary (single date)
    r1 = c.get(f"{base}/v1/open-close/AAPL/2026-05-08")
    print("=== /v1/open-close/AAPL/2026-05-08 ===")
    print(r1.status_code)
    print(json.dumps(r1.json(), indent=2)[:600])

    # 2) Custom bars (range, Polygon-shaped path)
    r2 = c.get(f"{base}/v2/aggs/ticker/AAPL/range/1/day/2026-04-01/2026-05-08")
    print("\n=== /v2/aggs/ticker/AAPL/range/1/day/2026-04-01/2026-05-08 ===")
    print(r2.status_code)
    print(json.dumps(r2.json(), indent=2)[:1000])

    # 3) Latest quote (v3)
    r3 = c.get(f"{base}/v3/quotes/AAPL")
    print("\n=== /v3/quotes/AAPL ===")
    print(r3.status_code)
    print(json.dumps(r3.json(), indent=2)[:600])
```

- [ ] **Step 3: Run the spike**

```bash
uv run python scripts/spikes/massive_spike.py 2>&1 | tee /tmp/massive_spike.out
```

- [ ] **Step 4: Capture findings in a research note**

Write `docs/superpowers/research/2026-05-12-massive-com-api-spike.md` recording:
- Final base URL (confirmed)
- Daily-range endpoint path and the JSON-key shape (`results[].t/o/h/l/c/v` is the typical Polygon-shaped response)
- Quote endpoint path and JSON-key shape (`results[].t/p`, plus delay metadata if any)
- Auth header (`Authorization: Bearer ...`)
- Rate limit (header `X-RateLimit-Remaining` if present, plus tier you're on)
- Any unexpected behavior (e.g., the daily-range returning `null` results on weekends, holiday handling)

- [ ] **Step 5: Commit**

```bash
git add scripts/spikes/massive_spike.py \
        docs/superpowers/research/2026-05-12-massive-com-api-spike.md
git commit -m "spike(massive): probe v1 open-close / v2 aggs / v3 quotes endpoints"
```

### Task S3.2 — Implement `OhlcProvider` protocol + dataclasses

**Files:**
- Create: `src/uw_scan/sources/ohlc.py`
- Create: `tests/unit/sources/__init__.py` (empty)
- Create: `tests/unit/sources/test_ohlc_provider.py`

- [ ] **Step 1: Define the dataclasses + protocol**

```python
# src/uw_scan/sources/ohlc.py
"""OHLC provider protocol + Massive.com concrete implementation.

Provider returns typed dataclasses; persistence is the caller's responsibility.
The repository layer stores them in `daily_ohlc` and `intraday_quote`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OhlcBar:
    ticker: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None


@dataclass(frozen=True)
class IntradayQuote:
    ticker: str
    price: Decimal
    quoted_at: datetime  # tz-aware UTC


class OhlcProvider(Protocol):
    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]: ...
    def fetch_intraday_quote(self, ticker: str) -> IntradayQuote | None: ...


class MassiveOhlcProvider:
    """REST client for api.massive.com (Polygon-shaped API).

    Endpoints (confirmed in S3.1 spike):
    - GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to} → daily bars
    - GET /v3/quotes/{ticker} → latest quote (15-min delayed on lower tiers)
    """

    def __init__(self, api_key: str, base_url: str = "https://api.massive.com",
                 timeout: float = 10.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MassiveOhlcProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]:
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        r = self._client.get(path)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results") or []
        bars: list[OhlcBar] = []
        for row in results:
            # Polygon shape: t=ms epoch, o/h/l/c=price, v=volume
            t_ms = row.get("t")
            if t_ms is None or row.get("c") is None:
                continue
            bar_date = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).date()
            bars.append(OhlcBar(
                ticker=ticker,
                date=bar_date,
                open=Decimal(str(row["o"])) if row.get("o") is not None else None,
                high=Decimal(str(row["h"])) if row.get("h") is not None else None,
                low=Decimal(str(row["l"])) if row.get("l") is not None else None,
                close=Decimal(str(row["c"])),
                volume=int(row["v"]) if row.get("v") is not None else None,
            ))
        return bars

    def fetch_intraday_quote(self, ticker: str) -> IntradayQuote | None:
        path = f"/v3/quotes/{ticker}"
        r = self._client.get(path)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results") or []
        if not results:
            return None
        latest = results[0]
        # The exact key names are spike-confirmed; fallback chain handles either
        # "P" (Polygon-ish) or "ap"/"bp" mid:
        price = (
            latest.get("P")
            or latest.get("p")
            or latest.get("ap")
            or latest.get("bp")
        )
        t_ns = latest.get("t") or latest.get("participant_timestamp")
        if price is None or t_ns is None:
            return None
        # Polygon quotes report nanoseconds; massive may report ns or ms — try both.
        t_int = int(t_ns)
        seconds = t_int / 1_000_000_000 if t_int > 10**14 else t_int / 1000
        return IntradayQuote(
            ticker=ticker,
            price=Decimal(str(price)),
            quoted_at=datetime.fromtimestamp(seconds, tz=timezone.utc),
        )
```

- [ ] **Step 2: Write fixture-backed unit tests using `httpx.MockTransport`**

```python
# tests/unit/sources/test_ohlc_provider.py
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest

from uw_scan.sources.ohlc import MassiveOhlcProvider, OhlcBar, IntradayQuote


def _provider_with(handler) -> MassiveOhlcProvider:
    p = MassiveOhlcProvider(api_key="test", base_url="https://api.massive.com")
    p._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
        base_url="https://api.massive.com",
    )
    return p


def test_fetch_daily_returns_bars():
    def handler(req):
        assert req.url.path == "/v2/aggs/ticker/AAPL/range/1/day/2026-04-01/2026-05-01"
        return httpx.Response(200, json={
            "ticker": "AAPL",
            "results": [
                {"t": 1746057600000, "o": 100.0, "h": 102.0, "l": 99.5, "c": 101.25, "v": 12345678},
                {"t": 1746144000000, "o": 101.5, "h": 103.0, "l": 101.0, "c": 102.50, "v": 9876543},
            ],
        })
    p = _provider_with(handler)
    bars = p.fetch_daily("AAPL", date(2026, 4, 1), date(2026, 5, 1))
    assert len(bars) == 2
    assert bars[0].close == Decimal("101.25")
    assert bars[1].volume == 9876543


def test_fetch_daily_empty():
    p = _provider_with(lambda req: httpx.Response(200, json={"results": []}))
    bars = p.fetch_daily("ZZZZ", date(2026, 4, 1), date(2026, 5, 1))
    assert bars == []


def test_fetch_intraday_quote():
    def handler(req):
        return httpx.Response(200, json={
            "results": [{"P": 445.12, "t": 1746210000000000000}]
        })
    p = _provider_with(handler)
    q = p.fetch_intraday_quote("TSLA")
    assert q is not None
    assert q.price == Decimal("445.12")
    assert q.quoted_at.tzinfo is timezone.utc


def test_fetch_intraday_quote_404():
    p = _provider_with(lambda req: httpx.Response(404, json={}))
    assert p.fetch_intraday_quote("UNKNOWN") is None
```

- [ ] **Step 3: Run tests, verify fail then pass**

Run: `uv run pytest tests/unit/sources/test_ohlc_provider.py -v`

If FAIL before implementation, ensure `src/uw_scan/sources/ohlc.py` is committed in the same step. After implementation: PASS.

- [ ] **Step 4: Add config fields**

In `src/uw_scan/config.py`:

```python
class Settings(BaseModel):
    # ... existing fields ...
    massive_api_key: SecretStr | None = None
    massive_base_url: str = "https://api.massive.com"
```

And in `from_env`:

```python
            massive_api_key=SecretStr(os.environ.get("MASSIVE_API_KEY", "")) or None,
            massive_base_url=os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com"),
```

Update `.env.example`:

```
MASSIVE_API_KEY=
MASSIVE_BASE_URL=https://api.massive.com
```

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/ohlc.py src/uw_scan/config.py .env.example \
        tests/unit/sources/__init__.py tests/unit/sources/test_ohlc_provider.py
git commit -m "feat(sources): MassiveOhlcProvider — daily bars + intraday quote"
```

### Task S3.3 — Integration test against a recorded fixture corpus

**Files:**
- Create: `tests/fixtures/massive/daily_aggs_AAPL.json`
- Create: `tests/fixtures/massive/quote_AAPL.json`
- Create: `tests/integration/sources/__init__.py` (empty)
- Create: `tests/integration/sources/test_massive_against_fixtures.py`

- [ ] **Step 1: Capture two real responses from the spike output**

From `/tmp/massive_spike.out` (S3.1 step 3), copy the JSON bodies of `/v2/aggs/.../range/1/day/...` and `/v3/quotes/AAPL` into fixture files. Redact nothing — these are public ticker data.

- [ ] **Step 2: Write the fixture-backed test**

```python
# tests/integration/sources/test_massive_against_fixtures.py
"""Drive MassiveOhlcProvider with recorded responses from /v2/aggs and /v3/quotes
to lock in the parser's shape against real payloads."""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from uw_scan.sources.ohlc import MassiveOhlcProvider

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "massive"


def _provider(handler) -> MassiveOhlcProvider:
    p = MassiveOhlcProvider(api_key="test")
    p._client = httpx.Client(transport=httpx.MockTransport(handler),
                              base_url="https://api.massive.com")
    return p


def test_daily_aggs_real_shape():
    payload = json.loads((FIXTURES / "daily_aggs_AAPL.json").read_text())
    p = _provider(lambda req: httpx.Response(200, json=payload))
    bars = p.fetch_daily("AAPL", date(2026, 4, 1), date(2026, 5, 8))
    assert len(bars) > 0
    assert all(b.close > 0 for b in bars)
    assert bars[0].date <= bars[-1].date  # ordered ascending or descending — record observed


def test_quote_real_shape():
    payload = json.loads((FIXTURES / "quote_AAPL.json").read_text())
    p = _provider(lambda req: httpx.Response(200, json=payload))
    q = p.fetch_intraday_quote("AAPL")
    assert q is not None
    assert q.price > 0
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/integration/sources/test_massive_against_fixtures.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/massive/ tests/integration/sources/__init__.py \
        tests/integration/sources/test_massive_against_fixtures.py
git commit -m "test(sources): fixture-backed parser tests for massive.com daily + quote"
```

S3 done.

---

## Slice S4 — Card-row derivation (pure functions)

**Goal:** Pure-Python functions that take a `SingleStockReport` (+ optional OHLC history + optional intraday quote + optional 30d-prior PCR) and produce a fully-populated `WatchlistCardRow` dict. Unit-test heavy, no I/O.

### Task S4.1 — GEX helpers (flip strike, max strike, expiring %)

**Files:**
- Create: `src/uw_scan/cards/gex.py`
- Create: `tests/unit/cards/__init__.py` (empty)
- Create: `tests/unit/cards/test_gex.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import StrikeGexBucket
from uw_scan.cards.gex import (
    find_flip_strike, max_gex_strike, gex_expiring_pct,
)


def _b(strike, expiry, net):
    return StrikeGexBucket(strike=Decimal(strike), expiry=date.fromisoformat(expiry),
                           net_gex=Decimal(net))


def test_find_flip_strike_simple_sign_change():
    curve = [
        _b("90",  "2026-05-30", "-30"),
        _b("100", "2026-05-30", "-10"),
        _b("110", "2026-05-30",  "20"),
        _b("120", "2026-05-30",  "40"),
    ]
    # Cumulative passes from -10 (at 100) to +10 (at 110); flip strike = 110
    assert find_flip_strike(curve) == Decimal("110")


def test_find_flip_strike_all_positive_returns_none():
    curve = [_b("100", "2026-05-30", "10"), _b("110", "2026-05-30", "20")]
    assert find_flip_strike(curve) is None


def test_find_flip_strike_empty_curve_returns_none():
    assert find_flip_strike([]) is None


def test_max_gex_strike_picks_largest_absolute():
    curve = [
        _b("100", "2026-05-30",  "10"),
        _b("110", "2026-05-30", "-50"),
        _b("120", "2026-05-30",  "25"),
    ]
    assert max_gex_strike(curve) == Decimal("110")


def test_gex_expiring_pct_bucketed_by_expiry():
    curve = [
        _b("100", "2026-05-30",  "10"),
        _b("110", "2026-05-30", "-30"),  # |sum @ 2026-05-30| = |10-30| = 20
        _b("100", "2026-06-20",  "50"),
        _b("110", "2026-06-20",  "-5"),  # |sum @ 2026-06-20| = |50-5| = 45
    ]
    # Nearest expiry = 2026-05-30. Denominator = 20 + 45 = 65. Numerator = 20.
    pct = gex_expiring_pct(curve)
    assert pct is not None
    assert abs(pct - Decimal("20") / Decimal("65")) < Decimal("0.0001")


def test_gex_expiring_pct_empty_curve_returns_none():
    assert gex_expiring_pct([]) is None


def test_gex_expiring_pct_all_zero_returns_none():
    """Spec §7 null condition: denominator (sum of absolutes) is zero."""
    curve = [_b("100", "2026-05-30", "0"), _b("110", "2026-05-30", "0")]
    assert gex_expiring_pct(curve) is None
```

- [ ] **Step 2: Verify fail**

Run: `uv run pytest tests/unit/cards/test_gex.py -v`
Expected: ImportError / module not found.

- [ ] **Step 3: Implement `cards/gex.py`**

```python
"""Pure derivations on the per-strike, per-expiry GEX curve."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from uw_scan.models import StrikeGexBucket


def find_flip_strike(curve: list[StrikeGexBucket]) -> Decimal | None:
    """Return the lowest strike at which the cumulative net_gex (ascending by strike)
    changes sign or hits zero. If the curve never crosses zero, return None.

    For multi-expiry curves, we aggregate net_gex per strike across all expiries
    before computing the cumulative — this matches how the spec's "GEX Flip" reads
    (a single price level where dealer hedging direction inverts).
    """
    if not curve:
        return None
    per_strike = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            per_strike[b.strike] += b.net_gex
    items = sorted(per_strike.items(), key=lambda kv: kv[0])
    cumulative = Decimal("0")
    prev_sign = 0
    for strike, ngex in items:
        cumulative += ngex
        sign = (cumulative > 0) - (cumulative < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            return strike
        if sign != 0:
            prev_sign = sign
    return None


def max_gex_strike(curve: list[StrikeGexBucket]) -> Decimal | None:
    """The strike with the largest absolute aggregated net_gex (summed across expiries)."""
    if not curve:
        return None
    per_strike: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            per_strike[b.strike] += b.net_gex
    if not per_strike:
        return None
    return max(per_strike.items(), key=lambda kv: abs(kv[1]))[0]


def gex_expiring_pct(curve: list[StrikeGexBucket]) -> Decimal | None:
    """|net_gex @ nearest_expiry| / sum(|net_gex_by_expiry|).

    Spec §7: denominator is sum of absolute values; null only when the curve is
    empty OR every per-expiry net_gex sums to exactly zero.
    """
    if not curve:
        return None
    by_expiry: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            by_expiry[b.expiry] += b.net_gex
    if not by_expiry:
        return None
    nearest = min(by_expiry.keys())
    denom = sum(abs(v) for v in by_expiry.values())
    if denom == 0:
        return None
    return abs(by_expiry[nearest]) / denom


def nearest_expiry(curve: list[StrikeGexBucket]) -> date | None:
    if not curve:
        return None
    return min(b.expiry for b in curve)
```

- [ ] **Step 4: Run + verify pass**

Run: `uv run pytest tests/unit/cards/test_gex.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/gex.py tests/unit/cards/__init__.py tests/unit/cards/test_gex.py
git commit -m "feat(cards): GEX flip/max-strike/expiring-pct derivations"
```

### Task S4.2 — Return helpers (1d / 1w / 30d)

**Files:**
- Create: `src/uw_scan/cards/returns.py`
- Create: `tests/unit/cards/test_returns.py`

- [ ] **Step 1: Write the test**

```python
from datetime import date, timedelta
from decimal import Decimal
import pytest

from uw_scan.sources.ohlc import OhlcBar
from uw_scan.cards.returns import compute_returns


def _bar(d: date, close: str) -> OhlcBar:
    return OhlcBar(ticker="X", date=d, open=None, high=None, low=None,
                   close=Decimal(close), volume=None)


def test_returns_with_full_history():
    today = date(2026, 5, 8)
    # 22+ trading days of history; we only need indices -1, -5, -21.
    history = [_bar(today - timedelta(days=22 - i), str(100 + i)) for i in range(22)]
    # close[-1] = 121, close[-5] = 117, close[-21] = 101
    intraday_price = Decimal("125.00")
    r = compute_returns(history, intraday_price)
    assert r.ret_1d == (Decimal("125.00") - Decimal("121")) / Decimal("121")
    assert r.ret_1w == (Decimal("125.00") - Decimal("117")) / Decimal("117")
    assert r.ret_30d == (Decimal("125.00") - Decimal("101")) / Decimal("101")


def test_returns_insufficient_history_yields_none():
    today = date(2026, 5, 8)
    history = [_bar(today - timedelta(days=3), "100"), _bar(today - timedelta(days=2), "101")]
    r = compute_returns(history, Decimal("102"))
    assert r.ret_1d is not None  # have one prior close
    assert r.ret_1w is None       # need 5 prior
    assert r.ret_30d is None      # need 21 prior


def test_returns_empty_history_all_none():
    r = compute_returns([], Decimal("100"))
    assert r.ret_1d is None and r.ret_1w is None and r.ret_30d is None


def test_returns_no_intraday_falls_back_to_last_close():
    today = date(2026, 5, 8)
    history = [_bar(today - timedelta(days=22 - i), str(100 + i)) for i in range(22)]
    r = compute_returns(history, None)
    # Without intraday, ret_1d uses close[-1] vs close[-2]
    assert r.ret_1d == (Decimal("121") - Decimal("120")) / Decimal("120")
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/cards/returns.py
"""Return calculations for the watchlist card."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from uw_scan.sources.ohlc import OhlcBar


@dataclass(frozen=True)
class Returns:
    ret_1d: Decimal | None
    ret_1w: Decimal | None
    ret_30d: Decimal | None


def compute_returns(history: list[OhlcBar], price: Decimal | None) -> Returns:
    """Compute 1-day / 1-week (5 trading days) / 30-day (21 trading days) returns.

    `history` must be sorted ascending by date. `price` is the current intraday
    price; if None, falls back to the most recent close for the 1d calculation
    and yields close-to-close values for 1w/30d.
    """
    sorted_hist = sorted(history, key=lambda b: b.date)
    n = len(sorted_hist)
    last_close = sorted_hist[-1].close if n >= 1 else None
    numerator = price if price is not None else last_close

    def _ret(lookback_offset: int) -> Decimal | None:
        idx = n - 1 - lookback_offset
        if idx < 0 or numerator is None:
            return None
        ref = sorted_hist[idx].close
        if ref == 0:
            return None
        return (numerator - ref) / ref

    return Returns(
        ret_1d=_ret(1) if price is not None else (_ret(0) if n >= 2 else None),
        # When `price` is provided, ret_1d uses close[-1] as the "previous" reference.
        # When `price` is None, fall through to close-to-close: numerator=close[-1], ref=close[-2].
        ret_1w=_ret(5),
        ret_30d=_ret(21),
    )
```

Wait — re-read the test. `test_returns_no_intraday_falls_back_to_last_close` expects `(121 - 120) / 120`, which is `_ret(1)` with numerator=close[-1]=121, ref=close[-2]=120. The first branch `_ret(1) if price is not None` uses numerator=price, ref=close[-2]. The second branch `_ret(0) if n>=2` would use numerator=last_close, ref=close[-1] — wrong.

Fix: handle the no-price case correctly. Update the function:

```python
def compute_returns(history: list[OhlcBar], price: Decimal | None) -> Returns:
    sorted_hist = sorted(history, key=lambda b: b.date)
    n = len(sorted_hist)
    if n == 0:
        return Returns(None, None, None)
    last_close = sorted_hist[-1].close
    if price is None:
        # Close-to-close mode: drop the last element and treat last_close as "today's price"
        return compute_returns(sorted_hist[:-1], last_close)
    # price-anchored mode
    def _ret(lookback: int) -> Decimal | None:
        idx = n - lookback
        if idx < 0 or idx >= n:
            return None
        ref = sorted_hist[idx].close
        if ref == 0:
            return None
        return (price - ref) / ref
    return Returns(ret_1d=_ret(1), ret_1w=_ret(5), ret_30d=_ret(21))
```

- [ ] **Step 3: Run + verify pass**

Run: `uv run pytest tests/unit/cards/test_returns.py -v`
Expected: 4/4 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/returns.py tests/unit/cards/test_returns.py
git commit -m "feat(cards): 1d/1w/30d return calculations from OHLC + intraday"
```

### Task S4.3 — Aggression % and PCR-Δ helpers

**Files:**
- Create: `src/uw_scan/cards/aggression.py`
- Create: `src/uw_scan/cards/pcr.py`
- Create: `tests/unit/cards/test_aggression.py`
- Create: `tests/unit/cards/test_pcr.py`

- [ ] **Step 1: Test for aggression**

```python
# tests/unit/cards/test_aggression.py
from decimal import Decimal
from uw_scan.models import FlowSnapshot
from uw_scan.cards.aggression import compute_aggression_pct


def _flow(ask, bid):
    return FlowSnapshot(
        ticker="X", flow_count=0, net_premium=Decimal("0"),
        bull_premium=Decimal("0"), bear_premium=Decimal("0"),
        ask_side_premium=Decimal(ask), bid_side_premium=Decimal(bid),
    )


def test_aggression_pct_basic():
    assert compute_aggression_pct(_flow("80", "20")) == Decimal("0.8")


def test_aggression_pct_zero_total_returns_none():
    assert compute_aggression_pct(_flow("0", "0")) is None


def test_aggression_pct_all_ask_side_one():
    assert compute_aggression_pct(_flow("100", "0")) == Decimal("1")
```

- [ ] **Step 2: Implement aggression**

```python
# src/uw_scan/cards/aggression.py
from decimal import Decimal
from uw_scan.models import FlowSnapshot


def compute_aggression_pct(flow: FlowSnapshot) -> Decimal | None:
    """ask_side_premium / (ask_side + bid_side). None when total is zero."""
    ask = flow.ask_side_premium or Decimal("0")
    bid = flow.bid_side_premium or Decimal("0")
    total = ask + bid
    if total == 0:
        return None
    return ask / total
```

- [ ] **Step 3: Test for PCR delta**

```python
# tests/unit/cards/test_pcr.py
from datetime import date
from decimal import Decimal
from uw_scan.cards.pcr import compute_pcr_delta_30d


def test_pcr_delta_returns_diff():
    today = Decimal("1.75")
    prior = Decimal("1.50")
    assert compute_pcr_delta_30d(today, prior) == Decimal("0.25")


def test_pcr_delta_none_when_prior_missing():
    assert compute_pcr_delta_30d(Decimal("1.75"), None) is None


def test_pcr_delta_none_when_today_missing():
    assert compute_pcr_delta_30d(None, Decimal("1.50")) is None
```

- [ ] **Step 4: Implement PCR delta**

```python
# src/uw_scan/cards/pcr.py
from decimal import Decimal


def compute_pcr_delta_30d(today: Decimal | None, prior: Decimal | None) -> Decimal | None:
    if today is None or prior is None:
        return None
    return today - prior
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/unit/cards/test_aggression.py tests/unit/cards/test_pcr.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/aggression.py src/uw_scan/cards/pcr.py \
        tests/unit/cards/test_aggression.py tests/unit/cards/test_pcr.py
git commit -m "feat(cards): aggression % and pcr delta-30d helpers"
```

### Task S4.4 — Master derivation: `compute_watchlist_card_row`

**Files:**
- Create: `src/uw_scan/cards/derive.py`
- Create: `tests/unit/cards/test_derive.py`

- [ ] **Step 1: Write the failing high-level test**

```python
"""compute_watchlist_card_row should produce a complete card row from a
SingleStockReport + OHLC history + intraday quote + prior PCR snapshot."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from uw_scan.models import (
    SingleStockReport, MarketStructure, VolatilityProfile, FlowSnapshot,
    VRPAssessment, SetupClassification, MarketAggregates, StrikeGexBucket,
)
from uw_scan.sources.ohlc import OhlcBar, IntradayQuote
from uw_scan.storage.repository import PcrHistoryRow
from uw_scan.cards.derive import compute_watchlist_card_row


def _make_report(*, run_id: int = 1) -> SingleStockReport:
    today = date(2026, 5, 8)
    return SingleStockReport(
        run_id=run_id,
        ticker="TSLA",
        generated_at=datetime(2026, 5, 8, 13, 0, tzinfo=timezone.utc),
        market_structure=MarketStructure(
            spot=Decimal("445.12"),
            net_gex=Decimal("81256"),
            total_call_gex=Decimal("167045"),
            total_put_gex=Decimal("-85789"),
            max_pain=Decimal("410"),
        ),
        volatility=VolatilityProfile(
            iv=Decimal("0.691"), iv_rank=Decimal("39.0"),
            skew_25d=Decimal("-0.0146"),
        ),
        flow=FlowSnapshot(
            ticker="TSLA", flow_count=42,
            net_premium=Decimal("-50000000"),
            bull_premium=Decimal("60000000"),
            bear_premium=Decimal("110000000"),
            ask_side_premium=Decimal("91000000"),
            bid_side_premium=Decimal("9000000"),
        ),
        vrp=VRPAssessment(vrp=Decimal("-0.02"), signal="rich", note=""),
        setup=SetupClassification(
            setup_type="C", label="Deep Conviction",
            direction="bear", score=Decimal("1.51"),
        ),
        aggregates=MarketAggregates(
            call_oi_total=1_200_000, put_oi_total=2_100_000,
            pcr_oi=Decimal("1.75"), pcr_vol=Decimal("1.58"),
        ),
        strike_gex_curve=[
            StrikeGexBucket(strike=Decimal("420"), expiry=date(2026, 5, 15),
                            net_gex=Decimal("-50000")),
            StrikeGexBucket(strike=Decimal("440"), expiry=date(2026, 5, 15),
                            net_gex=Decimal("-30000")),
            StrikeGexBucket(strike=Decimal("450"), expiry=date(2026, 5, 15),
                            net_gex=Decimal("20000")),
            StrikeGexBucket(strike=Decimal("440"), expiry=date(2026, 6, 20),
                            net_gex=Decimal("50000")),
        ],
    )


def _make_ohlc(days: int = 22) -> list[OhlcBar]:
    today = date(2026, 5, 8)
    return [
        OhlcBar(ticker="TSLA", date=today - timedelta(days=days - i),
                open=None, high=None, low=None,
                close=Decimal(str(400 + i)), volume=None)
        for i in range(days)
    ]


def test_derive_full_row():
    report = _make_report()
    history = _make_ohlc()
    intraday = IntradayQuote(
        ticker="TSLA", price=Decimal("445.12"),
        quoted_at=datetime(2026, 5, 8, 13, 7, 55, tzinfo=timezone.utc),
    )
    prior_pcr = PcrHistoryRow(
        ticker="TSLA", snapshot_date=date(2026, 4, 8),
        pcr_oi=Decimal("1.78"), pcr_vol=Decimal("1.60"),
    )
    row = compute_watchlist_card_row(report, history, intraday, prior_pcr)

    # Header
    assert row["ticker"] == "TSLA"
    assert row["spot"] == Decimal("445.12")
    assert row["spot_source"] == "massive.com_intraday"
    assert row["iv_atm"] == Decimal("0.691")
    assert row["iv_rank"] == Decimal("39.0")

    # Setup
    assert row["setup_type"] == "C"
    assert row["setup_direction"] == "bear"
    assert row["setup_score"] == Decimal("1.51")

    # Aggression: 91 / (91 + 9) = 0.91
    assert row["aggression_pct"] == Decimal("0.91")

    # GEX block
    assert row["max_gex_strike"] is not None
    assert row["gex_per_1pct_move"] == Decimal("81256") * Decimal("0.01") * Decimal("445.12")
    assert row["gex_expiring_date"] == date(2026, 5, 15)
    assert row["gex_expiring_pct"] is not None

    # Skew
    assert row["skew_25d_30dte"] == Decimal("-0.0146")

    # Positioning
    assert row["pcr_oi"] == Decimal("1.75")
    assert row["pcr_vol"] == Decimal("1.58")
    assert row["pcr_delta_30d"] == Decimal("1.75") - Decimal("1.78")  # = -0.03


def test_derive_minimal_report_yields_mostly_nulls():
    report = _make_report()
    report.setup = None
    report.aggregates = None
    report.strike_gex_curve = []
    history: list[OhlcBar] = []
    row = compute_watchlist_card_row(report, history, None, None)
    assert row["setup_type"] is None
    assert row["aggression_pct"] is not None  # flow is still populated
    assert row["gex_flip_price"] is None
    assert row["gex_expiring_pct"] is None
    assert row["ret_1d"] is None
    assert row["pcr_delta_30d"] is None
```

- [ ] **Step 2: Implement `cards/derive.py`**

```python
# src/uw_scan/cards/derive.py
"""Pure derivation function that produces a complete watchlist_card row."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.models import SingleStockReport
from uw_scan.sources.ohlc import OhlcBar, IntradayQuote
from uw_scan.storage.repository import PcrHistoryRow
from uw_scan.cards import gex as _gex
from uw_scan.cards.returns import compute_returns
from uw_scan.cards.aggression import compute_aggression_pct
from uw_scan.cards.pcr import compute_pcr_delta_30d


def compute_watchlist_card_row(
    report: SingleStockReport,
    ohlc_history: list[OhlcBar],
    intraday: IntradayQuote | None,
    prior_pcr: PcrHistoryRow | None,
) -> dict[str, Any]:
    """Map a SingleStockReport (+ supporting data) onto the watchlist_card schema."""
    spot = intraday.price if intraday is not None else report.market_structure.spot
    spot_source = "massive.com_intraday" if intraday is not None else "uw_scan"

    returns = compute_returns(ohlc_history, intraday.price if intraday else None)
    flip_strike = _gex.find_flip_strike(report.strike_gex_curve)
    flip_distance = (
        (flip_strike - spot) / spot if (flip_strike is not None and spot) else None
    )
    per_1pct = (
        report.market_structure.net_gex * Decimal("0.01") * spot
        if report.market_structure.net_gex is not None and spot is not None else None
    )
    nearest = _gex.nearest_expiry(report.strike_gex_curve)

    agg = report.aggregates

    return {
        "ticker": report.ticker,
        "run_id": report.run_id,
        "scanned_at": report.generated_at,

        "spot": spot,
        "spot_quoted_at": intraday.quoted_at if intraday else None,
        "spot_source": spot_source,

        "iv_atm": report.volatility.iv,
        "iv_rank": report.volatility.iv_rank,

        "setup_type": report.setup.setup_type if report.setup else None,
        "setup_direction": report.setup.direction if report.setup else None,
        "setup_score": report.setup.score if report.setup else None,

        "aggression_pct": compute_aggression_pct(report.flow),

        "ret_1d":  returns.ret_1d,
        "ret_1w":  returns.ret_1w,
        "ret_30d": returns.ret_30d,

        "gex_flip_distance": flip_distance,
        "gex_flip_price":    flip_strike,
        "gex_per_1pct_move": per_1pct,
        "max_gex_strike":    _gex.max_gex_strike(report.strike_gex_curve),
        "gex_expiring_pct":  _gex.gex_expiring_pct(report.strike_gex_curve),
        "gex_expiring_date": nearest,

        "skew_25d_30dte": report.volatility.skew_25d,

        "call_oi_total": agg.call_oi_total if agg else None,
        "put_oi_total":  agg.put_oi_total  if agg else None,
        "pcr_oi":  agg.pcr_oi  if agg else None,
        "pcr_vol": agg.pcr_vol if agg else None,
        "pcr_delta_30d": (
            compute_pcr_delta_30d(agg.pcr_oi, prior_pcr.pcr_oi)
            if agg and prior_pcr else None
        ),
    }
```

- [ ] **Step 3: Run tests, verify pass**

Run: `uv run pytest tests/unit/cards/ -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/derive.py tests/unit/cards/test_derive.py
git commit -m "feat(cards): compute_watchlist_card_row — full SingleStockReport → card dict"
```

S4 done.

---

## Slice S5 — FastAPI server

**Goal:** Stand up `uw_scan.api.server:app` exposing all read endpoints (`/api/watchlist`, `/api/stock/{ticker}`, `/api/stock/{ticker}/runs[/{run_id}]`, `/api/ohlc/{ticker}`, `/api/health`), watchlist CRUD (`POST/DELETE/PATCH /api/watchlist[/{ticker}]`), and async-rescan endpoints (`POST /api/watchlist/{ticker}/rescan`, `GET /api/jobs/{job_id}`). All responses are Pydantic-modelled; OpenAPI schema auto-generated.

### Task S5.1 — App factory + health endpoint

**Files:**
- Create: `src/uw_scan/api/server.py`
- Create: `src/uw_scan/api/deps.py`
- Create: `src/uw_scan/api/routers/health.py`
- Create: `tests/integration/api/__init__.py` (empty)
- Create: `tests/integration/api/conftest.py`
- Create: `tests/integration/api/test_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/api/test_health.py
def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "db" in body
    assert "scheduler_lag_seconds" in body  # nullable when scheduler hasn't run yet
```

- [ ] **Step 2: Write `conftest.py` (shared FastAPI test fixture)**

```python
# tests/integration/api/conftest.py
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


# NOTE: these fixtures are also consumed by tests in tests/integration/worker/
# (e.g. test_full_scan.py, test_rescan_loop.py). Because pytest only auto-collects
# conftest.py upward from each test file's directory, define them in
# tests/integration/conftest.py — NOT in tests/integration/api/conftest.py —
# so both api/ and worker/ test dirs can use them. The block below shows the
# fixture bodies; copy them into tests/integration/conftest.py.

@pytest.fixture
def seeded_db_empty_cards():
    """Repository against a freshly-migrated TEST DB with the 54-ticker watchlist
    seeded but ZERO watchlist_card rows. Used to verify scan / refresh inserts.

    HARD REQUIREMENT: UW_SCAN_TEST_DB_NAME must be set (see tests/integration/
    storage/test_migrations.py `_test_settings` docstring). Refuses to run
    otherwise — never operates on the developer's working DB.
    """
    import os
    import subprocess
    from pathlib import Path
    import psycopg
    from uw_scan.config import Settings
    from uw_scan.storage.repository import Repository
    REPO_ROOT = Path(__file__).resolve().parents[3]
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to run a destructive fixture "
            "against the working DB.",
            pytrace=False,
        )
    settings = Settings.from_env().model_copy(update={"db_name": test_db})
    with psycopg.connect(settings.db_dsn(), autocommit=True) as c, c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE; CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(["bash", str(REPO_ROOT / "scripts/migrate.sh")],
                   check=True, cwd=REPO_ROOT, env=env)
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


@pytest.fixture
def seeded_db_with_cards(seeded_db_empty_cards):
    """Seeded DB + a fake scan_runs row + one watchlist_card row for TSLA.
    Used by tests that need to read cards back through the API."""
    repo = seeded_db_empty_cards
    from datetime import datetime, timezone
    from decimal import Decimal
    run_id = repo.start_scan_run(ticker="TSLA", scan_type="single_stock")
    repo.finish_scan_run(run_id, status="ok")
    repo.upsert_watchlist_card(
        ticker="TSLA", run_id=run_id,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("445.12"), iv_atm=Decimal("0.691"), iv_rank=Decimal("39.0"),
    )
    return repo
```

- [ ] **Step 3: Implement `deps.py` (DI helpers)**

```python
# src/uw_scan/api/deps.py
"""Dependency-injection helpers for FastAPI route handlers."""
from __future__ import annotations

from functools import lru_cache
from typing import Generator

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def get_repo() -> Generator[Repository, None, None]:
    settings = get_settings()
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()
```

- [ ] **Step 4: Implement health router**

```python
# src/uw_scan/api/routers/health.py
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from uw_scan.api.deps import get_repo
from uw_scan.storage.repository import Repository

router = APIRouter()


class HealthResponse(BaseModel):
    ok: bool
    db: str
    scheduler_lag_seconds: Optional[float] = None
    last_full_scan_at: Optional[datetime] = None


@router.get("/health", response_model=HealthResponse)
def health(repo: Repository = Depends(get_repo)) -> HealthResponse:
    db_status = "up"
    try:
        with repo.conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as e:  # noqa: BLE001
        return HealthResponse(ok=False, db=f"down: {e!r}")

    last_scan = repo.get_last_full_scan_finished_at()
    lag = (datetime.now(timezone.utc) - last_scan).total_seconds() if last_scan else None
    return HealthResponse(
        ok=True, db=db_status,
        scheduler_lag_seconds=lag, last_full_scan_at=last_scan,
    )
```

Add `Repository.get_last_full_scan_finished_at()`:

```python
    def get_last_full_scan_finished_at(self):
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(finished_at) FROM {self.schema}.scan_runs
                WHERE status='ok'
                """
            )
            row = cur.fetchone()
        return row[0] if row else None
```

(Verify the column is named `finished_at` and the status check matches existing pipeline writes — adjust if `repo.finish_scan_run` uses different column names.)

- [ ] **Step 5: Implement `server.py`**

```python
# src/uw_scan/api/server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uw_scan.api.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="UW Watchlist API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3001", "http://localhost:3001"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    return app


app = create_app()
```

- [ ] **Step 6: Run + verify pass**

Run: `uv run pytest tests/integration/api/test_health.py -v`
Expected: PASS.

- [ ] **Step 7: Smoke-boot the server**

Run (in another shell): `uv run uvicorn uw_scan.api.server:app --port 8400`
Verify: `curl http://127.0.0.1:8400/api/health` returns `{"ok":true,...}`. `curl http://127.0.0.1:8400/openapi.json | jq .info.title` returns `"UW Watchlist API"`.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/api/server.py src/uw_scan/api/deps.py \
        src/uw_scan/api/routers/health.py src/uw_scan/storage/repository.py \
        tests/integration/api/__init__.py tests/integration/api/conftest.py \
        tests/integration/api/test_health.py
git commit -m "feat(api): FastAPI app factory + /api/health endpoint"
```

### Task S5.2 — Response schemas (`schemas.py`)

**Files:**
- Create: `src/uw_scan/api/schemas.py`

- [ ] **Step 1: Define all over-the-wire response models**

```python
# src/uw_scan/api/schemas.py
"""Pydantic models for FastAPI responses. These are the public API contract;
keep them stable, and update openapi-typescript generation when they change."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class SetupBlock(BaseModel):
    type: Optional[str] = None
    direction: Optional[str] = None
    score: Optional[Decimal] = None


class ReturnsBlock(BaseModel):
    d1: Optional[Decimal] = Field(None, alias="ret_1d")
    w1: Optional[Decimal] = Field(None, alias="ret_1w")
    d30: Optional[Decimal] = Field(None, alias="ret_30d")

    model_config = {"populate_by_name": True}


class GammaBlock(BaseModel):
    flip_distance: Optional[Decimal] = None
    flip_price: Optional[Decimal] = None
    per_1pct_move: Optional[Decimal] = None
    max_strike: Optional[Decimal] = None
    expiring_pct: Optional[Decimal] = None
    expiring_date: Optional[date] = None


class SkewBlock(BaseModel):
    rr25d_30dte: Optional[Decimal] = None


class PositioningBlock(BaseModel):
    call_oi: Optional[int] = None
    put_oi: Optional[int] = None
    pcr_oi: Optional[Decimal] = None
    pcr_vol: Optional[Decimal] = None
    pcr_delta_30d: Optional[Decimal] = None


class WatchlistCard(BaseModel):
    ticker: str
    sector: str
    pinned: bool
    sort_rank: int

    spot: Optional[Decimal] = None
    spot_quoted_at: Optional[datetime] = None
    spot_source: Optional[str] = None
    scanned_at: datetime

    iv_atm: Optional[Decimal] = None
    iv_rank: Optional[Decimal] = None

    setup: SetupBlock
    aggression_pct: Optional[Decimal] = None
    returns: ReturnsBlock
    gamma: GammaBlock
    skew: SkewBlock
    positioning: PositioningBlock


class WatchlistResponse(BaseModel):
    scanned_at_min: Optional[datetime] = None
    scanned_at_max: Optional[datetime] = None
    scheduler_lag_seconds: Optional[float] = None
    tickers: list[WatchlistCard]


class WatchlistMutation(BaseModel):
    ticker: str
    sector: str
    notes: Optional[str] = None
    pinned: bool = False
    sort_rank: int = 0


class WatchlistPatch(BaseModel):
    sector: Optional[str] = None
    notes: Optional[str] = None
    pinned: Optional[bool] = None
    sort_rank: Optional[int] = None


class JobStatus(BaseModel):
    job_id: str
    status: str  # 'queued' | 'running' | 'done' | 'failed'
    run_id: Optional[int] = None
    error: Optional[str] = None
    requested_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class OhlcRow(BaseModel):
    date: date
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Decimal
    volume: Optional[int] = None
```

- [ ] **Step 2: Commit (no tests yet — they come with the router implementations)**

```bash
git add src/uw_scan/api/schemas.py
git commit -m "feat(api): Pydantic response schemas for over-the-wire API"
```

### Task S5.3 — Watchlist grid endpoint

**Files:**
- Create: `src/uw_scan/api/routers/watchlist.py`
- Modify: `src/uw_scan/api/server.py` (register router)
- Create: `tests/integration/api/test_watchlist_endpoint.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/api/test_watchlist_endpoint.py
import pytest


def test_get_watchlist_returns_empty_when_no_cards(client, seeded_db_empty_cards):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert body["tickers"] == []


def test_get_watchlist_returns_seeded_cards(client, seeded_db_with_cards):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tickers"]) >= 1
    card = body["tickers"][0]
    assert "ticker" in card and "sector" in card
    assert "setup" in card
    assert "returns" in card and "gamma" in card and "skew" in card and "positioning" in card
    assert card["scanned_at"] is not None


def test_get_watchlist_filters_by_sector(client, seeded_db_with_cards):
    r = client.get("/api/watchlist?sector=Technology")
    assert r.status_code == 200
    for card in r.json()["tickers"]:
        assert card["sector"] == "Technology"


def test_get_watchlist_filters_by_setup(client, seeded_db_with_cards):
    r = client.get("/api/watchlist?setup=C-bull")
    body = r.json()
    for card in body["tickers"]:
        assert card["setup"]["type"] == "C" and card["setup"]["direction"] == "bull"


def test_get_watchlist_filters_by_freshness(client, seeded_db_with_cards):
    r = client.get("/api/watchlist?fresh_within_minutes=60")
    assert r.status_code == 200
```

Add the `seeded_db_empty_cards` and `seeded_db_with_cards` fixtures to `conftest.py` — they should:

1. Run all migrations against a fresh test DB (use a separate schema or DB).
2. For `seeded_db_with_cards`, also insert a fake `scan_runs` row + a fake `watchlist_card` row for one or two seed tickers.

(Implementation detail of fixture: it depends on the conftest pattern already in `tests/integration/`. Reuse what's there if possible; otherwise add a `pytest.fixture(scope="session")` that wraps `scripts/migrate.sh`.)

- [ ] **Step 2: Implement the router**

```python
# src/uw_scan/api/routers/watchlist.py
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import (
    WatchlistResponse, WatchlistCard, SetupBlock, ReturnsBlock,
    GammaBlock, SkewBlock, PositioningBlock,
    WatchlistMutation, WatchlistPatch,
)
from uw_scan.storage.repository import Repository

router = APIRouter()


def _card_to_response(row, sector: str, pinned: bool, sort_rank: int) -> WatchlistCard:
    return WatchlistCard(
        ticker=row.ticker, sector=sector, pinned=pinned, sort_rank=sort_rank,
        spot=row.spot, spot_quoted_at=row.spot_quoted_at, spot_source=row.spot_source,
        scanned_at=row.scanned_at,
        iv_atm=row.iv_atm, iv_rank=row.iv_rank,
        setup=SetupBlock(type=row.setup_type, direction=row.setup_direction, score=row.setup_score),
        aggression_pct=row.aggression_pct,
        returns=ReturnsBlock(ret_1d=row.ret_1d, ret_1w=row.ret_1w, ret_30d=row.ret_30d),
        gamma=GammaBlock(
            flip_distance=row.gex_flip_distance, flip_price=row.gex_flip_price,
            per_1pct_move=row.gex_per_1pct_move, max_strike=row.max_gex_strike,
            expiring_pct=row.gex_expiring_pct, expiring_date=row.gex_expiring_date,
        ),
        skew=SkewBlock(rr25d_30dte=row.skew_25d_30dte),
        positioning=PositioningBlock(
            call_oi=row.call_oi_total, put_oi=row.put_oi_total,
            pcr_oi=row.pcr_oi, pcr_vol=row.pcr_vol, pcr_delta_30d=row.pcr_delta_30d,
        ),
    )


@router.get("/watchlist", response_model=WatchlistResponse)
def get_watchlist(
    sector: Optional[str] = Query(None),
    setup: Optional[str] = Query(None, description="e.g. 'C-bull', 'C-bear', 'F-MULTI', 'NEUTRAL'"),
    fresh_within_minutes: Optional[int] = Query(None, ge=1),
    repo: Repository = Depends(get_repo),
):
    rows = repo.list_watchlist_cards()
    out: list[WatchlistCard] = []
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=fresh_within_minutes)
        if fresh_within_minutes else None
    )
    setup_filter_type, setup_filter_dir = None, None
    if setup:
        if setup.upper() == "NEUTRAL":
            setup_filter_type = None
        elif "-" in setup:
            t, d = setup.split("-", 1)
            setup_filter_type, setup_filter_dir = t.upper(), d.lower()
        else:
            setup_filter_type = setup.upper()

    for r in rows:
        if sector and r.sector != sector:
            continue
        if cutoff and r.scanned_at < cutoff:
            continue
        if setup is not None:
            if setup.upper() == "NEUTRAL":
                if r.setup_type is not None:
                    continue
            else:
                if r.setup_type != setup_filter_type:
                    continue
                if setup_filter_dir and r.setup_direction != setup_filter_dir:
                    continue
        out.append(_card_to_response(r, r.sector, r.pinned, r.sort_rank))

    return WatchlistResponse(
        scanned_at_min=min((c.scanned_at for c in out), default=None),
        scanned_at_max=max((c.scanned_at for c in out), default=None),
        scheduler_lag_seconds=None,  # filled by /api/health
        tickers=out,
    )


@router.post("/watchlist", status_code=201)
def post_watchlist(body: WatchlistMutation, repo: Repository = Depends(get_repo)):
    repo.add_watchlist_ticker(
        ticker=body.ticker.upper(),
        sector=body.sector,
        notes=body.notes,
        sort_rank=body.sort_rank,
        pinned=body.pinned,
    )
    return {"ok": True, "ticker": body.ticker.upper()}


@router.delete("/watchlist/{ticker}", status_code=204)
def delete_watchlist(ticker: str, repo: Repository = Depends(get_repo)):
    repo.soft_delete_watchlist_ticker(ticker.upper())


@router.patch("/watchlist/{ticker}")
def patch_watchlist(ticker: str, body: WatchlistPatch, repo: Repository = Depends(get_repo)):
    repo.patch_watchlist_ticker(
        ticker.upper(),
        sector=body.sector, notes=body.notes,
        pinned=body.pinned, sort_rank=body.sort_rank,
    )
    return {"ok": True, "ticker": ticker.upper()}
```

- [ ] **Step 3: Register the router**

In `server.py`:

```python
from uw_scan.api.routers import health, watchlist

def create_app() -> FastAPI:
    # ...
    app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
```

- [ ] **Step 4: Run + verify pass**

Run: `uv run pytest tests/integration/api/test_watchlist_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/routers/watchlist.py src/uw_scan/api/server.py \
        tests/integration/api/test_watchlist_endpoint.py
git commit -m "feat(api): /api/watchlist GET + POST/DELETE/PATCH CRUD"
```

### Task S5.4 — Stock detail endpoint

**Files:**
- Create: `src/uw_scan/api/routers/stock.py`
- Modify: `src/uw_scan/api/server.py`
- Create: `tests/integration/api/test_stock_endpoint.py`

- [ ] **Step 1: Failing test**

```python
def test_get_stock_returns_latest_report(client, seeded_db_with_cards):
    r = client.get("/api/stock/TSLA")
    if r.status_code == 404:
        pytest.skip("TSLA not seeded in test DB")
    body = r.json()
    assert body["ticker"] == "TSLA"
    assert "market_structure" in body
    assert "volatility" in body
    assert "flow" in body
    assert "strike_gex_curve" in body


def test_get_stock_404_for_unknown_ticker(client):
    r = client.get("/api/stock/ZZZZZZ")
    assert r.status_code == 404


def test_get_stock_runs_returns_history(client, seeded_db_with_cards):
    r = client.get("/api/stock/TSLA/runs")
    if r.status_code == 404:
        pytest.skip("TSLA not seeded")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    for entry in body:
        assert "run_id" in entry and "scanned_at" in entry


def test_get_specific_run(client, seeded_db_with_cards, latest_tsla_run_id):
    r = client.get(f"/api/stock/TSLA/runs/{latest_tsla_run_id}")
    assert r.status_code == 200
    assert r.json()["run_id"] == latest_tsla_run_id
```

Add fixtures for `latest_tsla_run_id` to `conftest.py`.

- [ ] **Step 2: Implement router**

```python
# src/uw_scan/api/routers/stock.py
from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import SingleStockReport
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/stock/{ticker}", response_model=SingleStockReport)
def get_stock(ticker: str, repo: Repository = Depends(get_repo)) -> SingleStockReport:
    ticker = ticker.upper()
    run_id = repo.latest_run_id(ticker)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {ticker}")
    return assemble_single_stock_report(ticker, run_id, repo)


@router.get("/stock/{ticker}/runs")
def list_runs(ticker: str, repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_runs_for_ticker(ticker.upper(), limit=50)


@router.get("/stock/{ticker}/runs/{run_id}", response_model=SingleStockReport)
def get_specific_run(ticker: str, run_id: int, repo: Repository = Depends(get_repo)) -> SingleStockReport:
    return assemble_single_stock_report(ticker.upper(), run_id, repo)
```

Add `Repository.list_runs_for_ticker(ticker, limit)` returning `[{"run_id": int, "scanned_at": datetime, "status": str}, ...]`.

- [ ] **Step 3: Register and run**

Register in `server.py`, run `uv run pytest tests/integration/api/test_stock_endpoint.py -v`. Expect PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/api/routers/stock.py src/uw_scan/api/server.py \
        src/uw_scan/storage/repository.py \
        tests/integration/api/test_stock_endpoint.py
git commit -m "feat(api): /api/stock/{ticker} + /runs[/{run_id}]"
```

### Task S5.5 — OHLC endpoint

**Files:**
- Create: `src/uw_scan/api/routers/ohlc.py`
- Modify: `src/uw_scan/api/server.py`
- Create: `tests/integration/api/test_ohlc_endpoint.py`

- [ ] **Step 1: Failing test**

```python
def test_get_ohlc_returns_recent_bars(client, seeded_db_with_ohlc):
    r = client.get("/api/ohlc/AAPL?days=10")
    assert r.status_code == 200
    bars = r.json()
    assert isinstance(bars, list)
    assert all("date" in b and "close" in b for b in bars)
    assert len(bars) <= 10


def test_get_ohlc_default_30_days(client, seeded_db_with_ohlc):
    r = client.get("/api/ohlc/AAPL")
    assert r.status_code == 200
    assert len(r.json()) <= 30
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/api/routers/ohlc.py
from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import OhlcRow
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/ohlc/{ticker}", response_model=list[OhlcRow])
def get_ohlc(ticker: str, days: int = Query(30, ge=1, le=365),
             repo: Repository = Depends(get_repo)) -> list[OhlcRow]:
    rows = repo.list_daily_ohlc(ticker.upper(), limit=days)
    return [
        OhlcRow(date=r.date, open=r.open, high=r.high, low=r.low,
                close=r.close, volume=r.volume)
        for r in rows
    ]
```

- [ ] **Step 3: Run + commit**

```bash
git add src/uw_scan/api/routers/ohlc.py src/uw_scan/api/server.py \
        tests/integration/api/test_ohlc_endpoint.py
git commit -m "feat(api): /api/ohlc/{ticker} returns daily bars"
```

### Task S5.6 — Rescan + jobs endpoints

**Files:**
- Create: `src/uw_scan/api/routers/jobs.py`
- Modify: `src/uw_scan/api/server.py`
- Create: `tests/integration/api/test_jobs_endpoint.py`

- [ ] **Step 1: Failing test**

```python
def test_post_rescan_enqueues_job(client, seeded_db_with_cards):
    r = client.post("/api/watchlist/TSLA/rescan")
    assert r.status_code == 202  # accepted
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_get_job_status(client, seeded_db_with_cards):
    enqueued = client.post("/api/watchlist/TSLA/rescan").json()
    r = client.get(f"/api/jobs/{enqueued['job_id']}")
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "running", "done")


def test_get_unknown_job_404(client):
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/api/routers/jobs.py
from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import JobStatus
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.post("/watchlist/{ticker}/rescan", status_code=202, response_model=JobStatus)
def enqueue_rescan(ticker: str, repo: Repository = Depends(get_repo)) -> JobStatus:
    job_id = repo.enqueue_rescan_job(ticker.upper())
    job = repo.get_job(job_id)
    return JobStatus(
        job_id=job.id, status=job.status, run_id=job.run_id, error=job.error,
        requested_at=job.requested_at, started_at=job.started_at, finished_at=job.finished_at,
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, repo: Repository = Depends(get_repo)) -> JobStatus:
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatus(
        job_id=job.id, status=job.status, run_id=job.run_id, error=job.error,
        requested_at=job.requested_at, started_at=job.started_at, finished_at=job.finished_at,
    )
```

- [ ] **Step 3: Run + commit**

```bash
git add src/uw_scan/api/routers/jobs.py src/uw_scan/api/server.py \
        tests/integration/api/test_jobs_endpoint.py
git commit -m "feat(api): POST /watchlist/{t}/rescan + GET /jobs/{id}"
```

### Task S5.7 — OpenAPI snapshot test

**Files:**
- Create: `tests/integration/api/openapi.snapshot.json` (generated)
- Create: `tests/integration/api/test_openapi_snapshot.py`

- [ ] **Step 1: Capture the initial snapshot**

Run: `uv run python -c "import json; from uw_scan.api.server import app; print(json.dumps(app.openapi(), indent=2))" > tests/integration/api/openapi.snapshot.json`

- [ ] **Step 2: Write the test that compares against the snapshot**

```python
# tests/integration/api/test_openapi_snapshot.py
import json
from pathlib import Path

SNAP = Path(__file__).resolve().parent / "openapi.snapshot.json"


def test_openapi_schema_matches_snapshot(client):
    current = client.get("/openapi.json").json()
    expected = json.loads(SNAP.read_text())
    # Compare paths + their methods. The full schema includes ephemeral fields
    # (FastAPI's version banner), so we narrow to the stable subset.
    assert sorted(current["paths"].keys()) == sorted(expected["paths"].keys()), \
        "OpenAPI paths changed — update tests/integration/api/openapi.snapshot.json " \
        "if the change is intentional."
    for path, methods in expected["paths"].items():
        for method in methods:
            assert method in current["paths"][path], \
                f"Method {method.upper()} {path} removed from OpenAPI"
```

- [ ] **Step 3: Run + commit**

```bash
git add tests/integration/api/test_openapi_snapshot.py \
        tests/integration/api/openapi.snapshot.json
git commit -m "test(api): OpenAPI schema snapshot guards public contract"
```

S5 done.

---

## Slice S6 — Worker / scheduler

**Goal:** APScheduler running in a dedicated process (`python -m uw_scan.worker.scheduler`) with three configurable jobs (spot refresh / full scan / OHLC pull) plus a 1-second ad-hoc rescan loop reading the `jobs` table. Configurable via env-var cron expressions.

### Task S6.1 — Spot refresh job

**Files:**
- Create: `src/uw_scan/worker/jobs/spot_refresh.py`
- Create: `tests/integration/worker/__init__.py` (empty)
- Create: `tests/integration/worker/test_spot_refresh.py`

- [ ] **Step 1: Failing test**

```python
"""spot_refresh_job updates intraday_quote rows and recomputes spot-derived
fields on every active watchlist_card row."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
def test_spot_refresh_updates_quotes_and_card(seeded_db_with_cards):
    from uw_scan.worker.jobs.spot_refresh import spot_refresh_once
    from uw_scan.sources.ohlc import IntradayQuote

    fake_provider = MagicMock()
    fake_provider.fetch_intraday_quote.side_effect = lambda t: IntradayQuote(
        ticker=t, price=Decimal("999.99"),
        quoted_at=datetime(2026, 5, 8, 13, 0, tzinfo=timezone.utc),
    )

    n_updated = spot_refresh_once(seeded_db_with_cards, fake_provider)
    assert n_updated >= 1

    # Verify intraday_quote rows landed
    q = seeded_db_with_cards.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("999.99")

    # Verify spot field on watchlist_card now reflects new price
    card = seeded_db_with_cards.get_watchlist_card("TSLA")
    assert card.spot == Decimal("999.99")
    assert card.spot_source == "massive.com_intraday"
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/worker/jobs/spot_refresh.py
"""Spot-refresh job: fetch massive.com intraday quote for every active ticker
and update the spot-derived fields on watchlist_card."""
from __future__ import annotations

import logging
from decimal import Decimal

from uw_scan.cards.returns import compute_returns
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def spot_refresh_once(repo, provider: OhlcProvider) -> int:
    """Run one pass over every active watchlist ticker.

    Returns the number of cards updated.
    """
    updated = 0
    for w in repo.list_active_watchlist():
        try:
            quote = provider.fetch_intraday_quote(w.ticker)
            if quote is None:
                continue
            repo.upsert_intraday_quote(w.ticker, quote.price, quote.quoted_at)
            # Recompute spot-derived card fields
            history = repo.list_daily_ohlc(w.ticker, limit=40)
            returns = compute_returns(history, quote.price)
            existing = repo.get_watchlist_card(w.ticker)
            if existing is None:
                # No full scan yet — only the spot is meaningful; write a partial row.
                continue
            # net_gex is needed for gex_per_1pct_move recomputation
            run = repo.get_single_stock_run(existing.run_id)  # fetch the report's market_structure
            net_gex = run.net_gex if run else None
            per_1pct = (
                net_gex * Decimal("0.01") * quote.price
                if net_gex is not None else None
            )
            flip_price = existing.gex_flip_price
            flip_distance = (
                (flip_price - quote.price) / quote.price
                if flip_price is not None else None
            )
            repo.upsert_watchlist_card(
                ticker=w.ticker,
                run_id=existing.run_id,
                scanned_at=existing.scanned_at,
                spot=quote.price,
                spot_quoted_at=quote.quoted_at,
                spot_source="massive.com_intraday",
                ret_1d=returns.ret_1d,
                ret_1w=returns.ret_1w,
                ret_30d=returns.ret_30d,
                gex_per_1pct_move=per_1pct,
                gex_flip_distance=flip_distance,
            )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("spot_refresh failed for %s: %s", w.ticker, repr(exc))
    return updated
```

(Add `Repository.get_single_stock_run(run_id)` — minimal: returns an object with `.net_gex` attribute pulled from the persisted `market_structure`.)

- [ ] **Step 3: Run + verify**

Run: `uv run pytest tests/integration/worker/test_spot_refresh.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/worker/jobs/spot_refresh.py \
        src/uw_scan/storage/repository.py \
        tests/integration/worker/__init__.py \
        tests/integration/worker/test_spot_refresh.py
git commit -m "feat(worker): spot refresh job — intraday quote + recompute spot-derived fields"
```

### Task S6.2 — Full scan job

**Files:**
- Create: `src/uw_scan/worker/jobs/full_scan.py`
- Create: `tests/integration/worker/test_full_scan.py`

- [ ] **Step 1: Failing test**

```python
"""full_scan_once runs run_single_stock for every active watchlist ticker
and updates the watchlist_card row from the resulting report."""
from unittest.mock import MagicMock, patch
import pytest


@pytest.mark.integration
def test_full_scan_writes_card_per_ticker(seeded_db_empty_cards):
    from uw_scan.worker.jobs.full_scan import full_scan_once

    fake_uw = MagicMock()
    fake_ohlc = MagicMock()

    # The test should rely on a stub run_single_stock that returns a minimal
    # SingleStockReport with a populated MarketAggregates and strike_gex_curve;
    # we don't need a live UW API call for this assertion.

    with patch("uw_scan.worker.jobs.full_scan.run_single_stock") as mock_rss:
        from uw_scan.models import SingleStockReport, MarketStructure, VolatilityProfile, FlowSnapshot, VRPAssessment
        from datetime import datetime, timezone
        from decimal import Decimal

        mock_rss.return_value = SingleStockReport(
            run_id=99, ticker="TSLA", generated_at=datetime.now(timezone.utc),
            market_structure=MarketStructure(spot=Decimal("445")),
            volatility=VolatilityProfile(iv=Decimal("0.5")),
            flow=FlowSnapshot(ticker="TSLA", flow_count=0,
                              net_premium=Decimal("0"), bull_premium=Decimal("0"),
                              bear_premium=Decimal("0"),
                              ask_side_premium=Decimal("0"), bid_side_premium=Decimal("0")),
            vrp=VRPAssessment(vrp=None, signal="—", note=""),
        )
        n = full_scan_once(seeded_db_empty_cards, fake_uw, fake_ohlc)
    assert n >= 1
    card = seeded_db_empty_cards.get_watchlist_card("TSLA")
    assert card is not None
    assert card.spot == Decimal("445")
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/worker/jobs/full_scan.py
"""Full-scan job: per-ticker run_single_stock + watchlist_card upsert."""
from __future__ import annotations

import logging

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.pipeline import run_single_stock
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def full_scan_once(repo, uw_client, ohlc_provider: OhlcProvider) -> int:
    """Run a full UW scan across the active watchlist and rebuild card rows."""
    completed = 0
    for w in repo.list_active_watchlist():
        try:
            report = run_single_stock(w.ticker, uw_client, repo)
            history = repo.list_daily_ohlc(w.ticker, limit=40)
            intraday = repo.get_intraday_quote(w.ticker)
            prior_pcr = repo.get_pcr_history_30d_ago(w.ticker, today=report.generated_at.date())
            card_row = compute_watchlist_card_row(report, history, intraday, prior_pcr)
            repo.upsert_watchlist_card(**card_row)
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("full_scan failed for %s: %s", w.ticker, repr(exc))
    return completed
```

- [ ] **Step 3: Run + commit**

```bash
git add src/uw_scan/worker/jobs/full_scan.py \
        tests/integration/worker/test_full_scan.py
git commit -m "feat(worker): full scan job — UW deep-scan + card upsert"
```

### Task S6.3 — Daily OHLC pull job

**Files:**
- Create: `src/uw_scan/worker/jobs/ohlc_pull.py`
- Create: `tests/integration/worker/test_ohlc_pull.py`

- [ ] **Step 1: Test**

```python
@pytest.mark.integration
def test_ohlc_pull_writes_daily_rows(seeded_db_empty_cards):
    from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
    from uw_scan.sources.ohlc import OhlcBar
    from datetime import date, timedelta
    from decimal import Decimal
    from unittest.mock import MagicMock

    today = date(2026, 5, 8)
    fake_provider = MagicMock()
    fake_provider.fetch_daily.side_effect = lambda t, start, end: [
        OhlcBar(ticker=t, date=today - timedelta(days=i),
                open=None, high=None, low=None,
                close=Decimal(str(100 + i)), volume=10_000)
        for i in range(30)
    ]
    n = ohlc_pull_once(seeded_db_empty_cards, fake_provider, lookback_days=30)
    assert n >= 1
    rows = seeded_db_empty_cards.list_daily_ohlc("TSLA", limit=10)
    assert len(rows) >= 1
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/worker/jobs/ohlc_pull.py
"""Daily OHLC pull: for every watchlist ticker, fetch the last N trading days
from the OHLC provider and upsert into uw_scan.daily_ohlc."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def ohlc_pull_once(repo, provider: OhlcProvider, lookback_days: int = 40) -> int:
    completed = 0
    end = date.today()
    start = end - timedelta(days=lookback_days * 2)  # buffer for weekends/holidays
    for w in repo.list_active_watchlist():
        try:
            bars = provider.fetch_daily(w.ticker, start, end)
            for bar in bars:
                repo.upsert_daily_ohlc(
                    ticker=bar.ticker, date=bar.date,
                    open=bar.open, high=bar.high, low=bar.low,
                    close=bar.close, volume=bar.volume,
                    source="massive.com",
                )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("ohlc_pull failed for %s: %s", w.ticker, repr(exc))
    return completed
```

- [ ] **Step 3: Run + commit**

```bash
git add src/uw_scan/worker/jobs/ohlc_pull.py \
        tests/integration/worker/test_ohlc_pull.py
git commit -m "feat(worker): daily OHLC pull job — massive.com → daily_ohlc"
```

### Task S6.4 — Ad-hoc rescan loop

**Files:**
- Create: `src/uw_scan/worker/jobs/rescan_loop.py`
- Create: `tests/integration/worker/test_rescan_loop.py`

- [ ] **Step 1: Test**

```python
@pytest.mark.integration
def test_rescan_loop_claims_and_completes_job(seeded_db_with_cards):
    from uw_scan.worker.jobs.rescan_loop import rescan_tick
    from unittest.mock import MagicMock, patch
    from uw_scan.models import SingleStockReport, MarketStructure, VolatilityProfile, FlowSnapshot, VRPAssessment
    from datetime import datetime, timezone
    from decimal import Decimal

    job_id = seeded_db_with_cards.enqueue_rescan_job("TSLA")

    with patch("uw_scan.worker.jobs.rescan_loop.run_single_stock") as mock_rss:
        mock_rss.return_value = SingleStockReport(
            run_id=123, ticker="TSLA", generated_at=datetime.now(timezone.utc),
            market_structure=MarketStructure(spot=Decimal("500")),
            volatility=VolatilityProfile(),
            flow=FlowSnapshot(ticker="TSLA", flow_count=0,
                              net_premium=Decimal("0"), bull_premium=Decimal("0"),
                              bear_premium=Decimal("0"),
                              ask_side_premium=Decimal("0"), bid_side_premium=Decimal("0")),
            vrp=VRPAssessment(vrp=None, signal="—", note=""),
        )
        worked = rescan_tick(seeded_db_with_cards, MagicMock(), MagicMock())
    assert worked is True

    job = seeded_db_with_cards.get_job(job_id)
    assert job.status == "done"
    assert job.run_id == 123


@pytest.mark.integration
def test_rescan_tick_returns_false_when_no_queued(seeded_db_with_cards):
    from uw_scan.worker.jobs.rescan_loop import rescan_tick
    from unittest.mock import MagicMock
    # Ensure no queued jobs (test isolation)
    assert rescan_tick(seeded_db_with_cards, MagicMock(), MagicMock()) is False
```

- [ ] **Step 2: Implement**

```python
# src/uw_scan/worker/jobs/rescan_loop.py
"""Ad-hoc rescan loop: claim one queued job from uw_scan.jobs, run it, mark done/failed."""
from __future__ import annotations

import logging

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.pipeline import run_single_stock
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def rescan_tick(repo, uw_client, ohlc_provider: OhlcProvider) -> bool:
    """Process one queued rescan. Returns True if a job ran, False if the queue was empty."""
    job = repo.claim_next_queued_job()
    if job is None:
        return False
    try:
        report = run_single_stock(job.ticker, uw_client, repo)
        history = repo.list_daily_ohlc(job.ticker, limit=40)
        intraday = repo.get_intraday_quote(job.ticker)
        prior_pcr = repo.get_pcr_history_30d_ago(job.ticker, today=report.generated_at.date())
        card_row = compute_watchlist_card_row(report, history, intraday, prior_pcr)
        repo.upsert_watchlist_card(**card_row)
        repo.mark_job_done(job.id, report.run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("rescan job %s failed: %s", job.id, repr(exc))
        repo.mark_job_failed(job.id, repr(exc))
        return True
```

- [ ] **Step 3: Run + commit**

```bash
git add src/uw_scan/worker/jobs/rescan_loop.py \
        tests/integration/worker/test_rescan_loop.py
git commit -m "feat(worker): ad-hoc rescan tick — claim job, scan, mark done/failed"
```

### Task S6.5 — Scheduler entry point

**Files:**
- Create: `src/uw_scan/worker/scheduler.py`

- [ ] **Step 1: Implement the scheduler driver**

```python
# src/uw_scan/worker/scheduler.py
"""APScheduler driver: registers the three cron jobs and the ad-hoc rescan poll."""
from __future__ import annotations

import logging
import signal
import sys

import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.full_scan import full_scan_once
from uw_scan.worker.jobs.ohlc_pull import ohlc_pull_once
from uw_scan.worker.jobs.rescan_loop import rescan_tick
from uw_scan.worker.jobs.spot_refresh import spot_refresh_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("uw_scan.worker")


def _with_repo(settings: Settings):
    """Yield a fresh Repository per job tick — short-lived connection avoids stale state."""
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


def _make_uw_client(settings: Settings) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )


def _make_ohlc_provider(settings: Settings) -> MassiveOhlcProvider | None:
    if settings.massive_api_key is None:
        logger.warning("MASSIVE_API_KEY not set; OHLC jobs will be no-ops")
        return None
    return MassiveOhlcProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
    )


def main() -> int:
    settings = Settings.from_env()
    sched = BlockingScheduler(timezone=settings.rth_tz)

    # ---- Spot refresh
    def _spot_refresh():
        provider = _make_ohlc_provider(settings)
        if provider is None:
            return
        for repo in _with_repo(settings):
            try:
                n = spot_refresh_once(repo, provider)
                logger.info("spot_refresh updated %d cards", n)
            finally:
                provider.close()
    sched.add_job(
        _spot_refresh,
        IntervalTrigger(seconds=settings.spot_refresh_seconds),
        id="spot_refresh", name="Spot refresh",
    )

    # ---- Full scan
    def _full_scan():
        with _make_uw_client(settings) as uw, (_make_ohlc_provider(settings) or _NoOhlc()) as ohlc:
            for repo in _with_repo(settings):
                n = full_scan_once(repo, uw, ohlc)
                logger.info("full_scan completed %d tickers", n)
    sched.add_job(
        _full_scan,
        CronTrigger.from_crontab(settings.full_scan_cron, timezone=settings.rth_tz),
        id="full_scan", name="Full UW scan",
    )

    # ---- Daily OHLC pull
    def _ohlc_pull():
        provider = _make_ohlc_provider(settings)
        if provider is None:
            return
        with provider:
            for repo in _with_repo(settings):
                n = ohlc_pull_once(repo, provider)
                logger.info("ohlc_pull refreshed %d tickers", n)
    sched.add_job(
        _ohlc_pull,
        CronTrigger.from_crontab(settings.ohlc_pull_cron, timezone=settings.rth_tz),
        id="ohlc_pull", name="Daily OHLC pull",
    )

    # ---- Rescan loop
    def _rescan_tick():
        with _make_uw_client(settings) as uw, (_make_ohlc_provider(settings) or _NoOhlc()) as ohlc:
            for repo in _with_repo(settings):
                rescan_tick(repo, uw, ohlc)
    sched.add_job(
        _rescan_tick,
        IntervalTrigger(seconds=1),
        id="rescan_tick", name="Ad-hoc rescan poll",
    )

    # Clean shutdown
    def _stop(_sig, _frame):
        logger.info("received signal, shutting down scheduler")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("scheduler started")
    sched.start()
    return 0


class _NoOhlc:
    """Null-object OhlcProvider for runs without a Massive key — methods return None."""
    def fetch_daily(self, *_a, **_k): return []
    def fetch_intraday_quote(self, *_a, **_k): return None
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def close(self): pass


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add `tzdata` is already in pyproject (S0.4). Verify the cron expression parses**

Run: `uv run python -c "from apscheduler.triggers.cron import CronTrigger; CronTrigger.from_crontab('*/60 9-16 * * 1-5', timezone='America/New_York')"`
Expected: no error.

- [ ] **Step 3: Smoke-boot the scheduler for ~5 seconds, then SIGTERM**

```bash
timeout 5 uv run python -m uw_scan.worker.scheduler || true
```

Expected: log lines `scheduler started`, then `received signal, shutting down scheduler`. Exit code 0 (or 124 for the timeout).

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/worker/scheduler.py
git commit -m "feat(worker): APScheduler driver with three cron jobs + rescan poll"
```

S6 done. Backend is feature-complete.

---

## Slice S7 — Frontend foundation

**Goal:** Generate TypeScript types from FastAPI's OpenAPI schema, set up shared `lib/api.ts` and formatters, and verify the build chain. The Next.js scaffold already exists from S0.

### Task S7.1 — Generate `lib/types.ts` from FastAPI OpenAPI

**Files:**
- Create: `web/lib/types.ts`
- Modify: `web/package.json` (the `gen:types` script already exists from S0.6)

- [ ] **Step 1: Boot FastAPI and run the codegen**

```bash
# In one shell:
uv run uvicorn uw_scan.api.server:app --port 8400 &
SERVER_PID=$!
sleep 2

cd web
npm run gen:types  # → curls http://127.0.0.1:8400/openapi.json into lib/types.ts

kill $SERVER_PID
cd ..
```

- [ ] **Step 2: Verify the generated file compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): generate types.ts from FastAPI OpenAPI schema"
```

### Task S7.2 — `lib/api.ts` typed fetch wrapper

**Files:**
- Create: `web/lib/api.ts`
- Create: `web/lib/formatters.ts`
- Create: `web/lib/freshness.ts`
- Create: `web/tests/unit/formatters.test.ts`
- Create: `web/tests/unit/freshness.test.ts`
- Create: `web/vitest.config.ts`

- [ ] **Step 1: Vitest config**

```typescript
// web/vitest.config.ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: { "@": "." },
  },
});
```

- [ ] **Step 2: Formatters with unit tests (TDD)**

`web/tests/unit/formatters.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { fmtPct, fmtMoney, fmtSigned, fmtDecimal } from "@/lib/formatters";

describe("fmtPct", () => {
  it("formats decimal percent", () => {
    expect(fmtPct(0.293)).toBe("29.3%");
    expect(fmtPct(-0.044)).toBe("-4.4%");
  });
  it("renders em-dash for null", () => {
    expect(fmtPct(null)).toBe("—");
  });
});

describe("fmtMoney", () => {
  it("formats large numbers with commas, no decimals", () => {
    expect(fmtMoney(91_000_000)).toBe("$91,000,000");
  });
  it("handles negative", () => {
    expect(fmtMoney(-50_000_000)).toBe("-$50,000,000");
  });
});

describe("fmtSigned", () => {
  it("prefixes positive with +", () => {
    expect(fmtSigned(0.05, 2)).toBe("+0.05");
    expect(fmtSigned(-0.05, 2)).toBe("-0.05");
  });
});

describe("fmtDecimal", () => {
  it("formats with configurable digits", () => {
    expect(fmtDecimal(81256, 0)).toBe("81,256");
    expect(fmtDecimal(0.691, 4)).toBe("0.6910");
  });
});
```

- [ ] **Step 3: Implement formatters**

```typescript
// web/lib/formatters.ts
export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

export function fmtMoney(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const fmt = abs.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return v < 0 ? `-$${fmt}` : `$${fmt}`;
}

export function fmtDecimal(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * Coerce an unknown API value to `number | null` *preserving zero*.
 * `Number(x) || null` is wrong: it converts a legitimate 0 (zero return,
 * zero aggression, flat skew, etc.) into `null`, which the UI then
 * renders as a missing value instead of "0".
 */
export function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}
```

- [ ] **Step 4: Freshness helper with tests**

`web/tests/unit/freshness.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { bucketFreshness } from "@/lib/freshness";

describe("bucketFreshness", () => {
  const now = new Date("2026-05-12T14:00:00Z");
  it("fresh within 60 min", () => {
    expect(bucketFreshness("2026-05-12T13:55:00Z", now)).toBe("fresh");
  });
  it("stale between 60 and 180 min", () => {
    expect(bucketFreshness("2026-05-12T12:00:00Z", now)).toBe("stale");
  });
  it("dead beyond 180 min", () => {
    expect(bucketFreshness("2026-05-12T05:00:00Z", now)).toBe("dead");
  });
  it("treats nulls as dead", () => {
    expect(bucketFreshness(null, now)).toBe("dead");
  });
});
```

```typescript
// web/lib/freshness.ts
export type Freshness = "fresh" | "stale" | "dead";

export function bucketFreshness(
  scannedAt: string | null | undefined,
  now: Date = new Date()
): Freshness {
  if (!scannedAt) return "dead";
  const t = new Date(scannedAt).getTime();
  if (Number.isNaN(t)) return "dead";
  const ageMin = (now.getTime() - t) / 60_000;
  if (ageMin < 60) return "fresh";
  if (ageMin < 180) return "stale";
  return "dead";
}
```

- [ ] **Step 5: API wrapper**

```typescript
// web/lib/api.ts
import type { components, paths } from "./types";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400";

type WatchlistResponse =
  paths["/api/watchlist"]["get"]["responses"]["200"]["content"]["application/json"];

type SingleStockReport =
  paths["/api/stock/{ticker}"]["get"]["responses"]["200"]["content"]["application/json"];

type JobStatus =
  paths["/api/jobs/{job_id}"]["get"]["responses"]["200"]["content"]["application/json"];

async function _fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    throw new Error(`API ${r.status} for ${path}: ${await r.text()}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  watchlist: async (params: URLSearchParams = new URLSearchParams()): Promise<WatchlistResponse> => {
    const q = params.toString();
    return _fetch<WatchlistResponse>(`/api/watchlist${q ? `?${q}` : ""}`);
  },
  stock: async (ticker: string): Promise<SingleStockReport> =>
    _fetch<SingleStockReport>(`/api/stock/${ticker}`),
  ohlc: async (ticker: string, days = 30) =>
    _fetch(`/api/ohlc/${ticker}?days=${days}`),
  rescan: async (ticker: string): Promise<JobStatus> =>
    _fetch<JobStatus>(`/api/watchlist/${ticker}/rescan`, { method: "POST" }),
  job: async (jobId: string): Promise<JobStatus> =>
    _fetch<JobStatus>(`/api/jobs/${jobId}`),
  addTicker: async (body: { ticker: string; sector: string; notes?: string }) =>
    _fetch(`/api/watchlist`, { method: "POST", body: JSON.stringify(body) }),
  removeTicker: async (ticker: string) =>
    _fetch(`/api/watchlist/${ticker}`, { method: "DELETE" }),
  patchTicker: async (ticker: string, body: Partial<{ sector: string; notes: string; pinned: boolean; sort_rank: number }>) =>
    _fetch(`/api/watchlist/${ticker}`, { method: "PATCH", body: JSON.stringify(body) }),
};
```

- [ ] **Step 6: Run tests**

```bash
cd web && npx vitest run
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/lib/api.ts web/lib/formatters.ts web/lib/freshness.ts \
        web/tests/unit/formatters.test.ts web/tests/unit/freshness.test.ts \
        web/vitest.config.ts
git commit -m "feat(web): lib/api.ts + formatters + freshness with unit tests"
```

S7 done.

---

## Slice S8 — Watchlist landing page

**Goal:** `/watchlist` server component that fetches `/api/watchlist`, groups by sector, renders a placeholder `TickerCard` per row. Filter chips encoded in URL search params. Sub-components from S9 will fill in card visuals.

### Task S8.1 — Loading skeleton + page shell

**Files:**
- Create: `web/app/watchlist/page.tsx`
- Create: `web/app/watchlist/loading.tsx`
- Create: `web/components/watchlist/CardGrid.tsx`
- Create: `web/components/watchlist/TickerCard.tsx` (skeleton — frame only)
- Create: `web/components/watchlist/FilterBar.tsx`

- [ ] **Step 1: `web/app/watchlist/page.tsx`** (server component)

```tsx
import { api } from "@/lib/api";
import { CardGrid } from "@/components/watchlist/CardGrid";
import { FilterBar } from "@/components/watchlist/FilterBar";

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  if (sp.sector) qs.set("sector", sp.sector);
  if (sp.setup) qs.set("setup", sp.setup);
  if (sp.fresh) qs.set("fresh_within_minutes", sp.fresh);
  const data = await api.watchlist(qs);

  return (
    <main style={{ padding: "24px", maxWidth: 1600, margin: "0 auto" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
        <h1 style={{ fontFamily: "var(--font-mono)", fontSize: 24, letterSpacing: 1 }}>
          WATCHLIST
        </h1>
        <span style={{ color: "var(--text-muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {data.scheduler_lag_seconds != null
            ? `scheduler: ${Math.round(data.scheduler_lag_seconds)}s lag`
            : "scheduler: unknown"}
        </span>
      </header>
      <FilterBar current={sp} />
      <CardGrid data={data} />
    </main>
  );
}
```

- [ ] **Step 2: Loading skeleton**

```tsx
// web/app/watchlist/loading.tsx
export default function Loading() {
  return (
    <main style={{ padding: 24, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
      Loading watchlist…
    </main>
  );
}
```

- [ ] **Step 3: `CardGrid` (client component for filter interactions)**

```tsx
// web/components/watchlist/CardGrid.tsx
"use client";
import { TickerCard } from "./TickerCard";

type Props = {
  data: {
    tickers: Array<{
      ticker: string;
      sector: string;
      pinned: boolean;
      scanned_at: string;
      // ... full WatchlistCard shape from types.ts; expand once S9 lands
      [k: string]: unknown;
    }>;
  };
};

export function CardGrid({ data }: Props) {
  // Group by sector
  const grouped = new Map<string, typeof data.tickers>();
  for (const t of data.tickers) {
    const arr = grouped.get(t.sector) ?? [];
    arr.push(t);
    grouped.set(t.sector, arr);
  }
  // Pinned float to top within each group
  for (const arr of grouped.values()) {
    arr.sort((a, b) => Number(b.pinned) - Number(a.pinned));
  }

  return (
    <div>
      {[...grouped.entries()].map(([sector, tickers]) => (
        <section key={sector} style={{ marginBottom: 28 }}>
          <h2 style={{
            fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: 1.5,
            color: "var(--text-secondary)", textTransform: "uppercase",
            marginBottom: 8, paddingBottom: 4, borderBottom: "1px solid var(--border-dim)",
          }}>
            {sector} · {tickers.length}
          </h2>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12,
          }}>
            {tickers.map(t => <TickerCard key={t.ticker} card={t} />)}
          </div>
        </section>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Skeleton `TickerCard` (full visuals come in S9)**

```tsx
// web/components/watchlist/TickerCard.tsx
"use client";
import Link from "next/link";

type Card = { ticker: string; sector: string; scanned_at: string; [k: string]: unknown };

export function TickerCard({ card }: { card: Card }) {
  return (
    <Link href={`/stock/${card.ticker}`} style={{
      display: "block", padding: 12,
      background: "var(--bg-panel)", border: "1px solid var(--border-dim)",
      borderRadius: 4, color: "var(--text-primary)", textDecoration: "none",
      fontFamily: "var(--font-mono)",
    }}>
      <div style={{ fontSize: 16, fontWeight: 700 }}>{card.ticker}</div>
      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{card.sector}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 8 }}>
        scanned: {new Date(card.scanned_at).toLocaleTimeString()}
      </div>
    </Link>
  );
}
```

- [ ] **Step 5: `FilterBar` (client component, updates URL)**

```tsx
// web/components/watchlist/FilterBar.tsx
"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const SECTORS = [
  "All", "Technology", "Financials", "Healthcare", "Consumer Discretionary",
  "Communication Services", "Energy", "Industrials", "Consumer Staples", "ETF",
];

const SETUPS = ["All", "C-bull", "C-bear", "F-MULTI", "NEUTRAL"];

export function FilterBar({ current }: { current: Record<string, string | undefined> }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const setParam = (key: string, value: string | null) => {
    const q = new URLSearchParams(params.toString());
    if (value === null || value === "All") q.delete(key);
    else q.set(key, value);
    router.push(`${pathname}?${q.toString()}`);
  };

  const chip = (label: string, active: boolean, onClick: () => void) => (
    <button key={label} onClick={onClick} style={{
      padding: "4px 10px", fontSize: 11, fontFamily: "var(--font-mono)",
      background: active ? "var(--accent-bg)" : "transparent",
      color: active ? "var(--accent-text)" : "var(--text-secondary)",
      border: `1px solid ${active ? "var(--accent-bg)" : "var(--border-dim)"}`,
      borderRadius: 3, cursor: "pointer",
    }}>{label}</button>
  );

  return (
    <div style={{ display: "flex", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {SECTORS.map(s =>
          chip(s, (current.sector ?? "All") === s, () =>
            setParam("sector", s === "All" ? null : s)
          )
        )}
      </div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {SETUPS.map(s =>
          chip(s, (current.setup ?? "All") === s, () =>
            setParam("setup", s === "All" ? null : s)
          )
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Boot the full dev stack and click through manually**

```bash
bash scripts/dev.sh
```

Open <http://127.0.0.1:3001/watchlist>. Expected: page renders the seeded tickers grouped by sector, click on a card navigates to `/stock/TSLA` (404 for now — fixed in S10). Click filter chips; URL updates and grid re-renders.

- [ ] **Step 7: Commit**

```bash
git add web/app/watchlist/ web/components/watchlist/
git commit -m "feat(web): /watchlist landing — server component + filter chips + grid skeleton"
```

S8 done.

---

## Slice S9 — TickerCard sub-components

**Goal:** Fill in the visual blocks of `TickerCard`: header (ticker + IV ATM + IVR + freshness chip + ⋯ menu), setup badge, sparkline + return chips, aggression gauge, gamma block, skew block, positioning block. SVG-only, no extra data fetches.

### Task S9.1 — `SetupBadge`

**Files:**
- Create: `web/components/watchlist/SetupBadge.tsx`
- Create: `web/tests/unit/setupBadge.test.tsx`

- [ ] **Step 1: Test**

```tsx
// web/tests/unit/setupBadge.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SetupBadge } from "@/components/watchlist/SetupBadge";

describe("SetupBadge", () => {
  it("renders C-BULL in positive color", () => {
    const { getByText } = render(<SetupBadge type="C" direction="bull" />);
    expect(getByText("C-BULL")).toBeTruthy();
  });
  it("renders C-BEAR in negative color", () => {
    const { getByText } = render(<SetupBadge type="C" direction="bear" />);
    expect(getByText("C-BEAR")).toBeTruthy();
  });
  it("renders F-MULTI for F setup", () => {
    const { getByText } = render(<SetupBadge type="F" direction={null} />);
    expect(getByText("F-MULTI")).toBeTruthy();
  });
  it("renders NEUTRAL for null setup", () => {
    const { getByText } = render(<SetupBadge type={null} direction={null} />);
    expect(getByText("NEUTRAL")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// web/components/watchlist/SetupBadge.tsx
type Props = { type: string | null; direction: string | null };

function labelAndColor(t: string | null, d: string | null): { label: string; color: string } {
  if (t === "C" && d === "bull") return { label: "C-BULL", color: "var(--positive)" };
  if (t === "C" && d === "bear") return { label: "C-BEAR", color: "var(--negative)" };
  if (t === "F") return { label: "F-MULTI", color: "var(--info)" };
  return { label: "NEUTRAL", color: "var(--text-muted)" };
}

export function SetupBadge({ type, direction }: Props) {
  const { label, color } = labelAndColor(type, direction);
  return (
    <span style={{
      display: "inline-block", padding: "2px 6px", fontSize: 10,
      fontFamily: "var(--font-mono)", letterSpacing: 0.5,
      color: "var(--bg-base)", background: color,
      borderRadius: 2, fontWeight: 700,
    }}>{label}</span>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd web && npx vitest run tests/unit/setupBadge.test.tsx && cd ..
git add web/components/watchlist/SetupBadge.tsx web/tests/unit/setupBadge.test.tsx
git commit -m "feat(web): SetupBadge with C-BULL / C-BEAR / F-MULTI / NEUTRAL"
```

### Task S9.2 — `SparklineRow`

**Files:**
- Create: `web/components/watchlist/SparklineRow.tsx`
- Create: `web/components/watchlist/Sparkline.tsx`
- Create: `web/tests/unit/sparkline.test.tsx`

- [ ] **Step 1: Test the SVG path generator**

```tsx
// web/tests/unit/sparkline.test.tsx
import { describe, it, expect } from "vitest";
import { sparklinePath } from "@/components/watchlist/Sparkline";

describe("sparklinePath", () => {
  it("returns empty path for empty input", () => {
    expect(sparklinePath([], 100, 30)).toBe("");
  });
  it("draws a flat line for constant data", () => {
    const d = sparklinePath([10, 10, 10, 10], 100, 30);
    expect(d).toMatch(/^M0,15 L33.33,15 L66.67,15 L100,15$/);
  });
  it("scales min to bottom and max to top", () => {
    const d = sparklinePath([10, 20], 100, 30);
    // Two points: x=[0, 100], y=[30, 0]
    expect(d).toBe("M0,30 L100,0");
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// web/components/watchlist/Sparkline.tsx
export function sparklinePath(values: number[], width: number, height: number): string {
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = (i * step).toFixed(2).replace(/\.00$/, "");
      const y = (((max - v) / range) * height).toFixed(2).replace(/\.00$/, "");
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
}

export function Sparkline({ values, color = "var(--accent-bg)" }: { values: number[]; color?: string }) {
  const width = 200, height = 30;
  const d = sparklinePath(values, width, height);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}
```

- [ ] **Step 3: `SparklineRow` combines the chart with three return chips**

```tsx
// web/components/watchlist/SparklineRow.tsx
import { Sparkline } from "./Sparkline";
import { fmtPct } from "@/lib/formatters";

type Props = {
  closes: number[];
  ret_1d: number | null | undefined;
  ret_1w: number | null | undefined;
  ret_30d: number | null | undefined;
};

function chip(label: string, value: number | null | undefined) {
  const color = value == null ? "var(--text-muted)" : value >= 0 ? "var(--positive)" : "var(--negative)";
  return (
    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color, marginRight: 8 }}>
      {label} {fmtPct(value ?? null)}
    </span>
  );
}

export function SparklineRow(p: Props) {
  return (
    <div>
      <Sparkline values={p.closes} />
      <div style={{ marginTop: 4 }}>
        {chip("1d", p.ret_1d)}
        {chip("1w", p.ret_1w)}
        {chip("30d", p.ret_30d)}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run + commit**

```bash
cd web && npx vitest run tests/unit/sparkline.test.tsx && cd ..
git add web/components/watchlist/Sparkline.tsx \
        web/components/watchlist/SparklineRow.tsx \
        web/tests/unit/sparkline.test.tsx
git commit -m "feat(web): Sparkline SVG + SparklineRow with return chips"
```

### Task S9.3 — `AggressionGauge`

**Files:**
- Create: `web/components/watchlist/AggressionGauge.tsx`

- [ ] **Step 1: Implement (circular ring gauge, no test — pure visual)**

```tsx
// web/components/watchlist/AggressionGauge.tsx
type Props = { value: number | null | undefined };  // 0..1

export function AggressionGauge({ value }: Props) {
  const r = 22, c = 2 * Math.PI * r;
  const pct = value ?? 0;
  const offset = c * (1 - pct);
  const label = value == null ? "—" : `${Math.round(pct * 100)}`;
  const color = value == null
    ? "var(--text-muted)"
    : pct > 0.7 ? "var(--positive)" : pct < 0.3 ? "var(--negative)" : "var(--warning)";
  return (
    <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "center" }}>
      <svg width={56} height={56} viewBox="0 0 56 56">
        <circle cx="28" cy="28" r={r} fill="none" stroke="var(--border-dim)" strokeWidth={4} />
        <circle
          cx="28" cy="28" r={r}
          fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={c} strokeDashoffset={offset}
          transform="rotate(-90 28 28)" strokeLinecap="round"
        />
        <text x="28" y="32" textAnchor="middle"
              fontFamily="var(--font-mono)" fontSize="11" fill="var(--text-primary)">
          {label}
        </text>
      </svg>
      <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-muted)", letterSpacing: 0.5 }}>
        FLOW AGGR
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/watchlist/AggressionGauge.tsx
git commit -m "feat(web): AggressionGauge circular ring with color-by-band"
```

### Task S9.4 — `GammaBlock`, `SkewBlock`, `PositioningBlock`

**Files:**
- Create: `web/components/watchlist/GammaBlock.tsx`
- Create: `web/components/watchlist/SkewBlock.tsx`
- Create: `web/components/watchlist/PositioningBlock.tsx`

- [ ] **Step 1: `GammaBlock`**

```tsx
// web/components/watchlist/GammaBlock.tsx
import { fmtPct, fmtDecimal, fmtMoney } from "@/lib/formatters";

type Props = {
  flip_distance: number | null;
  flip_price: number | null;
  per_1pct_move: number | null;
  max_strike: number | null;
  expiring_pct: number | null;
  expiring_date: string | null;
};

function row(label: string, value: string) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)" }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ color: "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

export function GammaBlock(p: Props) {
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: 1, marginBottom: 4 }}>GAMMA</div>
      {row("GEX Flip Dist", fmtPct(p.flip_distance))}
      {row("GEX Flip Price", p.flip_price != null ? `$${fmtDecimal(p.flip_price, 2)}` : "—")}
      {row("GEX/1% Move", fmtMoney(p.per_1pct_move))}
      {row("Max GEX Strike", p.max_strike != null ? `$${fmtDecimal(p.max_strike, 0)}` : "—")}
      {row(
        "GEX Expiring",
        p.expiring_pct != null && p.expiring_date
          ? `${fmtPct(p.expiring_pct, 1)} (${p.expiring_date})`
          : "—",
      )}
    </div>
  );
}
```

- [ ] **Step 2: `SkewBlock`**

```tsx
// web/components/watchlist/SkewBlock.tsx
import { fmtSigned } from "@/lib/formatters";

export function SkewBlock({ rr25d_30dte }: { rr25d_30dte: number | null }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: 1, marginBottom: 4 }}>SKEW (30d)</div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: "var(--text-muted)" }}>25Δ RR</span>
        <span style={{ color: "var(--text-primary)" }}>{fmtSigned(rr25d_30dte, 4)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `PositioningBlock`**

```tsx
// web/components/watchlist/PositioningBlock.tsx
import { fmtDecimal, fmtSigned } from "@/lib/formatters";

type Props = {
  call_oi: number | null;
  put_oi: number | null;
  pcr_oi: number | null;
  pcr_vol: number | null;
  pcr_delta_30d: number | null;
};

export function PositioningBlock(p: Props) {
  const total = (p.call_oi ?? 0) + (p.put_oi ?? 0);
  const callPct = total > 0 ? (p.call_oi ?? 0) / total : 0.5;
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: 1, marginBottom: 4 }}>POSITIONING</div>
      {/* Split bar */}
      <div style={{ display: "flex", height: 6, marginBottom: 6, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ flex: callPct, background: "var(--positive)" }} />
        <div style={{ flex: 1 - callPct, background: "var(--negative)" }} />
      </div>
      <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        calls {p.call_oi != null ? fmtDecimal(p.call_oi, 0) : "—"}
        {" / "}
        puts {p.put_oi != null ? fmtDecimal(p.put_oi, 0) : "—"}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)", marginTop: 4 }}>
        <span style={{ color: "var(--text-muted)" }}>PCR (OI)</span>
        <span>{fmtDecimal(p.pcr_oi, 2)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: "var(--text-muted)" }}>PCR (Vol)</span>
        <span>{fmtDecimal(p.pcr_vol, 2)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: "var(--text-muted)" }}>PCR Δ30d</span>
        <span>{fmtSigned(p.pcr_delta_30d, 2)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/components/watchlist/GammaBlock.tsx \
        web/components/watchlist/SkewBlock.tsx \
        web/components/watchlist/PositioningBlock.tsx
git commit -m "feat(web): GammaBlock, SkewBlock, PositioningBlock"
```

### Task S9.5 — Compose the full `TickerCard` and fetch sparkline data

**Files:**
- Modify: `web/components/watchlist/TickerCard.tsx`
- Modify: `web/app/watchlist/page.tsx` (parallel-fetch sparklines)

- [ ] **Step 1: Update `WatchlistPage` to parallel-fetch sparklines for visible tickers**

```tsx
import { api } from "@/lib/api";
import { CardGrid } from "@/components/watchlist/CardGrid";
import { FilterBar } from "@/components/watchlist/FilterBar";

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  if (sp.sector) qs.set("sector", sp.sector);
  if (sp.setup) qs.set("setup", sp.setup);
  if (sp.fresh) qs.set("fresh_within_minutes", sp.fresh);
  const data = await api.watchlist(qs);

  // Parallel-fetch 30d OHLC for each ticker → sparkline points.
  const sparklineEntries = await Promise.all(
    data.tickers.map(async (t) => {
      const bars = await api.ohlc(t.ticker, 30);
      return [t.ticker, bars.map((b: any) => Number(b.close))] as const;
    })
  );
  const sparklines = Object.fromEntries(sparklineEntries);

  return (
    <main style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
        <h1 style={{ fontFamily: "var(--font-mono)", fontSize: 24, letterSpacing: 1 }}>WATCHLIST</h1>
        <span style={{ color: "var(--text-muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {data.scheduler_lag_seconds != null
            ? `scheduler: ${Math.round(data.scheduler_lag_seconds)}s lag`
            : "scheduler: unknown"}
        </span>
      </header>
      <FilterBar current={sp} />
      <CardGrid data={data} sparklines={sparklines} />
    </main>
  );
}
```

- [ ] **Step 2: Update `CardGrid` to thread sparklines through to `TickerCard`**

```tsx
// CardGrid.tsx — accept `sparklines: Record<string, number[]>` and pass to TickerCard
```

- [ ] **Step 3: Compose full `TickerCard`**

```tsx
// web/components/watchlist/TickerCard.tsx
"use client";
import Link from "next/link";
import { SetupBadge } from "./SetupBadge";
import { SparklineRow } from "./SparklineRow";
import { AggressionGauge } from "./AggressionGauge";
import { GammaBlock } from "./GammaBlock";
import { SkewBlock } from "./SkewBlock";
import { PositioningBlock } from "./PositioningBlock";
import { fmtPct, fmtDecimal, toNum } from "@/lib/formatters";
import { bucketFreshness } from "@/lib/freshness";

type Props = { card: any; sparkline: number[] };

export function TickerCard({ card, sparkline }: Props) {
  const fresh = bucketFreshness(card.scanned_at);
  const dot =
    fresh === "fresh" ? "var(--positive)"
    : fresh === "stale" ? "var(--warning)"
    : "var(--negative)";

  return (
    <Link href={`/stock/${card.ticker}`} style={{
      display: "block", padding: 12,
      background: "var(--bg-panel)", border: "1px solid var(--border-dim)",
      borderRadius: 4, color: "var(--text-primary)", textDecoration: "none",
      fontFamily: "var(--font-mono)",
    }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: dot, display: "inline-block" }} />
          <span style={{ fontSize: 16, fontWeight: 700 }}>{card.ticker}</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {fmtPct(toNum(card.iv_atm), 1)}
          </div>
          <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
            IVR {fmtDecimal(toNum(card.iv_rank), 0)}
          </div>
        </div>
      </div>

      {/* Setup */}
      <SetupBadge type={card.setup?.type ?? null} direction={card.setup?.direction ?? null} />

      {/* Sparkline + returns + gauge — `toNum` preserves legitimate zero values
          (Number(0) || null would clobber them to null). */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center", margin: "8px 0" }}>
        <SparklineRow
          closes={sparkline}
          ret_1d={toNum(card.returns?.d1)}
          ret_1w={toNum(card.returns?.w1)}
          ret_30d={toNum(card.returns?.d30)}
        />
        <AggressionGauge value={toNum(card.aggression_pct)} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8 }}>
        <GammaBlock
          flip_distance={toNum(card.gamma.flip_distance)}
          flip_price={toNum(card.gamma.flip_price)}
          per_1pct_move={toNum(card.gamma.per_1pct_move)}
          max_strike={toNum(card.gamma.max_strike)}
          expiring_pct={toNum(card.gamma.expiring_pct)}
          expiring_date={card.gamma.expiring_date ?? null}
        />
        <SkewBlock rr25d_30dte={toNum(card.skew.rr25d_30dte)} />
        <PositioningBlock
          call_oi={card.positioning.call_oi ?? null}
          put_oi={card.positioning.put_oi ?? null}
          pcr_oi={toNum(card.positioning.pcr_oi)}
          pcr_vol={toNum(card.positioning.pcr_vol)}
          pcr_delta_30d={toNum(card.positioning.pcr_delta_30d)}
        />
      </div>
    </Link>
  );
}
```

- [ ] **Step 4: Boot + dogfood**

Run `bash scripts/dev.sh`, open <http://127.0.0.1:3001/watchlist>. Expected: cards now look like the Market Pulse reference (subjective check — escalate to design-review if anything looks obviously broken).

- [ ] **Step 5: Commit**

```bash
git add web/components/watchlist/TickerCard.tsx web/components/watchlist/CardGrid.tsx web/app/watchlist/page.tsx
git commit -m "feat(web): full TickerCard with header / setup / sparkline / gauge / GAMMA / SKEW / POSITIONING"
```

S9 done.

---

## Slice S10 — Detail page foundation

**Goal:** `/stock/[ticker]` layout with persistent header strip + tab nav. Tab content is empty placeholders for S11.

### Task S10.1 — Layout + tab routing

**Files:**
- Create: `web/app/stock/[ticker]/layout.tsx`
- Create: `web/app/stock/[ticker]/page.tsx`
- Create: `web/app/stock/[ticker]/[tab]/page.tsx`
- Create: `web/components/stock/DetailHeader.tsx`
- Create: `web/components/stock/TabBar.tsx`

- [ ] **Step 1: Detail header**

```tsx
// web/components/stock/DetailHeader.tsx
import Link from "next/link";
import { SetupBadge } from "@/components/watchlist/SetupBadge";
import { fmtDecimal, fmtSigned } from "@/lib/formatters";

type Props = {
  ticker: string;
  spot: number | null;
  iv_atm: number | null;
  spotQuotedAt: string | null;
  scannedAt: string | null;
  setupType: string | null;
  setupDirection: string | null;
  setupScore: number | null;
};

export function DetailHeader(p: Props) {
  return (
    <header style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 16px", background: "var(--bg-panel)",
      borderBottom: "1px solid var(--border-dim)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <Link href="/watchlist" style={{ color: "var(--text-muted)", fontSize: 12 }}>← back</Link>
        <h1 style={{ fontFamily: "var(--font-mono)", fontSize: 24, margin: 0 }}>{p.ticker}</h1>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 18 }}>
          ${fmtDecimal(p.spot, 2)}
        </span>
        <SetupBadge type={p.setupType} direction={p.setupDirection} />
        {p.setupScore != null && (
          <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            score {fmtSigned(p.setupScore, 2)}
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)", textAlign: "right" }}>
        <div>spot: {p.spotQuotedAt ? new Date(p.spotQuotedAt).toLocaleTimeString() : "—"}</div>
        <div>analytics: {p.scannedAt ? new Date(p.scannedAt).toLocaleTimeString() : "—"}</div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: TabBar**

```tsx
// web/components/stock/TabBar.tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  ["market-structure", "Market Structure"],
  ["volatility", "Volatility"],
  ["flow", "Flow"],
  ["vrp", "VRP"],
  ["trade-plan", "Trade Plan"],
  ["tables", "Tables"],
] as const;

export function TabBar({ ticker }: { ticker: string }) {
  const path = usePathname();
  return (
    <nav style={{
      display: "flex", gap: 0, borderBottom: "1px solid var(--border-dim)",
      padding: "0 16px",
    }}>
      {TABS.map(([slug, label]) => {
        const href = `/stock/${ticker}/${slug}`;
        const active = path === href;
        return (
          <Link
            key={slug}
            href={href}
            prefetch
            style={{
              padding: "10px 16px",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: active ? "var(--accent-bg)" : "var(--text-secondary)",
              borderBottom: active ? "2px solid var(--accent-bg)" : "2px solid transparent",
              textDecoration: "none",
            }}
          >{label}</Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 3: Layout that fetches the report once**

```tsx
// web/app/stock/[ticker]/layout.tsx
import { api } from "@/lib/api";
import { DetailHeader } from "@/components/stock/DetailHeader";
import { TabBar } from "@/components/stock/TabBar";
import { toNum } from "@/lib/formatters";

export default async function StockLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  // Per-tab pages do their own fetch (cache:'no-store' + same-URL → request-pass dedup with the layout call).
  const report = await api.stock(ticker);

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <DetailHeader
        ticker={report.ticker}
        spot={toNum(report.market_structure.spot)}
        iv_atm={toNum(report.volatility.iv)}
        spotQuotedAt={null}      // wired from intraday_quote in a future enhancement
        scannedAt={report.generated_at}
        setupType={report.setup?.setup_type ?? null}
        setupDirection={report.setup?.direction ?? null}
        setupScore={toNum(report.setup?.score)}
      />
      <TabBar ticker={ticker} />
      <div style={{ padding: 16 }}>{children}</div>
    </main>
  );
}
```

- [ ] **Step 4: Default page redirect**

```tsx
// web/app/stock/[ticker]/page.tsx
import { redirect } from "next/navigation";

export default async function StockIndex({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  redirect(`/stock/${ticker}/market-structure`);
}
```

- [ ] **Step 5: Dynamic tab page with runtime whitelist**

```tsx
// web/app/stock/[ticker]/[tab]/page.tsx
import { notFound } from "next/navigation";
import { api } from "@/lib/api";

const VALID = new Set(["market-structure", "volatility", "flow", "vrp", "trade-plan", "tables"]);

export default async function TabPage({
  params,
}: {
  params: Promise<{ ticker: string; tab: string }>;
}) {
  const { ticker, tab } = await params;
  if (!VALID.has(tab)) notFound();
  const report = await api.stock(ticker);

  return (
    <section>
      <h2 style={{ fontFamily: "var(--font-mono)", fontSize: 14, color: "var(--text-secondary)", letterSpacing: 1, textTransform: "uppercase" }}>
        {tab.replace("-", " ")}
      </h2>
      <pre style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        {/* Placeholder for S11 */}
        run_id: {report.run_id} — tab content lands in S11
      </pre>
    </section>
  );
}
```

- [ ] **Step 6: Boot + verify**

`bash scripts/dev.sh`, navigate to <http://127.0.0.1:3001/stock/TSLA>. Should redirect to `/stock/TSLA/market-structure`. Tab nav switches between segments. Unknown tab → 404.

- [ ] **Step 7: Commit**

```bash
git add web/app/stock web/components/stock
git commit -m "feat(web): /stock/[ticker] layout + tab routing + DetailHeader + TabBar"
```

S10 done.

---

## Slice S11 — Detail page tabs

**Goal:** Render the existing `SingleStockReport` payload on each tab.

### Task S11.1 — Shared panel primitives

**Files:**
- Create: `web/components/stock/panels/MetricGrid.tsx`
- Create: `web/components/stock/panels/MetricRow.tsx`
- Create: `web/components/stock/panels/DataTable.tsx`

- [ ] **Step 1: `MetricGrid`**

```tsx
// web/components/stock/panels/MetricGrid.tsx
export function MetricGrid({ children, cols = 4 }: { children: React.ReactNode; cols?: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 16 }}>
      {children}
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 18, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
        {value == null || value === "" ? "—" : value}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: `DataTable`**

```tsx
// web/components/stock/panels/DataTable.tsx
export function DataTable<T extends Record<string, unknown>>({
  rows, columns,
}: {
  rows: T[];
  columns: { key: keyof T; label: string; render?: (v: T[keyof T], row: T) => React.ReactNode }[];
}) {
  if (rows.length === 0) return <div style={{ color: "var(--text-muted)", fontSize: 12 }}>No rows.</div>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 11 }}>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={String(c.key)} style={{ textAlign: "left", padding: "4px 8px", color: "var(--text-muted)", borderBottom: "1px solid var(--border-dim)" }}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderBottom: "1px solid var(--border-dim)" }}>
            {columns.map((c) => (
              <td key={String(c.key)} style={{ padding: "4px 8px" }}>
                {c.render ? c.render(r[c.key], r) : String(r[c.key] ?? "—")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/components/stock/panels/
git commit -m "feat(web): MetricGrid + Metric + DataTable panel primitives"
```

### Task S11.2 — Tab bodies (6 tabs)

**Files:**
- Modify: `web/app/stock/[ticker]/[tab]/page.tsx` (delegate to per-tab body component)
- Create: `web/components/stock/tabs/MarketStructureTab.tsx`
- Create: `web/components/stock/tabs/VolatilityTab.tsx`
- Create: `web/components/stock/tabs/FlowTab.tsx`
- Create: `web/components/stock/tabs/VrpTab.tsx`
- Create: `web/components/stock/tabs/TradePlanTab.tsx`
- Create: `web/components/stock/tabs/TablesTab.tsx`

- [ ] **Step 1: Update the dynamic tab page to dispatch**

```tsx
// web/app/stock/[ticker]/[tab]/page.tsx
import { notFound } from "next/navigation";
import { api } from "@/lib/api";

import { MarketStructureTab } from "@/components/stock/tabs/MarketStructureTab";
import { VolatilityTab } from "@/components/stock/tabs/VolatilityTab";
import { FlowTab } from "@/components/stock/tabs/FlowTab";
import { VrpTab } from "@/components/stock/tabs/VrpTab";
import { TradePlanTab } from "@/components/stock/tabs/TradePlanTab";
import { TablesTab } from "@/components/stock/tabs/TablesTab";

const TABS = {
  "market-structure": MarketStructureTab,
  "volatility":       VolatilityTab,
  "flow":             FlowTab,
  "vrp":              VrpTab,
  "trade-plan":       TradePlanTab,
  "tables":           TablesTab,
} as const;

export default async function TabPage({
  params,
}: {
  params: Promise<{ ticker: string; tab: string }>;
}) {
  const { ticker, tab } = await params;
  const Component = TABS[tab as keyof typeof TABS];
  if (!Component) notFound();
  const report = await api.stock(ticker);
  return <Component report={report} />;
}
```

- [ ] **Step 2: `MarketStructureTab`**

```tsx
// web/components/stock/tabs/MarketStructureTab.tsx
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { DataTable } from "../panels/DataTable";
import { fmtDecimal, toNum } from "@/lib/formatters";

export function MarketStructureTab({ report }: { report: any }) {
  const m = report.market_structure;
  return (
    <div>
      <h3 style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-secondary)", letterSpacing: 1, textTransform: "uppercase" }}>Gamma Exposure</h3>
      <MetricGrid cols={4}>
        <Metric label="Net GEX" value={fmtDecimal(toNum(m.net_gex), 0)} />
        <Metric label="Call GEX" value={fmtDecimal(toNum(m.total_call_gex), 0)} />
        <Metric label="Put GEX"  value={fmtDecimal(toNum(m.total_put_gex), 0)} />
        <Metric label="Max Pain (nearest)" value={`$${fmtDecimal(toNum(m.max_pain), 2)}`} />
      </MetricGrid>

      <h3 style={{ marginTop: 24, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-secondary)", letterSpacing: 1, textTransform: "uppercase" }}>Top OI Strikes</h3>
      <div style={{ display: "flex", gap: 32, fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <div>
          <div style={{ color: "var(--text-muted)" }}>Calls</div>
          {m.top_call_oi_strikes?.length
            ? m.top_call_oi_strikes.map((s: string) => <div key={s}>${s}</div>)
            : "—"}
        </div>
        <div>
          <div style={{ color: "var(--text-muted)" }}>Puts</div>
          {m.top_put_oi_strikes?.length
            ? m.top_put_oi_strikes.map((s: string) => <div key={s}>${s}</div>)
            : "—"}
        </div>
      </div>

      {report.max_pain_rows?.length > 0 && (
        <>
          <h3 style={{ marginTop: 24, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-secondary)", letterSpacing: 1, textTransform: "uppercase" }}>Max Pain by Expiry</h3>
          <DataTable
            rows={report.max_pain_rows}
            columns={[
              { key: "expiry", label: "Expiry" },
              { key: "max_pain", label: "Max Pain", render: (v) => v != null ? `$${v}` : "—" },
              { key: "close", label: "Close", render: (v) => v != null ? `$${v}` : "—" },
              { key: "next_upper_strike", label: "Upper", render: (v) => v != null ? `$${v}` : "—" },
              { key: "next_lower_strike", label: "Lower", render: (v) => v != null ? `$${v}` : "—" },
            ]}
          />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: `VolatilityTab` (similar pattern, 8 metrics in MetricGrid + term structure list)**

Use `MetricGrid` with: IV, RV, IV Rank, IV Rank 1y, IV 52w low/high, RV 52w low/high, IV %ile 30d, Implied Move 30d, Skew 25Δ. Render `term_dte_to_iv` as a small inline table (DTE → IV).

(Implementation parallels `MarketStructureTab` — repeat the pattern with the fields from `VolatilityProfile` in `models.py`.)

- [ ] **Step 4: `FlowTab`**

Metrics: flow_count, net_premium, bull_premium, bear_premium, ask_side_premium, bid_side_premium. Then a `DataTable` of `top_alerts` with columns: id (first 8 chars), type, expiry, strike, price, total_size, total_premium, vol_oi, rule.

- [ ] **Step 5: `VrpTab`**

Just two metrics: VRP (IV - RV) and Signal. Plus the `vrp.note` rendered as a callout panel.

- [ ] **Step 6: `TradePlanTab`**

If `report.setup` is null, render "No Type C classification on this run."
Otherwise show: setup_type, label, direction, score, confirmations (bulleted), warnings (callout).
If `report.trade_plan` exists, render structure + rationale + legs DataTable.

- [ ] **Step 7: `TablesTab`**

Three sections:
- OI Change top movers — `DataTable` from `report.oi_change_top`.
- Dark pool snapshot — two metrics: print_count, notional.
- Short data — if `report.short_data` is non-null, three metrics: shares_available, fee_rate, rebate_rate.

- [ ] **Step 8: Boot + dogfood**

`bash scripts/dev.sh`, click through all six tabs on TSLA. Each should render real data; nothing should `undefined` or `[object Object]`.

- [ ] **Step 9: Commit**

```bash
git add web/components/stock/tabs/ web/app/stock/[ticker]/[tab]/page.tsx
git commit -m "feat(web): 6 detail-page tabs render SingleStockReport"
```

S11 done.

---

## Slice S12 — Mutations + admin + E2E

**Goal:** `AddTickerDialog`, `RescanButton` polling client island, simple `/admin` ops page, one Playwright golden-path test.

### Task S12.1 — `RescanButton` with polling

**Files:**
- Create: `web/components/shared/RescanButton.tsx`
- Modify: `web/components/watchlist/TickerCard.tsx` (add the ⋯ menu housing the button)

- [ ] **Step 1: Implement**

```tsx
// web/components/shared/RescanButton.tsx
"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Status = "idle" | "queued" | "running" | "done" | "failed";

export function RescanButton({ ticker }: { ticker: string }) {
  const router = useRouter();
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");

  useEffect(() => {
    if (!jobId) return;
    const t = setInterval(async () => {
      try {
        const r = await api.job(jobId);
        setStatus(r.status as Status);
        if (r.status === "done" || r.status === "failed") {
          clearInterval(t);
          if (r.status === "done") router.refresh();
        }
      } catch (e) {
        console.error(e);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [jobId, router]);

  return (
    <button
      onClick={async (e) => {
        e.preventDefault();
        e.stopPropagation();
        setStatus("queued");
        const r = await api.rescan(ticker);
        setJobId(r.job_id);
      }}
      disabled={status === "queued" || status === "running"}
      style={{
        fontSize: 10, fontFamily: "var(--font-mono)",
        padding: "2px 6px",
        background: "transparent", color: "var(--text-secondary)",
        border: "1px solid var(--border-dim)", borderRadius: 2, cursor: "pointer",
      }}
    >
      {status === "idle" ? "rescan" :
       status === "queued" ? "queued…" :
       status === "running" ? "running…" :
       status === "done" ? "✓ done" :
       "✗ failed"}
    </button>
  );
}
```

- [ ] **Step 2: Wire it into the card's footer**

In `TickerCard.tsx` add at the bottom (above the closing `</Link>`, wrapped in `<div>` that calls `e.stopPropagation()`):

```tsx
<div style={{ marginTop: 8, display: "flex", justifyContent: "flex-end" }}
     onClick={(e) => e.stopPropagation()}>
  <RescanButton ticker={card.ticker} />
</div>
```

- [ ] **Step 3: Commit**

```bash
git add web/components/shared/RescanButton.tsx web/components/watchlist/TickerCard.tsx
git commit -m "feat(web): RescanButton with 1s polling + router.refresh() on done"
```

### Task S12.2 — `AddTickerDialog`

**Files:**
- Create: `web/components/watchlist/AddTickerDialog.tsx`
- Modify: `web/app/watchlist/page.tsx` (mount the dialog)

- [ ] **Step 1: Implement (HTML `<dialog>`-based — no headless-ui dep)**

```tsx
// web/components/watchlist/AddTickerDialog.tsx
"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

const SECTORS = [
  "Technology", "Financials", "Healthcare", "Consumer Discretionary",
  "Communication Services", "Energy", "Industrials", "Consumer Staples", "ETF",
];

export function AddTickerDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [sector, setSector] = useState(SECTORS[0]);
  const [notes, setNotes] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.addTicker({ ticker: ticker.toUpperCase(), sector, notes });
    ref.current?.close();
    setTicker(""); setNotes("");
    router.refresh();
  };

  return (
    <>
      <button onClick={() => ref.current?.showModal()} style={{
        padding: "4px 10px", fontFamily: "var(--font-mono)", fontSize: 11,
        background: "var(--accent-bg)", color: "var(--accent-text)",
        border: 0, borderRadius: 3, cursor: "pointer",
      }}>+ Ticker</button>
      <dialog ref={ref} style={{ padding: 16, background: "var(--bg-panel)", color: "var(--text-primary)", border: "1px solid var(--border-dim)" }}>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 280 }}>
          <input required placeholder="TICKER" value={ticker}
                 onChange={(e) => setTicker(e.target.value)}
                 style={{ fontFamily: "var(--font-mono)", padding: 4 }} />
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <input placeholder="notes (optional)" value={notes}
                 onChange={(e) => setNotes(e.target.value)} />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button type="button" onClick={() => ref.current?.close()}>Cancel</button>
            <button type="submit">Add</button>
          </div>
        </form>
      </dialog>
    </>
  );
}
```

- [ ] **Step 2: Mount in `WatchlistPage` header**

```tsx
import { AddTickerDialog } from "@/components/watchlist/AddTickerDialog";
// inside <header>:
<AddTickerDialog />
```

- [ ] **Step 3: Commit**

```bash
git add web/components/watchlist/AddTickerDialog.tsx web/app/watchlist/page.tsx
git commit -m "feat(web): AddTickerDialog for POST /api/watchlist"
```

### Task S12.3 — `/admin` ops page

**Files:**
- Create: `web/app/admin/page.tsx`

- [ ] **Step 1: Implement**

```tsx
// web/app/admin/page.tsx
import { api } from "@/lib/api";

async function fetchHealth() {
  const r = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"}/api/health`,
                       { cache: "no-store" });
  return r.json();
}

export default async function AdminPage() {
  const health = await fetchHealth();
  return (
    <main style={{ padding: 24, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
      <h1>Admin</h1>
      <pre style={{ background: "var(--bg-panel)", padding: 12 }}>
        {JSON.stringify(health, null, 2)}
      </pre>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/admin/page.tsx
git commit -m "feat(web): /admin page renders /api/health JSON"
```

### Task S12.4 — Playwright golden-path E2E

**Files:**
- Create: `web/playwright.config.ts`
- Create: `web/tests/e2e/golden-path.spec.ts`

- [ ] **Step 1: Playwright config**

```typescript
// web/playwright.config.ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3001",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:3001",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
```

- [ ] **Step 2: Spec**

```typescript
// web/tests/e2e/golden-path.spec.ts
import { test, expect } from "@playwright/test";

test("watchlist → detail → tab → rescan", async ({ page }) => {
  await page.goto("/watchlist");
  await expect(page.getByText("WATCHLIST")).toBeVisible();

  // First card should be clickable
  const firstCard = page.locator("a[href^='/stock/']").first();
  const ticker = (await firstCard.getAttribute("href"))?.split("/").pop()!;
  await firstCard.click();

  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/market-structure`));
  await page.getByRole("link", { name: /flow/i }).click();
  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/flow`));

  await page.goto("/watchlist");
  // Rescan flow (no assertion on completion — just verify enqueue works)
  await page.locator("button:has-text('rescan')").first().click();
  await expect(page.locator("button:has-text('queued')").first()).toBeVisible({ timeout: 3000 });
});
```

- [ ] **Step 3: Pre-seed the DB so the watchlist renders**

Document the prereq in a comment at the top of the spec: "Requires `bash scripts/migrate.sh` + at least one `scan_runs` row + `watchlist_card` row. Run `uv run python -m uw_scan.worker.jobs.full_scan` once before E2E if cards are missing."

- [ ] **Step 4: Run**

```bash
cd web && npx playwright install chromium && npx playwright test
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add web/playwright.config.ts web/tests/e2e/golden-path.spec.ts
git commit -m "test(e2e): Playwright golden-path watchlist→detail→tab→rescan"
```

S12 done. The application is feature-complete per the spec's acceptance criteria.

---

## Acceptance verification

After all 12 slices land, run these checks:

- [ ] **All tests green:** `uv run pytest tests/ -v && cd web && npx vitest run && npx playwright test`
- [ ] **Dev stack boots:** `bash scripts/dev.sh` — Next on :3001, API on :8400, scheduler logs `scheduler started`.
- [ ] **Watchlist renders 54 cards:** `curl http://127.0.0.1:8400/api/watchlist | jq '.tickers | length'` ≥ 1 (54 after scheduler has run at least once).
- [ ] **Streamlit gone:** `find . -path ./node_modules -prune -o -name "streamlit_app.py" -print` is empty; `pyproject.toml` has no `streamlit` entry.
- [ ] **Specs archived:** `ls docs/superpowers/archive/specs/ docs/superpowers/archive/plans/` lists the four moved files.
- [ ] **Health is honest:** kill the worker; `/api/health` reports `ok:false` after the configured lag threshold; `/watchlist` shows a warning banner.

