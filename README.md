# Argon

<p align="center">
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white" />
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white" />
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-336791?logo=postgresql&logoColor=white" />
  <img alt="Test stack" src="https://img.shields.io/badge/Tests-pytest%20%7C%20Vitest%20%7C%20Playwright-0A7F6F" />
</p>

**Per-ticker options analytics, watchlist-driven.**

Argon stitches dealer gamma, IV surface, dark-pool flow, and macro/rates context into Postgres, then turns the stitched evidence into compact triage views — and has three LLMs commit to a falsifiable, scored 1-2 week directional thesis on every name worth opening.

**Persisted evidence. Defined risk. Theses are scored, not narrated.**

---

## Four Disciplines (no exceptions)

| Discipline              | Rule                                                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| **1. Persistence**      | Every analytical output (vol, scan, regime, AI thesis) lands in Postgres. No in-memory-only results.       |
| **2. Defined Risk**     | No naked shorts. Every short option is covered. Trade-plan suggestions reject undefined risk by construction. |
| **3. Source Priority**  | IB → Unusual Whales → FMP → massive.com. Yahoo Finance is banned at every layer.                            |
| **4. Idempotent Schema**| Every migration is `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`. Re-running is a no-op. No tracking table.    |

Any discipline fails → fix at the source, not the symptom. Full standing rules: [`CLAUDE.md`](CLAUDE.md).

## Surfaces

| Surface                                  | Signal                                                | Output                                                | Refresh                                |
| ---------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------- | -------------------------------------- |
| **Watchlist Dashboard** (`/`)            | Per-ticker scan composite                             | Setup badge, IVR, GEX block, skew, positioning        | Cron `0 5-16 * * 1-5` ET + rescan      |
| **Stock — Market Structure**             | UW spot-exposure + per-strike GEX                     | Flip, magnets, walls, acceleration zones              | Worker-driven                          |
| **Stock — Volatility**                   | IV surface + RV + VRP                                  | VRP, IV/RV regime quadrant, smile, term structure     | Worker-driven + lazy backfill          |
| **Stock — Skew**                         | 25Δ risk-reversal + skew dynamics                     | Constant-maturity RR, skew term structure             | Worker-driven                          |
| **Stock — Technicals**                   | Dual MACD + dimensionless RSI + Chanlun (缠论)         | Oscillators, 200-DMA, 笔/中枢/买卖点 overlay, live badge | Daily + on-demand + live overlay       |
| **Stock — Flow**                         | UW flow alerts + dark prints                          | Filterable by alert type, premium, aggression         | Intraday                               |
| **Stock — Trade Insights AI**            | Codex + Claude + DeepSeek over the stitched evidence  | 1-2w thesis with strikes, triggers, invalidation      | Provider-pinned worker queue           |
| **Scanner** (`/scanner`)                 | DCF / Dark Pool / EIC / GEX detectors                 | Watchlist candidates + market-wide discoveries        | Intraday                               |
| **Regime** (`/regime`)                   | CRI · VCG · GEX · GRG · 5% Canary · Market Tide · Macro Short-Vol | Crash-risk, vol-curve, dealer & dispersion state      | Hourly EOD + 5-min live (CRI/VCG)      |
| **Gold Compass** (`/gold`)               | WGC + ETF flow + COMEX + LBMA + GPR + CFTC            | 5-tier physical / ETF / miner / vol / macro posture   | EOD with replay history                |
| **Index Cockpit** (`/cockpit/<TKR>`)     | SPX / SPY / QQQ / IWM dealer state                    | State, dealer, surface, flow-IM, VRP tabs             | Intraday + `?asof=YYYY-MM-DD` snapshots|
| **US Rates Desk** (`/rates`)             | FRED + Cleveland Fed + TreasuryDirect + CFTC TFF      | Curve, decomposition, supply, positioning, freshness  | Daily                                  |
| **Admin / Health** (`/admin`, `/api/health`) | Scheduler + worker + data freshness              | Liveness, queue depth, freshness monitor, gap-healer  | Live + nightly audit                   |

Full route inventory: [`web/app/`](web/app/) · per-surface doctrine in each `CLAUDE.md`.

