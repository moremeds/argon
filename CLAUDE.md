# CLAUDE.md

Guidance for Claude Code working in this repo. Subdirectory `CLAUDE.md` files cover layer-specific rules.

## Mission

Argon is the options/flow analytics cockpit of a five-repo personal quant desk:
livewire (data lake) → signal-lab (gated research) → apex (signal engine) →
**argon** (analytics/decision surface) → xenon (broker terminal, human executes).
Full vision, blockers, and rationale: `docs/masterplan/2026-07-12-stack-vision-blockers-review.md`; actionable per-component plan: `docs/masterplan/2026-07-12-stack-master-plan.md`.

Goal ladder (adopted 2026-07-12; each stage's exit criteria gate the next stage's risk-bearing work):

1. **Trustworthy foundation** *(current)* — honest data (corporate-action-adjusted prices in livewire), safe order path (xenon), durable options-surface accrual, ops/health patrol agent. **Minimal deliverable: signal→alert pipeline** — alert bar < trade bar, so ship alerts on existing signals (VRP macro state flips, CRI/VCG regime transitions, ops staleness) without waiting for a promoted signal.
2. **Self-tending desk** — agent harness runs research/maintenance loops; execution-realism gate added to signal-lab promotion; first promoted signal with a live shadow record.
3. **Proposal desk** *(aim, not commitment)* — agents stage sized, defined-risk order proposals; the operator disposes with one click.
4. **Mandate-based autonomy** *(ceiling)* — size-capped, revocable standing mandates for strategies with long live records. Full autonomy is explicitly NOT the goal.

Invariants at every stage: defined-risk only / no naked shorts; every mutating agent action routes through a gate; persist everything to durable storage.

Argon's Stage-1 lane: options analytics + surface capture (`option_surface_grid_daily` spans 2025-12-26→present under UW's ~180-day window, accrues forward-only — every uncaptured night is lost) + the alert pipeline v1. Research aim: the options/vol/flow surface is the desk's structural-advantage hunting ground — prefer it over crowded daily equity technicals.

## What this is

Per-ticker options analytics, watchlist-driven. Three processes share a single Postgres:

- **Next.js 16 web** (`web/`, port 3001) — Argon dark theme, RSC for landing pages, client islands for tabs
- **FastAPI** (`src/uw_scan/api/`, port 8400) — read-only over the warm store, mutations only via `/jobs`
- **APScheduler worker** (`src/uw_scan/worker/`) — full-scan / OHLC / spot-refresh / rescan-poll / nightly vol rollup

Postgres schema `uw_scan`, owned by role `argon_app` (NOSUPERUSER). UW (Unusual Whales) is the primary data source; xenon's IB realtime WS is the primary intraday spot feed (massive WS is the automatic fallback); massive.com supplies daily OHLC. **Never fall back to Yahoo.**

**Three-tier DB isolation** — `uw_scan.config._enforce_db_isolation` refuses to start on a `(host, db_name)` mismatch (override with `UW_SCAN_ALLOW_DB_MISMATCH=1` for one-off scripts):

| Host | DB name | Writer | Reset |
|------|---------|--------|-------|
| `127.0.0.1` on the Mac mini | `option_wizard` | macmini launchd stack only | persistent (prodlike) |
| `127.0.0.1` (MacBook / CI) | `option_wizard_local` | local `bash scripts/dev.sh` | persistent (dev-owned) |
| either host | `option_wizard_test` | `uv run pytest` | wiped per-fixture (DROP SCHEMA CASCADE) |

The Mac mini `.env` uses `UW_SCAN_DB_HOST=127.0.0.1`, `UW_SCAN_DB_NAME=option_wizard`, and `UW_SCAN_ALLOW_DB_MISMATCH=1` for the same-host prodlike route. MacBook runs fully local by default. To point at the mini for a browse session, `.env.local` must override BOTH `UW_SCAN_DB_HOST=100.66.147.98` AND `UW_SCAN_DB_NAME=option_wizard` (otherwise the tripwire blocks mini+local-name). See `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`.

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

