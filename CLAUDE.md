# CLAUDE.md

Guidance for Claude Code working in this repo. Subdirectory `CLAUDE.md` files cover layer-specific rules.

## What this is

Per-ticker options analytics, watchlist-driven. Three processes share a single Postgres:

- **Next.js 16 web** (`web/`, port 3001) — Argon dark theme, RSC for landing pages, client islands for tabs
- **FastAPI** (`src/uw_scan/api/`, port 8400) — read-only over the warm store, mutations only via `/jobs`
- **APScheduler worker** (`src/uw_scan/worker/`) — full-scan / OHLC / spot-refresh / rescan-poll / nightly vol rollup

Postgres schema `uw_scan`, owned by role `argon_app` (NOSUPERUSER). UW (Unusual Whales) is the primary data source; xenon's IB realtime WS is the primary intraday spot feed (massive WS is the automatic fallback); massive.com supplies daily OHLC. **Never fall back to Yahoo.**

**Three-tier DB isolation** — `uw_scan.config._enforce_db_isolation` refuses to start on a `(host, db_name)` mismatch (override with `UW_SCAN_ALLOW_DB_MISMATCH=1` for one-off scripts):

| Host | DB name | Writer | Reset |
|------|---------|--------|-------|
| `100.66.147.98` (Mac mini, Tailscale) | `option_wizard` | macmini launchd stack only | persistent (prodlike) |
| `127.0.0.1` (MacBook / CI) | `option_wizard_local` | local `bash scripts/dev.sh` | persistent (dev-owned) |
| either host | `option_wizard_test` | `uv run pytest` | wiped per-fixture (DROP SCHEMA CASCADE) |

MacBook runs fully local by default. To point at the mini for a browse session, `.env.local` must override BOTH `UW_SCAN_DB_HOST=100.66.147.98` AND `UW_SCAN_DB_NAME=option_wizard` (otherwise the tripwire blocks mini+local-name). See `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`.

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

## Release procedure

Tag-driven, launchd-native (no Docker). Cut a release with
`scripts/release/cut.sh prepare [patch|minor|major]` (opens a release PR) → merge
→ `scripts/release/cut.sh tag` (pushes `vX.Y.Z`). The tag fires
`.github/workflows/release.yml` (verify → publish GitHub Release). The mini's
`com.argon.deploy-poller` (every 120s) deploys the latest **published,
non-prerelease** Release via `scripts/deploy/macmini-prod.sh`. Prereleases
(`vX.Y.Z-rc1`) verify + publish but never auto-deploy. See
`docs/runbooks/release.md`.

## Live spot WS feed (xenon primary / massive fallback)