## Quick Start

**Prerequisites**

- Python `3.13` via [`uv`](https://docs.astral.sh/uv/) — never bare `python` / `pip` / activated venvs
- Node.js `20+`
- Postgres reachable as DB `option_wizard`, schema `uw_scan`, owner role `argon_app` (NOSUPERUSER)
- [Unusual Whales](https://unusualwhales.com) API key (flow, IV, GEX, spot-exposure)
- [massive.com](https://massive.com) API key (OHLC, Polygon-backed fundamentals)
- [FRED](https://fred.stlouisfed.org/docs/api/) API key (rates, macro)
- (Optional) Codex CLI + Claude CLI signed in locally and `DEEPSEEK_API_KEY` for Trade Insights AI

```bash
git clone https://github.com/moremeds/argon.git
cd argon
uv sync --extra postgres
cd web && npm install && cd ..

cp .env.example .env       # fill API keys + DB creds

bash scripts/migrate.sh    # idempotent SQL against option_wizard.uw_scan
bash scripts/dev.sh        # 13 processes — see Architecture below
```

Terminal at <http://127.0.0.1:3001>. Health: `curl http://127.0.0.1:8400/api/health`.

## Environment

**`.env`** (root) — Python workers, FastAPI, DB:

```bash
UW_SCAN_API_KEY=...
MASSIVE_API_KEY=...
FRED_API_KEY=...
UW_SCAN_DB_HOST=127.0.0.1          # or 100.66.147.98 for the shared Mac mini instance
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=option_wizard
UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=...

# Live spot feed — xenon IB realtime (primary) / massive WS (automatic fallback)
XENON_WS_ENABLED=true                        # primary intraday spot feed (default false)
XENON_WS_URL=ws://127.0.0.1:8765             # mini localhost; MacBook dev → ws://100.66.147.98:8765

# Xenon read-only query API — single-contract IB option greeks/IV (surface canary + VRP entry)
XENON_QUERY_API_URL=http://127.0.0.1:8321    # mini localhost; MacBook dev → http://100.66.147.98:8321
XENON_QUERY_API_KEY=...                       # required (X-API-Key) — missing → silent UW fallback

# Trade Insights AI (optional — defaults to enabled when providers are reachable)
DEEPSEEK_API_KEY=...
TRADE_INSIGHTS_AI_ENABLED=true               # Codex (local subprocess)
TRADE_INSIGHTS_AI_CLAUDE_ENABLED=true        # Claude CLI (OAuth keychain)
TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED=true      # DeepSeek HTTP API (thinking mode)
TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT=2    # drop to 1 on provider-side 429s
```

**`web/.env`** — Next.js client:

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8400
```

The Claude runner deliberately blocks `ANTHROPIC_API_KEY` from its subprocess env so the local Claude CLI's OAuth keychain (subscription auth) wins instead of an accidental pay-per-token call. The Codex runner runs with a strict env allow-list — UW / massive / FRED / DeepSeek keys never reach `codex exec`. DeepSeek is in-process `httpx`, so its key stays scoped to the worker process.

MacBook dev runs against `127.0.0.1`; pointing `dev.sh` at the Mac mini DB is refused by a tripwire unless `UW_SCAN_ALLOW_DEV_AGAINST_MINI=1` — two writers on the same queue would race via `FOR UPDATE SKIP LOCKED` and double-charge AI providers.

The spot WS consumer connects to xenon's IB realtime server first and fails over to massive.com's delayed WS automatically (connect failure, IB down, or in-session tick silence); `/api/health` → `ws_consumer.active_source` names the live feed. Worker processes **freeze env at fork** — rotating any `XENON_*` or provider key requires a worker restart, not just a re-export.

## Argon Terminal

Per-ticker options research surface built on **Next.js 16** with **React 19** and hand-rolled SVG charts. No chart library — gamma profiles, IV smiles, and term structures deserve honest pixels.

**Core capabilities**

- Card-grid watchlist with one-glance reads: setup badge, IVR, flow aggression dial, GEX block, skew, positioning bar
- Per-ticker stock page with six tabs (Market Structure, Volatility, Skew, Flow, Technicals, Trade Insights AI) over a single dealer-positioning model
- IV-surface analytics: VRP panel, smile, term structure, IV/RV regime quadrant, 1y IV percentile distribution
- **Technicals tab** — dual MACD (fast/standard), a dimensionless RSI/momentum readout, and a client-side **Chanlun (缠论)** price overlay (笔 / 中枢 / 买卖点, trust-tiered per the repaint/forward-edge probe), with a live intraday badge and on-demand compute for uncovered tickers
- Detector pipeline (DCF / Dark Pool / EIC / GEX) with separate **watchlist candidates** and **discovered tickers** lanes from the market-wide flow-alerts feed
- Market-wide regime cockpit (`/regime`): CRI, VCG, GEX (with profile chart), **GRG** (Gamma Rotation Gap), **5% Canary**, **Market Tide**, and a **VRP macro short-vol** sizing signal — CRI/VCG also compute live off the WS quote stream on a 5-min cadence, with dispersion context on the CRI subtab
- **Durable option-surface capture** — a nightly full-chain IV/greeks grid (`option_surface_grid_daily`, forward-only accrual) with an IB-vs-UW IV canary, feeding VRP macro entry-capture and short-horizon vol research
- **Gold Compass** five-tier cockpit on the gold complex (GLD / IAU / GDX / …) with `/gold/replay/<YYYY-MM-DD>` for historical days
- Index dealer cockpit (SPX / SPY / QQQ / IWM) with `?asof=YYYY-MM-DD` historical snapshots
- **US Rates Factor Desk** with FRED Treasury curve, Cleveland Fed 10Y decomposition, policy path, TreasuryDirect supply, CFTC TFF positioning, source freshness badges throughout
- **Trade Insights AI** — three LLMs commit to a 1-2 week directional thesis with decomposed `thesis_trigger` / `entry_trigger` / `invalidation` levels and explicit `legs[]` (geometrically validated: a bear put spread must be 2 puts, long strike > short strike, same expiry — the model can't hand-wave)

Theme & design tokens: [`DESIGN.md`](DESIGN.md) · product voice & anti-references: [`PRODUCT.md`](PRODUCT.md).

## Scripts

**Stack:** `scripts/migrate.sh` · `scripts/dev.sh`
**Workers (individual):** `uv run python -m uw_scan.worker.scheduler` with `UW_SCAN_WORKER_ROLE=uw|massive|ai-codex|ai-claude|ai-deepseek` (+ `UW_SCAN_WORKER_INDEX`, `UW_SCAN_WORKER_COUNT`)
**WS consumer:** `uv run python -m uw_scan.worker.massive_ws_consumer`
**Backfills:** `rates_backfill_once.py` · `canary_backfill.py` · `run_cockpit_backfill_jobs.py` · `backfill_flow_footprint.py` · `backfill_vcg_v2.py` · `seed_spy_ohlc.py`
**Backtests / scoring:** `backtest_canary.py` · `backtest_cri.py` · `backtest_vcg.py` · `compare_vcg_lead_time.py` · `score_vcg_classification_accuracy.py`
**Diagnostics:** `audit_uw_api_surface.py` · `validate_cri.py` · `validate_ws.py` · `s0_probe_endpoint.py` · `dry_run_volatility_endpoint.py`

Full inventory: [`scripts/`](scripts/).

## Architecture

```text
UW + massive.com + xenon (IB WS + query) + FRED + Cleveland Fed + TreasuryDirect + CFTC + WGC + LBMA + GPR
                                    │
                                    ▼
                Sharded APScheduler workers  (uw × 2, massive × 2,
                                    │         ai-codex × 2, ai-claude × 2,
                                    ▼         ai-deepseek × 2, spot-ws: xenon→massive)
                  Postgres  option_wizard.uw_scan   (owner: argon_app)
                                    │
                                    ▼
                          FastAPI  read-only  :8400
                                    │
                                    ▼
                       Next.js 16 + React 19  :3001
```

Thirteen dev processes, one database, one schema. Workers are the only writers; the API is read-only; UI mutations cross through `/api/jobs` and are drained by the UW workers' 1-second rescan loop. Per-ticker work uses stable shard ownership and DB claiming (`FOR UPDATE SKIP LOCKED`), so two workers never duplicate provider calls.

- `src/uw_scan/worker/` — APScheduler jobs (full-scan, OHLC, spot-refresh, rescan-poll, nightly vol rollup, gold/rates cron, regime EOD + 5-min live, option-surface capture + IV canary, VRP macro entry-capture, data-freshness monitor, gap-healer, trade-insights queue) governed by a shared UW daily-budget governor
- `src/uw_scan/api/` — FastAPI routers split by domain; OpenAPI flows to `web/lib/types.ts` via `npm run gen:types`
- `src/uw_scan/models/` — Pydantic v2 contract models; `__init__.py` is export-only, implementations live in domain modules
- `src/uw_scan/storage/` — repository split by domain (audit, cockpit, flow, gex, gold, jobs, scan_runs, trade_insights_ai, volatility_v2, watchlist, option_surface, data_freshness, …); `repository.py` is assembly-only and is **never** extended with new query methods
- `src/uw_scan/sources/` — provider clients (`uw`, `massive`, `xenon_ws`, `xenon_query`, `fred`, `cleveland_fed`, `comex`, `lbma`, `wgc_*`, `cftc_cot`, `etf_holdings`, `lake`, …)
- `src/uw_scan/scanner/` — per-ticker detector pipeline (DCF / Dark Pool / EIC / GEX), ranking, discovery, gates, context
- `src/uw_scan/scanners/` — market-wide regime scanners (`cri`, `vcg`, `gex`, `grg`, `canary`, `market_tide`, live-quote variants)
- `src/uw_scan/backtest/` — shared walk-forward backtest harness (OOS gates, metrics, parameter sweep) · `src/uw_scan/chanlun/` — Chanlun port + sub-level lifecycle engine
- `web/app/` — RSC landing pages + client-island tabs for the stock detail surface
- `web/components/` — Argon-dark UI primitives, hand-rolled SVG charts
- `docs/superpowers/` — active specs + plans; completed work under `docs/superpowers/archive/`
- `docs/uw-samples/` — full UW OpenAPI spec + per-endpoint sample payloads (consult before adding any new UW fetcher)

Per-layer doctrine lives in `CLAUDE.md` files under `src/uw_scan/`, `web/`, and `tests/`.

## Data Source Priority (strict)

1. **Interactive Brokers** (via xenon) — primary live intraday spot feed (WS) + single-contract option greeks/IV (read-only query API)
2. **[Unusual Whales](https://unusualwhales.com)** — flow alerts, dark pool prints, IV surface, GEX, spot-exposure
3. **[massive.com](https://massive.com)** — OHLC and Polygon-backed fundamentals (project tier)
4. **FRED · Cleveland Fed · TreasuryDirect · CFTC TFF · WGC · LBMA · GPR · CME COMEX** — macro & rates & gold layers
5. **FMP** — auxiliary fundamentals

**Yahoo Finance is banned.** Any fallback that would reach Yahoo is treated as a bug. New UW fetchers are checked against [`docs/uw-samples/unusual_whales_api.md`](docs/uw-samples/unusual_whales_api.md) and real sample payloads in `docs/uw-samples/*.json` before integration — never against guessed schemas.

Per-source status, failure modes, and gating notes: [`src/uw_scan/sources/CLAUDE.md`](src/uw_scan/sources/) · gold lens framework: [`docs/research/gold-sdf-framework/CLAUDE.md`](docs/research/gold-sdf-framework/).

## Trade Insights AI

Three model execution paths share one orchestration loop. The API queues one `trade_insight_ai_analyses` row per enabled provider on POST; provider-pinned workers (`ai-codex`, `ai-claude`, `ai-deepseek`) claim only their own rows via `FOR UPDATE SKIP LOCKED` and run the appropriate runner. Each persisted analysis carries the exact prompt, prompt payload, output schema, structured outcome, and a Markdown audit view.

| Provider     | Runtime                                          | Auth                          | Notes                                                                                                                          |
| ------------ | ------------------------------------------------ | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Codex**    | Local `codex exec` subprocess                    | Local CLI sign-in             | Strict env allow-list — provider keys never reach the subprocess                                                               |
| **Claude**   | Local `claude --print` subprocess (locked flags) | OAuth keychain                | `ANTHROPIC_API_KEY` explicitly blocked so subscription auth wins; tools/slash-commands/MCP all disabled, no session persistence|
| **DeepSeek** | In-process `httpx` → `api.deepseek.com`          | `DEEPSEEK_API_KEY` env        | Thinking-enabled `deepseek-v4-pro` by default; SSE streaming mandatory (idle non-stream connections drop ~60 s)                |

The decomposed-trigger contract (`thesis_trigger` / `entry_trigger` / `invalidation` + `legs[]` with geometric validation) makes every thesis falsifiable. A nightly outcome worker captures snapshot_close + 1d/3d/5d/10d forward closes and resolves rows against the three triggers in direction-aware order; each row resolves to `target_hit`, `invalidation_hit`, `expired_no_resolution`, or stays `pending` until the window closes.

Worker env is frozen at fork time — rotating a provider key requires restarting the relevant `ai-*` worker process. The UI exposes `[Codex] [Claude]` tabs today; a `[DeepSeek]` tab is planned (the backend already persists `provider='deepseek'` rows).

Orchestration: [`src/uw_scan/worker/jobs/trade_insights_ai.py`](src/uw_scan/worker/jobs/) · runners: [`trade_insights_ai_runners.py`](src/uw_scan/worker/jobs/) · API + storage: [`api/routers/trade_insights.py`](src/uw_scan/api/routers/) + [`storage/trade_insights_ai.py`](src/uw_scan/storage/).

## Testing

- **Python:** `pytest` — workers, storage, scanners, sources, scoring; fresh DB per session via `pytest-postgresql`
- **Frontend:** `Vitest` — web logic, type contracts, component snapshots
- **E2E:** `Playwright` — browser workflows; artifacts under `output/playwright/`

```bash
uv run pytest                              # full python suite (excludes `live`)
uv run pytest -m live                      # live API tests (needs UW_SCAN_API_KEY)
cd web && npm test                          # Vitest
cd web && npx playwright test               # Playwright E2E
cd web && npm run gen:types                 # regenerate web/lib/types.ts from OpenAPI
```

UW / massive / FRED calls are mocked in unit tests. Live tests are marked `live` and excluded by default. Browser artifacts (screenshots, traces) belong in `output/playwright/` with descriptive names — never in the repo root.

## Services

| Service                          | Purpose                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------- |
| FastAPI (`:8400`)                | Read-only HTTP surface over `option_wizard.uw_scan`; mutations queue via `/api/jobs`     |
| Next.js 16 (`:3001`)             | Argon-dark terminal; RSC landing pages, client-island tabs                               |
| `uw` worker × 2                  | UW scan + rescan + flow-alerts loops with stable shard ownership                         |
| `massive` worker × 2             | Spot refresh + OHLC backfill, sharded by ticker                                          |
| `massive-ws` consumer            | Live spot WebSocket → Postgres — xenon IB (primary) / massive.com (automatic fallback)   |
| `ai-codex` worker × 2            | Trade Insights AI — Codex; provider-pinned row claim                                     |
| `ai-claude` worker × 2           | Trade Insights AI — Claude; provider-pinned row claim                                    |
| `ai-deepseek` worker × 2         | Trade Insights AI — DeepSeek; provider-pinned row claim                                  |

The Mac mini (`100.66.147.98`) hosts the shared production stack in **Docker** (`/opt/argon/compose.yml`); the engine-wide **Watchtower** auto-deploys new `:latest` images on each final tagged release (launchd retired 2026-07-08, prereleases never float `:latest`). MacBook can run fully local against `127.0.0.1` or point at the mini through a per-machine `.env.local` override. Deploy runbook: [`docs/runbooks/docker-deploy.md`](docs/runbooks/docker-deploy.md) · migration design: [`docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`](docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md).

## Glossary

| Term                   | Definition                                                                                            |
| ---------------------- | ----------------------------------------------------------------------------------------------------- |
| **GEX**                | Gamma exposure — net dealer gamma at a strike/spot. Flip = level where the net sign changes.          |
| **DEX**                | Delta exposure — dealer net delta. Sign indicates whether dealers buy or sell into rallies.           |
| **IVR**                | IV Rank — current ATM IV as a percentile of the trailing 252 sessions. High = expensive options.     |
| **VRP**                | Volatility Risk Premium — implied minus realized vol. Positive = options carry premium.               |
| **25Δ RR**             | 25-delta risk reversal — sign and magnitude of put-vs-call demand at the wings.                       |
| **DCF**                | Deep Conviction Flow — argon's flow-density / conviction detector.                                    |
| **EIC**                | Earnings IV Crush — vol-regime detector around scheduled earnings events.                             |
| **CRI**                | Crash Risk Index — CTA deleveraging + COR1M composite, ported from xenon.                             |
| **VCG**                | Vol-Curve Gauge — VIX-term + credit + skew composite.                                                 |
| **GRG**                | Gamma Rotation Gap — z-score of (SPY gamma-z − TLT gamma-z) over a 63-session window.                 |
| **5% Canary**          | Composite early-warning score for a ~5% SPX drawdown (tactical + structural vol + speed sub-scores). |
| **Market Tide**        | UW market-wide net options-flow tide (call vs. put premium) surfaced as a regime subtab.             |
| **Chanlun (缠论)**      | Price-structure overlay — 笔 (strokes) / 中枢 (pivots) / 买卖点 (buy-sell points), trust-tiered.        |
| **Option surface grid** | Durable full-chain daily IV/greeks snapshot (`option_surface_grid_daily`), forward-only accrual.    |
| **Watchlist candidates** | Scanner output, full detector suite, restricted to watchlist tickers.                               |
| **Discovered tickers** | Scanner output, DCF-only, sourced from the market-wide flow-alerts feed.                              |
| **Outcome ledger**     | Per-thesis resolution against forward closes; substrate for Bayesian prior reweighting.               |

## Status

Active development (2026-05-12 → present); current release **v0.10.8**. Argon is the analytics/decision surface of a five-repo personal quant desk (livewire → signal-lab → apex → **argon** → xenon); full vision and the Stage-1 goal ladder live in [`CLAUDE.md`](CLAUDE.md) and [`docs/masterplan/`](docs/masterplan/).

Recent milestones (since v0.7):

- **Docker cutover (v0.8, 2026-07-08)** — the mini stack moved from launchd to Docker + GHCR + Watchtower auto-deploy; releases are tag-driven via `scripts/release/cut.sh`.
- **Xenon integration** — IB realtime WS as the primary intraday spot feed (massive fallback) plus a read-only query API for single-contract IB option greeks/IV.
- **Regime expansion** — GRG, the 5% Canary subtab, Market Tide, a VRP macro short-vol sizing signal (+ forward entry-capture), live 5-min CRI/VCG off the WS feed, and dispersion context on CRI.
- **Technicals tab** — dual MACD + dimensionless RSI and a Chanlun (缠论) price overlay (v1 → v2 线段/段级中枢 → Phase B 区间套 lifecycle → trust-styling), with a live intraday badge.
- **Durable option-surface capture** — a nightly full-chain IV/greeks grid with an IB-vs-UW IV canary; the grid spans 2025-12-26→present and accrues forward-only.
- **Ops hardening** — a data-freshness monitor + gap-healer across the warm store and a shared UW daily-budget governor (live/research pools), surfaced on a fuller `/api/health`.

Active specs/plans under [`docs/superpowers/`](docs/superpowers/); completed work under [`docs/superpowers/archive/`](docs/superpowers/archive/); research notes under [`docs/research/`](docs/research/); full history in [`CHANGELOG.md`](CHANGELOG.md).

---

Built with `Python 3.13` · `FastAPI` · `Pydantic v2` · `psycopg 3` · `APScheduler 3` · `Next.js 16` · `React 19` · `TypeScript` · `Vitest` · `Playwright` · `pytest` · `pytest-postgresql` · `uv`.