Tag-driven, Docker on the mini (launchd retired 2026-07-08). Cut a release with
`scripts/release/cut.sh prepare [patch|minor|major]` (opens a release PR) → merge
→ `scripts/release/cut.sh tag` (pushes `vX.Y.Z`). The tag fires
`.github/workflows/release.yml` (verify → publish GitHub Release + `ghcr-push`
builds/pushes the `argon-app`/`argon-web` images; `:latest` floats only for final,
non-prerelease tags). The mini runs argon from `/opt/argon/compose.yml`; the
engine-wide Watchtower in `/opt/xenon/compose.yml` auto-deploys the new `:latest`
images. Prereleases (`vX.Y.Z-rc1`) never float `:latest`, so Watchtower never
auto-deploys an rc. Schema changes apply out-of-band via the profile-gated
migrator. Current path: `docs/runbooks/docker-deploy.md`; the superseded launchd
`deploy-poller`/`macmini-prod.sh` path stays documented in `docs/runbooks/release.md`.

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
- **Persist every research/backtest trace before the process exits** — any sweep, backtest, or parameter search must save its *full* result set (every config + every metric, not just the headline) to a durable artifact: a Postgres table for productionized signals, or a committed file/notebook under `docs/research/` for exploratory runs. stdout-only is data loss — a number you can't reproduce from a saved trace did not happen. Always record the exact reproduce command (script path + args/seed)
- **No naked shorts** in any strategy/trade-plan code — defined-risk only
- **Data source priority** (live quotes/greeks): IB (via xenon) → UW → FMP → massive. UW stays the primary source for scan/options/flow data and massive for daily OHLC (see "What this is"). Yahoo is banned — enforced by `scripts/check_no_yahoo.py` in CI
- **Massive WS bypasses system proxies** — `MassiveWsClient` passes `proxy=None` to `websockets.connect`; the market-data stream must never inherit macOS SOCKS/HTTP proxy settings (`python-socks` is not installed, so an inherited proxy kills every connect). The configured feed is ~15-min delayed, so WS-consumer health keys on `last_flush_at` (is the consumer alive?), not tick event time
- **No secrets to local Codex subprocesses** — do not pass UW/FMP/Massive keys, DB credentials, or unrelated app secrets to `codex exec`
- **Never commit without an explicit user request.** Draft first, wait
- **Big projects use milestone commits** — when the user has explicitly requested commits for a large project/task, commit each closed milestone after its relevant verification before continuing
- **Always open a PR before merging to main.** `git push origin main` is forbidden
- **Branch names** default to type prefixes: `feat/` for features, `fix/` for bug fixes, `chore/` for maintenance, and `misc/` for other work. Do not default to a `codex/` prefix
- **Never add `Co-Authored-By: Claude` trailers** to commits
- **CHANGELOG rides the feature PR.** Add the `[Unreleased]` entry on the feature branch BEFORE merging — code, tests, docs, and changelog in one PR. Only the `cut.sh prepare` version-bump PR is legitimately separate
- **Worktrees live in `.worktrees/<branch-slug>/`** — the project-root `.worktrees/` directory is the only canonical location (already gitignored). When done, `git worktree remove <path>` — stale worktrees holding `main` block `git checkout main` in the primary repo
- **Smoke tests run the real worker path** — API enqueue → DB row → worker claims → DB result → web UI renders. Never a one-off `/tmp` script calling the function directly; the user validates via the web page. If the worker predates your edit, restart the stack first (APScheduler doesn't hot-reload)
- **R2 lake is primary for EOD/backfill reads** (new backtest/backfill code reads R2 parquet via `sources/lake.py`, falls back to the local mirror); Postgres warm store stays the API request-time read path. Outputs still persist to Postgres
- **Migrations are idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). No tracking table — re-running is a no-op
- **Live API tests** are marked `live` and need `UW_SCAN_API_KEY`; default `pytest` excludes them
- **Screenshots and browser artifacts** go under `output/playwright/` with descriptive names. Do not create ad hoc screenshots, logs, snapshots, or downloaded browser artifacts in the repo root; keep them in `output/playwright/` so cleanup and review evidence stay manageable
- **Module size budget** — target <500 lines per Python file; at 1000+ lines stop adding methods and propose a split first. `repository.py` reached 5000+ lines because the line was never drawn — don't repeat. Split by domain seam (one module per cohesive set of methods), not by technical layer. Cite this rule in any PR that grows a file past 1000 lines without a split plan
- **API model refactors preserve contract identity** — `src/uw_scan/models/` may be split by domain, but `from uw_scan.models import X`, `models.__all__`, Pydantic field/default/config surfaces, and OpenAPI component names must stay stable unless the PR is explicitly an API contract change. When moving Pydantic models out of the package root, preserve public model `__module__` metadata and run the export, field-surface, and OpenAPI snapshot checks before review
- **AGENTS.md is a symlink to this file** (for Codex). Edit CLAUDE.md only; never materialize AGENTS.md as a separate file

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
| UW daily-budget governor (live/research pools, hot fast lane) | `src/uw_scan/sources/uw_budget.py` (pool split + `may_spend` + `read_snapshot`) + scheduler `_live_max_tickers`/`_research_budget_ok` + `worker/jobs/full_scan_hot.py` + config `uw_*_ceiling`/`full_scan_hot_*`/`gex_scan_*_interval_minutes` + migration `096` (`watchlist.hot`) + `web/components/watchlist/HotButton.tsx`; plan `docs/superpowers/plans/2026-07-04-uw-budget-scaling.md` |
| Research ticker cohorts (non-watchlist) + their capture/catch-up pair | `storage/research_universe.py` + `worker/jobs/option_surface_research_capture.py` (19:10 ET, uw-0, `OPTION_SURFACE_RESEARCH_CAPTURE_ENABLED`, full chain — writes **tonight**) + `worker/jobs/option_surface_research_catchup.py` (03:20 ET, uw-0, `OPTION_SURFACE_RESEARCH_CATCHUP_ENABLED`/`_MAX_CALLS`, weekly sample ≤60 DTE — fills **history**, budget-gated, resumable, self-terminating) + migration `110` + seeding/manual fill `scripts/research/option_surface_research_backfill.py` (shares the catch-up's core; no duplicate logic). Both jobs self-gate on an empty cohort. Cohort `liquid_sector_balanced_v1` = 37 names, 10 sectors, marketcap ≥ $30B AND option OI ≥ 200k. **Not the watchlist, deliberately** — membership there costs ~+32% permanent per-ticker burn and hands the cohort to the gap healer at full-chain daily rates (~78,600 calls vs ~7,950). Exists to counterweight the watchlist's AI/semi concentration — see `docs/research/2026-07-29-theta-harvester-loss-anatomy.md` |
| Option surface capture (durable full-chain IV grid) + IB canary | `src/uw_scan/worker/jobs/option_surface_capture.py` + `worker/jobs/option_surface_iv_canary.py` + `storage/option_surface.py` + `sources/xenon_query.py` + migrations `077`/`078` (grid + `iv_source_validation`; jobs at 19:00/19:30 ET weekdays, uw-0); spec `docs/superpowers/specs/2026-06-19-option-surface-capture-design.md` |
| Live spot WS feed (xenon primary / massive fallback) | `src/uw_scan/sources/{xenon_ws,massive_ws}.py` + `worker/massive_ws_consumer.py` + `worker/ws_db_writer.py`; active feed: `/api/health` `ws_consumer.active_source` |
| UW endpoints (integrated) | `src/uw_scan/api/endpoints.py` + `sources/uw.py` |
| UW API reference (standard tier) | `docs/uw-samples/unusual_whales_api.md` (human-readable) + `docs/uw-samples/unusual_whales_api_spec.yaml` (OpenAPI) — integrated endpoints, untapped-but-accessible endpoints with signal-priority ranking, backfill notes. Consult before adding any new UW fetcher. Audit baseline: 140 accessible / 30 integrated (2026-05-15). |
| UW API reference (gated tiers) | `docs/uw-samples/unusual_whales_advanced_tier.md` — Advanced+ / Premium / Enterprise gated endpoints. Do not add fetchers for these without upgrading. |
| UW sample payloads | `docs/uw-samples/*.json` — real responses for each integrated endpoint, with `_shape-summary.md` |
| UW capability audit (machine-readable) | `docs/uw-samples/uw_api_capability_audit.json` + `uw_api_capability_audit.md` — full 177-operation matrix with live probe results, backfill classification, response shapes |
| Volatility derivers | `src/uw_scan/cards/vol_series.py`, `reports/volatility_series.py` |
| Scanner (detectors + ranking + discovery) | `src/uw_scan/scanner/` (pipeline, signals, ranking, discovery, gates, context) + `api/routers/scanner.py` + `web/app/scanner/[[...tab]]/page.tsx` (Flow / Discover / Value / Theta sub-tabs, `components/scanner/ScannerPanel.tsx`) |
| Theta Harvester (short-strangle **research** scanner, radon port) | `src/uw_scan/theta_harvester/` (pure compute: vol, range, dealer support, legs, scoring/gates) + `storage/theta_harvester_repository.py` + `worker/jobs/theta_harvester.py` (scan 19:45 ET, markout 19:55 ET, uw-0, gated `UW_SCAN_THETA_HARVESTER_ENABLED`) + `api/routers/scanner.py` (`/theta-harvester{,/rescan,/quote}`) + `web/components/scanner/theta/ThetaSubTab.tsx` + migration `109`; backfill `scripts/backfill/theta_harvester_backfill.py`, sweep `scripts/research/theta_harvester_weight_sweep.py`. **Research artifact, not a trade surface** — the structure is a naked short strangle (violates defined-risk-only) and the 2026-07-28 sweep found the score ORDERS (IC +0.075) but its selected set does not pay; held-to-expiry short strangles lost money over the measured window. Ranking is zero-UW-cost (reads `option_surface_grid_daily`); IB quoting is view-only and capped at 8 contracts. Verdict + method: `docs/research/2026-07-28-theta-harvester-weight-sweep.md`; plan `docs/superpowers/plans/2026-07-28-theta-harvester-scanner.md` |
| Regime indicators (CRI / GEX / VCG) | `src/uw_scan/scanners/{cri,gex,vcg}.py` + `api/routers/regime.py` + `web/app/regime/page.tsx` + `web/components/regime/*` |
| Regime live CRI/VCG (WS quotes) | `src/uw_scan/scanners/live_quotes.py` + `scanners/{cri,vcg}.py` `run_live` + `worker/jobs/regime_live.py` + `api/routers/regime.py` (`/cri/live` etc.) + `web/components/regime/MultiPanelGrid.tsx` |
| VRP macro short-vol signal (EOD + live) | `reports/vrp_macro_signal.py` (`current_macro_signal`, `current_macro_signal_live`) + `storage/vrp_macro_signal.py` (`basis` col) + `worker/jobs/{vrp_macro_signal,regime_live}.py` + `api/routers/regime.py` (`/vrp-macro-signal`, `/vrp-macro-signal/live`) + `web/components/regime/MacroShortVolSubTab.tsx`; migrations 083/084. **Live = SPX only**, piggybacks the 5-min `regime_live_scan` (no new job); EOD stays `vrp_macro_signal_refresh` @03:45 ET |
| VRP harvest markout (is rich vol sellable) | `src/uw_scan/reports/vrp_markout.py` + `storage/vrp_markout.py` + `worker/jobs/vrp_markout.py` + `api/routers/regime.py` (`/vrp-harvest`) + migration `079`; nightly 18:50 ET (massive-0); spec `docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md` |
| VRP macro entry-capture (forward markout) | `reports/vrp_macro_entry.py` (`resolve_entry_contracts`, `quote_leg` — **xenon/IB-primary NBBO+IV+native greeks → UW fallback → greeks IB-native primary (rescaled to BS convention: vega ×100, theta ×365), BS-from-IV backup**) + `worker/jobs/vrp_macro_entry.py` (daily birth + 8 marks/day, 30-cal-day EOD taper) + `storage/vrp_macro_entry.py` + `api/models/vrp_macro_entry.py` + `api/routers/regime.py` (`/vrp-macro-signal/entry/{preview,capture}` — preview is zero-IB/zero-UW) + `web/components/regime/MacroShortVolCard.tsx` (strike/ETD panel + Capture button); migration `085`; 8 ET crons (massive-0, gated `vrp_macro_entry_capture_enabled`); plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`. **Deploy:** set `XENON_QUERY_API_KEY` in the mini's argon `.env` (URL now defaults to the mini's `:8321`) or the IB path silently no-ops to `source='uw'`. **Strike-grid cache** (`vrp_macro_entry_grid`, migration `088`): nightly `vrp_macro_entry_grid_refresh` @03:50 ET caches the real UW-listed strikes so the RTH birth reads the cache and makes **zero UW calls** (the inline-UW birth 429'd daily and never persisted); plan `docs/superpowers/plans/2026-06-25-vrp-macro-entry-grid-cache.md` |
| Gold Compass — code | `api/routers/gold.py` + `storage/gold_etf.py` + `worker/jobs/gold_jobs.py` + `sources/{fred,gpr,lbma,comex,etf_holdings,uw_gold_options,cftc_cot,wgc_etf,wgc_cb}.py` + `web/app/gold/page.tsx` (+ `gold/replay/[date]/`) + `web/components/gold/*` |
| Gold Compass — research / sources docs | `docs/research/gold-sdf-framework/CLAUDE.md` (3-lens model, status vs. shipped, deferred sources) + `src/uw_scan/sources/CLAUDE.md` (per-source status + failure modes) |
| Index dealer cockpit (SPX/SPY/QQQ/IWM) | `api/routers/cockpit.py` + `web/app/cockpit/[ticker]/page.tsx` |
| Stock detail page | `web/app/stock/[ticker]/page.tsx` + `components/stock/tabs/*` |
| Technicals Magnet View (levels + options-implied cone) | `cards/magnets.py` + `models/magnets.py` + `api/routers/stock.py` (`/magnets`) + `web/components/stock/tabs/technicals/*` + `web/tests/e2e/magnet-view.spec.ts`; research `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md` (G1 failed — 0.618 is geometry only; cone band labels carry MEASURED coverage + its 95% CI, never the nominal), plan `docs/superpowers/plans/2026-08-09-magnet-view-phase2-3-build.md` |
| Chanlun (缠论) price-chart overlay (笔/中枢/买卖点) | `web/lib/chanlun.ts` (compute) + `web/lib/lwc/chanlunZhongshu.ts` (中枢 rect primitive) + toggle/wiring in `web/components/stock/panels/TechnicalsPriceChart.tsx`; research/design `docs/research/2026-07-14-chanlun-tv-view-research.md`; tests `web/tests/lib/chanlun.test.ts` (frozen real-AAPL fixture) |
| Chanlun Phase B sub-level lifecycle (区间套 30m fast-confirm) | `src/uw_scan/chanlun/` (port + `lifecycle.py`) + `sources/apex.py::fetch_bars` + `storage/chanlun_signal_repository.py` + migration `107` + `worker/jobs/chanlun_lifecycle.py` (03:10 ET Tue–Sat massive-0, gated `UW_SCAN_CHANLUN_LIFECYCLE_ENABLED`, promotable default EMPTY — probe failed all categories) + `api/routers/stock.py` (`/chanlun/lifecycle`) + probe `scripts/research/chanlun_sublevel_probe.py`; spec `docs/superpowers/specs/2026-07-14-chanlun-phase-b-sublevel-confirm-design.md`, plan `docs/superpowers/plans/2026-07-14-chanlun-phase-b.md` |
| Dual MACD + live technicals coverage | `cards/technicals.py` (`dual_macd_series`/`dual_macd_state`/`live_technical_snapshot`) + `worker/jobs/technical_live.py` + `storage/technical_live_repository.py` + migration `104` + `api/routers/stock.py` (`/technicals/live`, gated `UW_SCAN_TECHNICAL_LIVE_ENABLED`, massive-0) + `web/components/stock/panels/{TechnicalsOscillators,LiveBadge}.tsx` + `web/components/stock/tabs/TechnicalsTab.tsx`; spec `docs/superpowers/specs/2026-07-09-dual-macd-live-technicals-design.md`, plan `docs/superpowers/plans/2026-07-10-dual-macd-live-technicals.md` |
| On-demand technicals compute (unavailable ticker) | `api/routers/stock.py` (`POST /stock/{ticker}/technicals/refresh` — runs `worker/jobs/technical_daily_refresh.technical_daily_refresh` scoped to one ticker; the one deliberate write on the read-only router) + `web/components/stock/panels/TechnicalsEmptyState.tsx` ("Compute now" button) + `web/lib/api.ts` (`technicalsRefresh`); compute-only, no watchlist mutation |
| Per-stock short-vol card (single-name sibling of macro short-vol) | `reports/stock_short_vol.py` (`decide_short_vol`/`build_short_vol`) + `models/stock.py` (`StockShortVol`, `SingleStockReport.short_vol`) + `web/components/stock/panels/ShortVolPanel.tsx` + `web/components/stock/tabs/MarketStructureTab.tsx`; read-time reshape of `vrp_daily` gated by `reports/vrp_gate.py`; plan `docs/superpowers/plans/2026-06-24-stock-short-vol-card.md` |
| Fundamental PM lane (statement store → composite → card) | `src/uw_scan/fundamentals/` (`statements`/`features`/`scoring`/`valuation`/`fx`/`card`) + `storage/fundamental_{obs,scores,anchors}.py` + migrations `114`/`117`/`118` + `worker/jobs/fundamental_{ingest,scoring,anchors,refresh}.py` (`fundamental_refresh` 18:20 ET, massive-0, gated `UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED` default **on**, chains routing → subscores → anchor bands at zero UW/IB spend; it deliberately does **not** ingest — new filings come from `scripts/backfill/fundamental_ingest_backfill.py`) + `api/routers/stock.py` (`/fundamentals`, `/fundamentals/statements`) + `web/components/stock/tabs/FundamentalsTab.tsx` + `web/components/stock/panels/Fundamental*`. **Two things that will bite:** observation identity is a `content_hash` that **excludes UW's `inserted_at`/`updated_at`** — include them and every refresh reads as a phantom restatement; and the composite **orders names cross-sectionally** (rank IC 0.039, t 2.67 on rows carrying a real `filing_date`) but **cannot time one name against itself** (within-ticker market-neutral IC −0.0000, all 16 tests fail BH), which is why the card presents subscore trajectories as descriptive and draws no price consequence from them. Specs `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md` + `2026-08-12-fundamentals-card-flip-design.md`; verdicts `docs/research/2026-08-12-fundamental-*/` |
| Valuation buy-zone surface (cross-name list of own-history bands) | `storage/fundamental_anchors.py` (`in_buy_zone`/`band_coverage` — the only cross-name reads on `valuation_anchors`) + `api/routers/scanner.py` (`GET /scanner/value`, warm-store only, zero UW/IB) + `web/components/scanner/value/ValueSubTab.tsx` + check `scripts/research/valuation_band_coverage_check.py`. **It LISTS, it must never RANK** — own-history value measured (`sales_to_ev` within-ticker 2q IC +0.0744, t 5.77) but cross-sectional value measured INVERTED in the same universe (`book_to_price` IC −0.0365, t −2.32), so no `sort` parameter over `spot_percentile` or depth may ever be added; the ordering is newly-entered-first then alphabetical. Two more traps: `spot_percentile` is a **yield** percentile (0.80 = CHEAP) and reaches the screen only through `rankPhrase`; and `entered` is three-state, where `null` means "no prior band in the 30-day lookback" and must never render as NEW — on 2026-08-17 that was 29 of 98 names, all present because the panel widened 256 → 414. Plan `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` (PR 4) |
| Revenue concentration (segment / geography) — **descriptive only** | `fundamentals/concentration.py` (derivation, read-time) + `storage/fundamental_concentration.py` + migration `122` (`revenue_breakdown_obs`, content-hash identity) + `worker/jobs/fundamental_concentration_capture.py` (04:10 ET on the 3rd, uw-0, `UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED` default **on**, ~450 UW calls/run) + `api/routers/stock.py` (`/fundamentals/concentration`) + `web/components/stock/panels/FundamentalConcentration.tsx`. **Not a signal and never a composite input** — the top share moves a median 1.20pp/quarter against p90 17.5pp of annual/quarterly basis contamination; the level is a factor loading, not alpha (spec §896 weight withdrawn 2026-08-18). Three things that will bite: group by the XBRL **axis**, never `rev_group`; the denominator is the period's untagged consolidated row from **any** group; and annual-row detection compares against a period's **4 nearest neighbours**, never the ticker's lifetime median — a grower's recent quarter clears 2.5x its own median on growth alone. Plan `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` (3 recorded deviations) |
| Watchlist landing | `web/app/page.tsx` + `components/watchlist/CardGrid.tsx` |
| Backtest harness (walk-forward engine / OOS gates / metrics / sweep) | `src/uw_scan/backtest/` (see its `CLAUDE.md`) + `storage/backtest_repository.py` (standalone `BacktestRepository`, tables `backtest_sweep_runs`/`backtest_sweep_results`) + migration `095`. **Shared compute engine only** — strategies delegate their gate, holdout, and (for sweeps) metric math here (zero private copies); result STORAGE stays per-strategy (skew/vrp verdict tables) except parameter sweeps, which write the generic `backtest_sweep_*`. Gate/holdout consumers: `reports/{skew_markout,vrp_markout,vrp_markout_core,vrp_backtest}.py`. Sweep runner: `scripts/_vrp_macro_param_sweep.py` (VRP macro bull-put-spread; reproduces Sharpe ~1.65). Plan `docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md` |
| Single-name daily GEX refresh (#179) | `worker/jobs/greek_exposure_daily_refresh.py` (UW aggregate `/greek-exposure` per single name, reuses `scanners/gex.fetch_aggregate_gex` + `GreekExposureDailyRepository.upsert_rows`) + scheduler `_greek_exposure_daily_refresh` (uw-0, 18:30 ET); backfill `scripts/backfill/greek_exposure_daily_refresh_backfill.py` |
| Intraday OI-mover refresh (#180) | `worker/jobs/option_intraday_jobs.py` + scheduler `_intraday_oi_refresh` (primary-only, `ticker_filter=None`, per-outcome counters); backfill `scripts/backfill/intraday_buckets_backfill.py` |
| Data-date freshness monitor (prevention) | `reports/data_freshness.py` (`MONITORED_TABLES`, `compute_freshness`) + `storage/data_freshness_repository.py` + `worker/jobs/data_freshness_monitor.py` (uw-0, 21:00 ET) + `/api/health` `freshness` block; migration `087` |
| Data gap healer (exact audit + heal + nightly backfill) | `reports/data_gap_healer.py` (REGISTRY + scanner) + `worker/jobs/data_gap_adapters.py` (heal dispatch) + `worker/jobs/data_gap_healer.py` (orchestration + nightly job, 20:00 ET, uw-0, `DATA_GAP_HEALER_ENABLED` default off) + `storage/data_gap_healer_repository.py` + `scripts/backfill/data_gap_healer.py` (audit/execute/resume/verify/verify-all) + `/api/health` `gap_healer`; migration `092`; runbook `docs/runbooks/data-gap-healer.md`, policy `docs/runbooks/data-gap-dataset-policy.md` |
| Trade Insights AI — orchestration | `src/uw_scan/worker/jobs/trade_insights_ai.py` (claim → dispatch → persist; RUNNERS registry, `provider_filter` param, per-provider heartbeats) |
| Trade Insights AI — provider runners | `src/uw_scan/worker/jobs/trade_insights_ai_runners.py` (`AiProviderRunner` Protocol, `_format_runner_failure`, `_runner_child_env`), `trade_insights_codex_runner.py`, `trade_insights_claude_runner.py` |
| Trade Insights AI — API + storage | `api/routers/trade_insights.py` (POST paired stubs, /latest keyed pair) + `storage/trade_insights_ai.py` (provider param on every read/write, `find_latest_*_per_provider`, `count_queued_*_by_provider`) |
| Trade Insights AI — UI tabs | `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` ([Codex] [Claude] tabs, per-provider polling, state badges) |
| Release pipeline (versioning + workflow) | `VERSION` + `CHANGELOG.md` + `scripts/release/{_lib.sh,version_sync_check.py,cut.sh}` + `.github/workflows/release.yml` |
| Auto-deploy to the mini | `scripts/deploy/macmini-deploy-poller.sh` + `config/templates/com.argon.deploy-poller.plist.template` + `scripts/deploy/macmini-prod.sh`; runbook `docs/runbooks/release.md` |