The spot WS consumer (`uw_scan.worker.massive_ws_consumer` — module name retained for plist/dev.sh compat) connects to xenon's IB realtime server as the primary live feed and falls back to massive's WS automatically. Xenon streams 24h whenever IB Gateway is connected (massive only delivers Mon–Fri 04:00–20:00 ET). Failover triggers: connect failure, `ib_connected: false` at connect, or in-session tick silence (watchdog armed only inside massive's feed window — failing over outside it buys nothing). While on massive, a probe re-tries xenon every retry interval and switches back on recovery. `watchlist_card.spot_source` / `intraday_quote.source` tag each row (`xenon_ws` | `massive.com_ws`); `/api/health` `ws_consumer.active_source` shows the live feed.

- `XENON_WS_ENABLED` — primary-feed switch; default **false**
- `XENON_WS_URL` — default `ws://127.0.0.1:8765` (right for the mini, where xenon runs). MacBook dev points over Tailscale: `ws://100.66.147.98:8765`
- `XENON_WS_PORT_FILE` — default `/tmp/xenon-ib-realtime.json`; xenon writes its actual port there if 8765 is taken. Only consulted when the URL host is localhost; empty string disables
- `XENON_WS_RETRY_PRIMARY_SECONDS` — stay on massive this long after a xenon failure before re-probing; default 300
- `XENON_WS_QUIET_FAILOVER_SECONDS` — in-session silence threshold before failover; default 120; 0 disables
- `REGIME_WS_SYMBOLS` — always-subscribed regime symbols beyond the watchlist; default `VIX,VVIX,VIX3M,COR1M,SPX,HYG`. Feeds the live CRI/VCG compute (`/api/regime/{cri,vcg}/live`) and the 5-min `regime_live_scan` job (basis='live' rows in cri/vcg_snapshots; hourly :20/:25 scans stay the canonical basis='eod' dailies). Quotes older than `REGIME_LIVE_QUOTE_MAX_AGE_SECONDS` (default 900) are ignored — live endpoints then fall back to the EOD snapshot. `REGIME_LIVE_SCAN_INTERVAL_MINUTES` (default 5) sets the snapshot cadence. Nightly 03:40 ET `regime_live_validation` diffs the live-captured close vs the lake close (>0.5% → WARN). Massive fallback is stocks-only: indices stall during failover, HYG keeps ticking.

The worker process freezes env at fork — rotating any `XENON_*` value requires restarting the spot-WS consumer process. Subscription mapping: stocks/ETFs → xenon `symbols` (IB SMART); index symbols (SPX/VIX/VVIX/COR1M/…) → `indexes` with exchange CBOE — extend `XENON_INDEX_SYMBOLS` in `sources/xenon_ws.py` when the watchlist grows a new index.

## Trade Insights AI (V1.5)

Local Codex CLI, Claude CLI, and DeepSeek HTTP API are the three model execution paths for Trade Insights AI analysis. The API queues persisted `trade_insight_ai_analyses` rows (one per enabled provider); per-provider workers run the respective runner and store the exact prompt, prompt payload, output schema, produced timestamp, structured outcome (resolved-model preserved post-hoc), and Markdown audit view. The DeepSeek path uses function-calling with `strict: true` (Beta) against `https://api.deepseek.com/chat/completions` and reads `DEEPSEEK_API_KEY` from the worker env. The runner runs DeepSeek in **thinking-enabled** mode without forced `tool_choice` — the model voluntarily calls the structured-output tool, and the reasoning trace is captured into `provider_metadata_jsonb.reasoning_content` for inspection. SSE streaming is mandatory (DeepSeek closes idle non-streaming connections at ~60 s, well before our ~350 KB prompts finish generating). Cost: thinking adds ~2× output tokens per call vs non-thinking; same per-token rate. The web stock page renders `[Codex] [Claude]` tabs with independent per-provider polling — a `[DeepSeek]` tab is planned; the backend persists `provider='deepseek'` rows today but the UI does not yet surface them.

Environment (Codex):

- `TRADE_INSIGHTS_AI_ENABLED` — Codex kill switch; default **true**
- `TRADE_INSIGHTS_AI_MODEL` — optional Codex model alias; blank → resolved model captured or `codex-default`
- `TRADE_INSIGHTS_AI_TIMEOUT_SECONDS` — Codex subprocess timeout, default 300

Environment (Claude):

- `TRADE_INSIGHTS_AI_CLAUDE_ENABLED` — Claude kill switch; default **true**
- `TRADE_INSIGHTS_AI_CLAUDE_MODEL` — optional Claude model alias; blank → resolved canonical id from envelope (e.g. `claude-opus-4-7`) or `claude-default`
- `TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS` — Claude subprocess timeout, default 300

Environment (DeepSeek):

- `TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED` — DeepSeek kill switch; default **true**
- `TRADE_INSIGHTS_AI_DEEPSEEK_MODEL` — optional DeepSeek model alias; blank → `deepseek-v4-pro` (top-tier thinking variant — quality default). Set to `deepseek-v4-flash` for the cheap/fast non-thinking alternative. The legacy `deepseek-chat` / `deepseek-reasoner` names still resolve (aliased to v4-flash's non-thinking / thinking modes) but are deprecated and retire 2026-07-24. The runner sends `thinking: {type: enabled}` and omits `tool_choice` — v4-pro rejects forced tool_choice while thinking, but voluntarily calls the structured-output tool. `reasoning_content` is persisted to `provider_metadata_jsonb`.
- `TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS` — DeepSeek HTTP timeout, default 300
- `TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT` — parallel workers claiming deepseek rows, default 2. **Lower to 1 if DeepSeek 429s** — DeepSeek's rate ceiling is provider-side and may be below your codex/claude ceilings.
- `DEEPSEEK_API_KEY` — bearer token; read in-process at call time (no subprocess env-allow-list dance)

**Worker env rotation:** APScheduler workers freeze their env at fork time. Rotating `DEEPSEEK_API_KEY` (or any env above) requires restarting the `ai-deepseek` worker processes — the running process will keep using the boot-time value. The same applies to `ai-codex` / `ai-claude` workers.

Environment (shared):

- `TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES` — structured output cap, default 262144
- `TRADE_INSIGHTS_AI_POLL_SECONDS` — worker polling interval, default 3

Worker roles: `ai-codex`, `ai-claude`, and `ai-deepseek` (provider-pinned, recommended); legacy `ai` (claims any provider). The Claude runner uses `claude --print` with locked-down flags (`--tools "" --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers": {}}' --no-session-persistence`) and reads OAuth keychain auth — never `ANTHROPIC_API_KEY` (the env allow-list strips it so subscription auth wins). The DeepSeek runner is in-process HTTP (`httpx`), not a subprocess — `_runner_child_env` does not apply, but `DEEPSEEK_API_KEY` is still scoped to the worker process and not echoed in error messages.

## Standing rules

- **uv only** — `uv run pytest`, never `pytest` directly
- **Persist analytical results to Postgres** — vol/scan/regime outputs land in tables, never in-memory-only
- **No naked shorts** in any strategy/trade-plan code — defined-risk only
- **Data source priority**: IB → UW → FMP → massive (OHLC). Yahoo is banned
- **Massive WS bypasses system proxies** — `MassiveWsClient` passes `proxy=None` to `websockets.connect`; the market-data stream must never inherit macOS SOCKS/HTTP proxy settings (`python-socks` is not installed, so an inherited proxy kills every connect). The configured feed is ~15-min delayed, so WS-consumer health keys on `last_flush_at` (is the consumer alive?), not tick event time
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
| Live spot WS feed (xenon primary / massive fallback) | `src/uw_scan/sources/{xenon_ws,massive_ws}.py` + `worker/massive_ws_consumer.py` + `worker/ws_db_writer.py`; active feed: `/api/health` `ws_consumer.active_source` |
| UW endpoints (integrated) | `src/uw_scan/api/endpoints.py` + `sources/uw.py` |
| UW API reference (full surface) | `docs/uw-samples/unusual_whales_api.md` (human-readable) + `docs/uw-samples/unusual_whales_api_spec.yaml` (OpenAPI) — consult before adding any new UW fetcher |
| UW sample payloads | `docs/uw-samples/*.json` — real responses for each integrated endpoint, with `_shape-summary.md` |
| Volatility derivers | `src/uw_scan/cards/vol_series.py`, `reports/volatility_series.py` |
| Scanner (detectors + ranking + discovery) | `src/uw_scan/scanner/` (pipeline, signals, ranking, discovery, gates, context) + `api/routers/scanner.py` + `web/app/scanner/page.tsx` |
| Regime indicators (CRI / GEX / VCG) | `src/uw_scan/scanners/{cri,gex,vcg}.py` + `api/routers/regime.py` + `web/app/regime/page.tsx` + `web/components/regime/*` |
| Regime live CRI/VCG (WS quotes) | `src/uw_scan/scanners/live_quotes.py` + `scanners/{cri,vcg}.py` `run_live` + `worker/jobs/regime_live.py` + `api/routers/regime.py` (`/cri/live` etc.) + `web/components/regime/MultiPanelGrid.tsx` |
| VRP harvest markout (is rich vol sellable) | `src/uw_scan/reports/vrp_markout.py` + `storage/vrp_markout.py` + `worker/jobs/vrp_markout.py` + `api/routers/regime.py` (`/vrp-harvest`) + migration `079`; nightly 18:50 ET (massive-0); spec `docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md` |
| Gold Compass — code | `api/routers/gold.py` + `storage/gold_etf.py` + `worker/jobs/gold_jobs.py` + `sources/{fred,gpr,lbma,comex,etf_holdings,uw_gold_options,cftc_cot,wgc_etf,wgc_cb}.py` + `web/app/gold/page.tsx` (+ `gold/replay/[date]/`) + `web/components/gold/*` |
| Gold Compass — research / sources docs | `docs/research/gold-sdf-framework/CLAUDE.md` (3-lens model, status vs. shipped, deferred sources) + `src/uw_scan/sources/CLAUDE.md` (per-source status + failure modes) |
| Index dealer cockpit (SPX/SPY/QQQ/IWM) | `api/routers/cockpit.py` + `web/app/cockpit/[ticker]/page.tsx` |
| Stock detail page | `web/app/stock/[ticker]/page.tsx` + `components/stock/tabs/*` |
| Watchlist landing | `web/app/page.tsx` + `components/watchlist/CardGrid.tsx` |
| Trade Insights AI — orchestration | `src/uw_scan/worker/jobs/trade_insights_ai.py` (claim → dispatch → persist; RUNNERS registry, `provider_filter` param, per-provider heartbeats) |
| Trade Insights AI — provider runners | `src/uw_scan/worker/jobs/trade_insights_ai_runners.py` (`AiProviderRunner` Protocol, `_format_runner_failure`, `_runner_child_env`), `trade_insights_codex_runner.py`, `trade_insights_claude_runner.py` |
| Trade Insights AI — API + storage | `api/routers/trade_insights.py` (POST paired stubs, /latest keyed pair) + `storage/trade_insights_ai.py` (provider param on every read/write, `find_latest_*_per_provider`, `count_queued_*_by_provider`) |
| Trade Insights AI — UI tabs | `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` ([Codex] [Claude] tabs, per-provider polling, state badges) |
| Release pipeline (versioning + workflow) | `VERSION` + `CHANGELOG.md` + `scripts/release/{_lib.sh,version_sync_check.py,cut.sh}` + `.github/workflows/release.yml` |
| Auto-deploy to the mini | `scripts/deploy/macmini-deploy-poller.sh` + `config/templates/com.argon.deploy-poller.plist.template` + `scripts/deploy/macmini-prod.sh`; runbook `docs/runbooks/release.md` |
