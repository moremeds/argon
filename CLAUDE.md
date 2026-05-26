# CLAUDE.md

Guidance for Claude Code working in this repo. Subdirectory `CLAUDE.md` files cover layer-specific rules.

## What this is

Per-ticker options analytics, watchlist-driven. Three processes share a single Postgres:

- **Next.js 16 web** (`web/`, port 3001) — Argon dark theme, RSC for landing pages, client islands for tabs
- **FastAPI** (`src/uw_scan/api/`, port 8400) — read-only over the warm store, mutations only via `/jobs`
- **APScheduler worker** (`src/uw_scan/worker/`) — full-scan / OHLC / spot-refresh / rescan-poll / nightly vol rollup

Postgres `option_wizard` DB, schema `uw_scan`. UW (Unusual Whales) is the primary data source; massive.com supplies OHLC. **Never fall back to Yahoo.**

## Tech stack

- Python 3.13 via `uv` only (no bare `python`/`pip`/activated venvs)
- FastAPI + Pydantic v2, psycopg 3, APScheduler 3
- Next.js 16 + React 19, TypeScript, hand-rolled SVG charts (no chart library)
- Vitest + Playwright (web), pytest + pytest-postgresql (Python)
- Types flow API → client via `openapi-typescript` → `web/lib/types.ts`

## Daily commands

```bash
uv sync --extra postgres          # install
bash scripts/migrate.sh           # apply SQL migrations (idempotent)
bash scripts/dev.sh               # run web, API, 2 UW workers, and 2 massive workers
uv run pytest                     # python tests
cd web && npm run test            # vitest
cd web && npm run gen:types       # regenerate types.ts after API change
```

## Trade Insights AI (V1.5)

Local Codex CLI and Claude CLI are the two model execution paths for Trade Insights AI analysis. The API queues persisted `trade_insight_ai_analyses` rows (one per enabled provider); per-provider workers run the respective CLI in a locked-down sandbox and store the exact prompt, prompt payload, output schema, produced timestamp, structured outcome (resolved-model preserved post-hoc), and Markdown audit view. The web stock page renders `[Codex] [Claude]` tabs with independent per-provider polling.

Environment (Codex):

- `TRADE_INSIGHTS_AI_ENABLED` — Codex kill switch; default **true**
- `TRADE_INSIGHTS_AI_MODEL` — optional Codex model alias; blank → resolved model captured or `codex-default`
- `TRADE_INSIGHTS_AI_TIMEOUT_SECONDS` — Codex subprocess timeout, default 300

Environment (Claude):

- `TRADE_INSIGHTS_AI_CLAUDE_ENABLED` — Claude kill switch; default **true**
- `TRADE_INSIGHTS_AI_CLAUDE_MODEL` — optional Claude model alias; blank → resolved canonical id from envelope (e.g. `claude-opus-4-7`) or `claude-default`
- `TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS` — Claude subprocess timeout, default 300

Environment (shared):

- `TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES` — structured output cap, default 262144
- `TRADE_INSIGHTS_AI_POLL_SECONDS` — worker polling interval, default 3

Worker roles: `ai-codex` and `ai-claude` (provider-pinned, recommended); legacy `ai` (claims any provider). The Claude runner uses `claude --print` with locked-down flags (`--tools "" --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers": {}}' --no-session-persistence`) and reads OAuth keychain auth — never `ANTHROPIC_API_KEY` (the env allow-list strips it so subscription auth wins).

## Standing rules

- **uv only** — `uv run pytest`, never `pytest` directly
- **Persist analytical results to Postgres** — vol/scan/regime outputs land in tables, never in-memory-only
- **No naked shorts** in any strategy/trade-plan code — defined-risk only
- **Data source priority**: IB → UW → FMP → massive (OHLC). Yahoo is banned
- **No secrets to local Codex subprocesses** — do not pass UW/FMP/Massive keys, DB credentials, or unrelated app secrets to `codex exec`
- **Never commit without an explicit user request.** Draft first, wait
- **Big projects use milestone commits** — when the user has explicitly requested commits for a large project/task, commit each closed milestone after its relevant verification before continuing
- **Always open a PR before merging to main.** `git push origin main` is forbidden
- **Branch names** default to type prefixes: `feat/` for features, `fix/` for bug fixes, `chore/` for maintenance, and `misc/` for other work. Do not default to a `codex/` prefix
- **Never add `Co-Authored-By: Claude` trailers** to commits
- **Migrations are idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). No tracking table — re-running is a no-op
- **Live API tests** are marked `live` and need `UW_SCAN_API_KEY`; default `pytest` excludes them
- **Screenshots and browser artifacts** go under `output/playwright/` with descriptive names. Do not create ad hoc screenshots, logs, snapshots, or downloaded browser artifacts in the repo root; keep them in `output/playwright/` so cleanup and review evidence stay manageable
- **Module size budget** — target <500 lines per Python file; at 1000+ lines stop adding methods and propose a split first. `repository.py` reached 5000+ lines because the line was never drawn — don't repeat. Split by domain seam (one module per cohesive set of methods), not by technical layer. Cite this rule in any PR that grows a file past 1000 lines without a split plan
- **API model refactors preserve contract identity** — `src/uw_scan/models/` may be split by domain, but `from uw_scan.models import X`, `models.__all__`, Pydantic field/default/config surfaces, and OpenAPI component names must stay stable unless the PR is explicitly an API contract change. When moving Pydantic models out of the package root, preserve public model `__module__` metadata and run the export, field-surface, and OpenAPI snapshot checks before review
- **AGENTS.md** still lives at the root for Codex; keep both files in sync when policy changes

