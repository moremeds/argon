# src/uw_scan/api — FastAPI app + UW HTTP client

## Two distinct roles

This directory holds **two unrelated things** that share a folder for historical reasons:

1. **Outbound** — `client.py` is the **UW HTTP client** used by sources/workers
2. **Inbound** — `server.py` + `routers/` is **our own** FastAPI surface for the web

Don't conflate them.

## Files

- `server.py` — app factory, mounts `health|watchlist|stock|ohlc|jobs|volatility` under `/api`
- `client.py` — `UwClient(httpx)` with retry/throttle; one entry per UW endpoint
- `endpoints.py` — `EndpointSlug` enum + `build_path()` — the only place UW URL paths live
- `deps.py` — FastAPI dependencies (DB session, settings)
- `schemas.py` — request/response shapes specific to our HTTP surface (not the DB models)
- `routers/{health,watchlist,stock,ohlc,jobs,volatility}.py` — read-only over the warm store

## Rules

- **Routers are read-only.** Long-running work (rescan, full-scan kickoff, vol backfill) goes through `routers/jobs.py` and the worker.
- **No business logic in routers** — call into `reports/*` or `cards/*`. A router method should be a thin wrapper that resolves params → calls assembler → returns the model.
- **Mutations use `pg_try_advisory_lock`** for single-flight (see `routers/jobs.py` + `routers/volatility.py` backfill kicker).
- **CORS** allows loopback (`127.0.0.1` / `localhost`) on ports `300{1,2,3}` for local dev, plus the Tailscale CGNAT range (`100.x.x.x`) on the same ports for cross-machine browse against the mini stack (Phase 4, see `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`). Implemented as an `allow_origin_regex` in `server.py`. Don't widen further (public domains, broader IP ranges, HTTPS) without an architectural reason — the Tailnet-only assumption is what keeps this trust boundary tight.
- **`openapi.json` is the API contract.** After any model/router change run `cd web && npm run gen:types` to regenerate `web/lib/types.ts`.

## UW client (`client.py`)

- Reads `UW_SCAN_API_KEY` from `Settings`
- Retry on 429/5xx with backoff; never silently drop a non-2xx
- All fetchers in `sources/uw.py` flow through this client
