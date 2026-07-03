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

## Xenon read-only query API (IB option greeks)

Separate from the WS spot feed: a request/response HTTP API (`sources/xenon_query.py`) for **single-contract IB option greeks** via `GET /options/greeks?symbol=&expiry=YYYYMMDD&strike=&right=`. Each call spawns an IB snapshot subprocess (~2–5 s) and consumes one of the shared ~100-line IB market-data cap — **never bulk-poll**; quote serially with a per-mark budget. Response: top-level `bid`/`ask` (nullable) + nested `greeks{impliedVol,delta,gamma,vega,theta,undPrice}` (whole object may be `null`, still HTTP 200). **IB `theta` is per-DAY** and IB `vega` is per-1% vol — argon now stores IB's native greeks as the **primary** source (rescaled to its BS column convention: vega ×100, theta ×365), with BS-from-marked-IV as the backup when IB returns no greek set. Consumers: the surface IV canary (`fetch_ib_option_iv`) and VRP entry-capture (`fetch_ib_option_quote`).

- `XENON_QUERY_API_URL` — default `http://127.0.0.1:8321` (the mini's authenticated localhost port — verified listening; the old `:8421` was dead, silently no-op'ing the canary). MacBook dev points over Tailscale: `http://100.66.147.98:8321`.
- `XENON_QUERY_API_KEY` — **required** even on localhost (`X-API-Key` header; missing/wrong → HTTP 401). Lives in xenon's `/opt/xenon/.env` on the mini; copy the same value into the mini's argon `.env`. Without it, the never-raise clients swallow the 401 → every leg silently falls back to `source='uw'`. Set it once in the mini `.env` (persists across deploys; worker kickstart picks it up).

The worker freezes env at fork — rotating `XENON_QUERY_API_KEY`/`_URL` needs a worker restart (kickstart).

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
- **Persist every research/backtest trace before the process exits** — any sweep, backtest, or parameter search must save its *full* result set (every config + every metric, not just the headline) to a durable artifact: a Postgres table for productionized signals, or a committed file/notebook under `docs/research/` for exploratory runs. stdout-only is data loss — a number you can't reproduce from a saved trace did not happen. Always record the exact reproduce command (script path + args/seed). This rule exists because a believed-but-unsaved "Sharpe ~2.0" cost a day chasing a figure that the saved trace later proved was never real (the true headline is 1.65)
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
- **Worktrees live in `.worktrees/<branch-slug>/`** — the project-root `.worktrees/` directory is the only canonical location. Already gitignored. Do not create worktrees under `.claude/worktrees/`, `$HOME/projects/<repo>-worktrees/`, or anywhere else; if a skill defaults elsewhere, override it. When you finish with a worktree, `git worktree remove <path>` it — stale worktrees holding `main` block `git checkout main` in the primary repo
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
| VRP macro short-vol signal (EOD + live) | `reports/vrp_macro_signal.py` (`current_macro_signal`, `current_macro_signal_live`) + `storage/vrp_macro_signal.py` (`basis` col) + `worker/jobs/{vrp_macro_signal,regime_live}.py` + `api/routers/regime.py` (`/vrp-macro-signal`, `/vrp-macro-signal/live`) + `web/components/regime/MacroShortVolSubTab.tsx`; migrations 083/084. **Live = SPX only**, piggybacks the 5-min `regime_live_scan` (no new job); EOD stays `vrp_macro_signal_refresh` @03:45 ET |
| VRP harvest markout (is rich vol sellable) | `src/uw_scan/reports/vrp_markout.py` + `storage/vrp_markout.py` + `worker/jobs/vrp_markout.py` + `api/routers/regime.py` (`/vrp-harvest`) + migration `079`; nightly 18:50 ET (massive-0); spec `docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md` |
| VRP macro entry-capture (forward markout) | `reports/vrp_macro_entry.py` (`resolve_entry_contracts`, `quote_leg` — **xenon/IB-primary NBBO+IV+native greeks → UW fallback → greeks IB-native primary (rescaled to BS convention: vega ×100, theta ×365), BS-from-IV backup**) + `worker/jobs/vrp_macro_entry.py` (daily birth + 8 marks/day, 30-cal-day EOD taper) + `storage/vrp_macro_entry.py` + `api/models/vrp_macro_entry.py` + `api/routers/regime.py` (`/vrp-macro-signal/entry/{preview,capture}` — preview is zero-IB/zero-UW) + `web/components/regime/MacroShortVolCard.tsx` (strike/ETD panel + Capture button); migration `085`; 8 ET crons (massive-0, gated `vrp_macro_entry_capture_enabled`); plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`. **Deploy:** set `XENON_QUERY_API_KEY` in the mini's argon `.env` (URL now defaults to the mini's `:8321`) or the IB path silently no-ops to `source='uw'`. **Strike-grid cache** (`vrp_macro_entry_grid`, migration `088`): nightly `vrp_macro_entry_grid_refresh` @03:50 ET caches the real UW-listed strikes so the RTH birth reads the cache and makes **zero UW calls** (the inline-UW birth 429'd daily and never persisted); plan `docs/superpowers/plans/2026-06-25-vrp-macro-entry-grid-cache.md` |
| Gold Compass — code | `api/routers/gold.py` + `storage/gold_etf.py` + `worker/jobs/gold_jobs.py` + `sources/{fred,gpr,lbma,comex,etf_holdings,uw_gold_options,cftc_cot,wgc_etf,wgc_cb}.py` + `web/app/gold/page.tsx` (+ `gold/replay/[date]/`) + `web/components/gold/*` |
| Gold Compass — research / sources docs | `docs/research/gold-sdf-framework/CLAUDE.md` (3-lens model, status vs. shipped, deferred sources) + `src/uw_scan/sources/CLAUDE.md` (per-source status + failure modes) |
| Index dealer cockpit (SPX/SPY/QQQ/IWM) | `api/routers/cockpit.py` + `web/app/cockpit/[ticker]/page.tsx` |
| Stock detail page | `web/app/stock/[ticker]/page.tsx` + `components/stock/tabs/*` |
| Per-stock short-vol card (single-name sibling of macro short-vol) | `reports/stock_short_vol.py` (`decide_short_vol`/`build_short_vol`) + `models/stock.py` (`StockShortVol`, `SingleStockReport.short_vol`) + `web/components/stock/panels/ShortVolPanel.tsx` + `web/components/stock/tabs/MarketStructureTab.tsx`; read-time reshape of `vrp_daily` gated by `reports/vrp_gate.py`; plan `docs/superpowers/plans/2026-06-24-stock-short-vol-card.md` |
| Watchlist landing | `web/app/page.tsx` + `components/watchlist/CardGrid.tsx` |
| Backtest harness (engine/gates/metrics/sweep) | `src/uw_scan/backtest/` + `storage/backtest_repository.py` + migration `095`; consumers: `reports/{skew_markout,vrp_markout_core}.py`, `scripts/_vrp_macro_param_sweep.py`; plan `docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md` |
| Release pipeline (versioning + workflow) | `VERSION` + `CHANGELOG.md` + `scripts/release/{_lib.sh,version_sync_check.py,cut.sh}` + `.github/workflows/release.yml` |
| Auto-deploy to the mini | `scripts/deploy/macmini-deploy-poller.sh` + `config/templates/com.argon.deploy-poller.plist.template` + `scripts/deploy/macmini-prod.sh`; runbook `docs/runbooks/release.md` |
