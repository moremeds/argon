# src/uw_scan/api — FastAPI app + UW HTTP client

## Two distinct roles

This directory holds **two unrelated things** that share a folder for historical reasons:

1. **Outbound** — `client.py` is the **UW HTTP client** used by sources/workers
2. **Inbound** — `server.py` + `routers/` is **our own** FastAPI surface for the web

Don't conflate them.

## Files

- `server.py` — app factory, mounts 24 routers under `/api`: `health, benchmark, watchlist, stock, ohlc, cockpit, jobs, volatility, skew, provider_usage, trade_insights, regime, regime_validation, gold, rates, macro, scanner, radar, fundamentals_desk, research_evidence, research_reports, positioning, vrp, positions` (the `include_router` block in `server.py` is authoritative)
- `client.py` — `UwClient(httpx)` with retry/throttle; one entry per UW endpoint
- `endpoints.py` — `EndpointSlug` enum + `build_path()` — the only place UW URL paths live
- `deps.py` — FastAPI dependencies (DB session, settings)
- `schemas.py` — request/response shapes specific to our HTTP surface (not the DB models)
- `models/` — router-local request/response models too niche for `uw_scan.models` (canary, regime_validation, scanner, theta_harvester, vrp_macro_entry, watchlist)
- `routers/*.py` — read-only over the warm store; one file per router listed above

## Rules

- **Routers are read-only.** Long-running work (rescan, full-scan kickoff, vol backfill) goes through `routers/jobs.py` and the worker.
- **No business logic in routers** — call into `reports/*` or `cards/*`. A router method should be a thin wrapper that resolves params → calls assembler → returns the model.
- **Mutations use `pg_try_advisory_lock`** for single-flight (see `routers/{stock,scanner,volatility}.py`); `routers/jobs.py` instead enqueues a DB row via `repo.enqueue_rescan_job` for the worker to pick up.
- **CORS** is permissive by design (`allow_origin_regex=r".*"` in `server.py`) — the real trust boundary is the network layer (the private Tailnet), not the origin string.
- **`openapi.json` is the API contract.** After any model/router change run `cd web && npm run gen:types` to regenerate `web/lib/types.ts`.

## UW client (`client.py`)

- Reads `UW_SCAN_API_KEY` from `Settings`
- Retry on 429/5xx with backoff; never silently drop a non-2xx
- All fetchers in `sources/uw.py` flow through this client
