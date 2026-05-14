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
bash scripts/dev.sh               # run all three processes
uv run pytest                     # python tests
cd web && npm run test            # vitest
cd web && npm run gen:types       # regenerate types.ts after API change
```

## Trade Insights AI (V1.5)

Local Codex CLI is the only model execution path for Trade Insights AI analysis. The API queues persisted `trade_insight_ai_analyses` rows; the worker runs `codex exec` in a read-only sandbox and stores the exact prompt, prompt payload, output schema, produced timestamp, structured outcome, and Markdown audit view.

Environment:

- `TRADE_INSIGHTS_AI_ENABLED` — enable the worker/API path when true
- `TRADE_INSIGHTS_AI_MODEL` — optional Codex model; blank means local Codex default and rows store `codex-default`
- `TRADE_INSIGHTS_AI_TIMEOUT_SECONDS` — subprocess timeout, default 300
- `TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES` — structured output cap, default 262144
- `TRADE_INSIGHTS_AI_POLL_SECONDS` — worker polling interval, default 3

## Standing rules

- **uv only** — `uv run pytest`, never `pytest` directly
- **Persist analytical results to Postgres** — vol/scan/regime outputs land in tables, never in-memory-only
- **No naked shorts** in any strategy/trade-plan code — defined-risk only
- **Data source priority**: IB → UW → FMP → massive (OHLC). Yahoo is banned
- **No secrets to local Codex subprocesses** — do not pass UW/FMP/Massive keys, DB credentials, or unrelated app secrets to `codex exec`
- **Never commit without an explicit user request.** Draft first, wait
- **Always open a PR before merging to main.** `git push origin main` is forbidden
- **Branch names** default to type prefixes: `feat/` for features, `fix/` for bug fixes, `chore/` for maintenance, and `misc/` for other work. Do not default to a `codex/` prefix
- **Never add `Co-Authored-By: Claude` trailers** to commits
- **Migrations are idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). No tracking table — re-running is a no-op
- **Live API tests** are marked `live` and need `UW_SCAN_API_KEY`; default `pytest` excludes them
- **AGENTS.md** still lives at the root for Codex; keep both files in sync when policy changes

## Where to look first

| Need | Look at |
|---|---|
| Active specs / plans | `docs/superpowers/specs/`, `docs/superpowers/plans/` |
| API surface | `src/uw_scan/api/server.py` + `routers/*` |
| Persistence | `src/uw_scan/storage/repository.py` (one method per query) |
| Scheduled jobs | `src/uw_scan/worker/scheduler.py` |
| UW endpoints (integrated) | `src/uw_scan/api/endpoints.py` + `sources/uw.py` |
| UW API reference (full surface) | `docs/uw-samples/unusual_whales_api.md` (human-readable) + `docs/uw-samples/unusual_whales_api_spec.yaml` (OpenAPI) — consult before adding any new UW fetcher |
| UW sample payloads | `docs/uw-samples/*.json` — real responses for each integrated endpoint, with `_shape-summary.md` |
| Volatility derivers | `src/uw_scan/cards/vol_series.py`, `reports/volatility_series.py` |
| Stock detail page | `web/app/stock/[ticker]/page.tsx` + `components/stock/tabs/*` |
| Watchlist landing | `web/app/page.tsx` + `components/watchlist/CardGrid.tsx` |