## Where to look first

| Need | Look at |
|---|---|
| Active specs / plans | `docs/superpowers/specs/`, `docs/superpowers/plans/`; completed specs/plans live under `docs/superpowers/archive/{specs,plans}/` |
| Research notes | `docs/research/` |
| API surface | `src/uw_scan/api/server.py` + `routers/*` |
| API contract models | `src/uw_scan/models/` (`__init__.py` is export-only; implementations live in domain modules) |
| Persistence — aggregate shim | `src/uw_scan/storage/repository.py` (thin `Repository` assembly + compatibility re-exports; do not add query methods here) |
| Persistence — domain modules | `src/uw_scan/storage/{audit,cockpit,external_api,fetchers,flow,gex,gold,gold_etf,health,jobs,market_data,matrix_state,options,rates_repository,scan_outputs,scan_results,scan_runs,trade_insights_ai,volatility_raw,volatility_v2,watchlist,ws_consumer_state}.py`. New domains go in their own module/mixin and are added to `repository.py` only for assembly/re-export compatibility |
| Scheduled jobs | `src/uw_scan/worker/scheduler.py` |
| UW endpoints (integrated) | `src/uw_scan/api/endpoints.py` + `sources/uw.py` |
| UW API reference (full surface) | `docs/uw-samples/unusual_whales_api.md` (human-readable) + `docs/uw-samples/unusual_whales_api_spec.yaml` (OpenAPI) — consult before adding any new UW fetcher |
| UW sample payloads | `docs/uw-samples/*.json` — real responses for each integrated endpoint, with `_shape-summary.md` |
| Volatility derivers | `src/uw_scan/cards/vol_series.py`, `reports/volatility_series.py` |
| Scanner (detectors + ranking + discovery) | `src/uw_scan/scanner/` (pipeline, signals, ranking, discovery, gates, context) + `api/routers/scanner.py` + `web/app/scanner/page.tsx` |
| Regime indicators (CRI / GEX / VCG) | `src/uw_scan/scanners/{cri,gex,vcg}.py` + `api/routers/regime.py` + `web/app/regime/page.tsx` + `web/components/regime/*` |
| Gold Compass — code | `api/routers/gold.py` + `storage/gold_etf.py` + `worker/jobs/gold_jobs.py` + `sources/{fred,gpr,lbma,comex,etf_holdings,uw_gold_options,cftc_cot,wgc_etf,wgc_cb}.py` + `web/app/gold/page.tsx` (+ `gold/replay/[date]/`) + `web/components/gold/*` |
| Gold Compass — research / sources docs | `docs/research/gold-sdf-framework/CLAUDE.md` (3-lens model, status vs. shipped, deferred sources) + `src/uw_scan/sources/CLAUDE.md` (per-source status + failure modes) |
| Index dealer cockpit (SPX/SPY/QQQ/IWM) | `api/routers/cockpit.py` + `web/app/cockpit/[ticker]/page.tsx` |
| Stock detail page | `web/app/stock/[ticker]/page.tsx` + `components/stock/tabs/*` |
| Watchlist landing | `web/app/page.tsx` + `components/watchlist/CardGrid.tsx` |
| Trade Insights AI — orchestration | `src/uw_scan/worker/jobs/trade_insights_ai.py` (claim → dispatch → persist; RUNNERS registry, `provider_filter` param, per-provider heartbeats) |
| Trade Insights AI — provider runners | `src/uw_scan/worker/jobs/trade_insights_ai_runners.py` (`AiProviderRunner` Protocol, `_format_runner_failure`, `_runner_child_env`), `trade_insights_codex_runner.py`, `trade_insights_claude_runner.py` |
| Trade Insights AI — API + storage | `api/routers/trade_insights.py` (POST paired stubs, /latest keyed pair) + `storage/trade_insights_ai.py` (provider param on every read/write, `find_latest_*_per_provider`, `count_queued_*_by_provider`) |
| Trade Insights AI — UI tabs | `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` ([Codex] [Claude] tabs, per-provider polling, state badges) |
