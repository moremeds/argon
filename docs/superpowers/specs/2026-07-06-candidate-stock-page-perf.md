# Candidate: /stock/{ticker} performance package

**Date:** 2026-07-06 · **Status:** DRAFT (candidate) · **Basis:** [COMPUTED] from code-health probe, file:line-verified. Confidence HIGH.
**Effort:** S + M + S. Three compounding fixes on the highest-traffic read path.

## 1. N+1 in the hottest report (Effort: S — biggest single latency win)

`reports/single_stock.py:250-274` (`_build_intraday_profiles`) loops over `OI_MOVERS_INTRADAY_TOP_N` (10) rows and calls `intraday_repo.fetch_buckets(option_symbol, trade_date)` **once per row** — 10 sequential DB round-trips to `option_intraday_buckets` on every `/api/stock/{ticker}` and `/api/stock/{ticker}/runs/{run_id}` request (`api/routers/stock.py:44,90`). This backs the busiest page in the app.

Fix: rewrite `fetch_buckets` to accept a batch of `(option_symbol, trade_date)` pairs → one `WHERE (option_symbol, trade_date) = ANY(...)` query. Cuts ~10 round-trips to 1 per stock-page load.

## 2. No API connection pool (Effort: M)

`api/deps.py:21-27` — `get_repo()` calls `psycopg.connect(settings.db_dsn())` fresh per request, closes in `finally`. Documented as intentional ("one conn per request") but that convention predates load: it pays full TCP + auth + `SET search_path` on every hit, including `/api/watchlist/spots` polled every 2.5s per open tab (`web/components/watchlist/LiveSpotsProvider.tsx:25`). Compounds with #1 across many tabs.

Fix: `psycopg_pool.ConnectionPool` created once at app startup; `get_repo()` borrows/returns. Removes per-request connection setup; lowers Postgres connection churn.

**Docker interaction:** under the container migration the api runs as its own service against `host.docker.internal:5432` — a pool matters *more* there (connection setup crosses the VM boundary). Do this before or with the Docker cutover.

## 3. Report response cache (Effort: S)

Compounding with #1: every `/api/stock/{ticker}` call rebuilds 10 intraday profiles from raw buckets even though `option_intraday_buckets` only changes on its own worker cadence (`worker/jobs/option_intraday_jobs.py`) — no caching keyed on `run_id`/last-write, so page revisits and adjacent polling redo full derivation each time.

Fix: cache `assemble_single_stock_report` per `(ticker, run_id)` with short TTL / eviction, invalidated when `latest_run_id` changes. Pairs with #1 to make repeat views near-O(1) DB work within a scan cycle.

## Order

#1 (standalone win) → #3 (rides on #1's batched read) → #2 (broader, do with the Docker cutover).
