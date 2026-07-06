# Candidate: deploy-gate fix + ops-hardening package

**Date:** 2026-07-06 · **Status:** DRAFT (candidate) · **Basis:** [COMPUTED] from ops probe, file:line-verified. Confidence HIGH.
**Note:** partly overlaps the Docker migration (Watchtower removes the launchd deploy path). The *alerting* and *health-surface* pieces survive that migration and become the primary detection layer once Watchtower's no-rollback tradeoff is accepted. Sequence with `2026-07-06-docker-migration-design.md`.

## 1. Deploy health-gate bug — DO FIRST (Effort: S)

`scripts/deploy/macmini-prod.sh:104-118` gates deploy success (and auto-rollback) on `check_url` = `curl -fsS --max-time 2 "$url"` — any 2xx passes. But `/api/health` returns **HTTP 200 in every branch, including `ok=false`** (`api/routers/health.py:358` db-down, `:635`, `:658`, `:673`). So a release that breaks the DB, misses 2 full scans, or collapses record-coverage passes the gate clean and the rollback never fires — the one automated safety net checks the wrong signal.

Fix: swap the `curl -fsS` reachability check for a body check — `curl -fsS "$url" | jq -e '.ok == true'` — on both the forward gate and the post-rollback verify.

**Caveat given the Docker migration:** if launchd deploy retires in favour of Watchtower, this script fix is moot for prod — but the *reason* it matters (no health-aware gate at all under Watchtower) makes the alerting piece below mandatory, not optional.

## 2. Ops alerting channel (Effort: M)

`grep -rli "pushover|telegram|discord|slack|webhook" src/uw_scan` → zero real hits. Every failure path (scheduler job exceptions, R2 lake-staleness fallback, frozen `data_freshness` tables, gap-healer circuit-breaker trips, budget wall) ends in a `logger.warning`/DB row — never pushed. The whole stack runs unattended on one Mac mini; no operator is in the loop unless they open the health panel.

Distinct from shortlist R3 (which pushes *trading signals*). This is purely operational: "the worker died" / "UW budget hit the wall at 08:03 ET" has zero notification path.

Build: one notification sink (Pushover or Discord webhook) wired to 3-4 existing conditions — `/api/health` `ok=false`, `autoheal_circuit_broken`, deploy/Watchtower recreate failure, budget `total_guard` breach.

## 3. R2 lake-staleness on /api/health (Effort: S)

`sources/lake_resolver.py:93-124` silently falls back to the local mirror and only `logger.warning(...)`s (line 122) when R2 is behind. `sources/CLAUDE.md` documents this defense was added 2026-06-07 after a **16-day silent stall** when the producer→R2 push died — yet the fix is still just a log line, not wired into `HealthResponse` or `data_freshness`. The exact failure it was built for can recur silently for another 16 days.

Fix: emit a heartbeat/counter row when the WARN fires; surface `lake_resolver_stale: bool` on `/api/health` (same pattern as `ws_consumer`/`gap_healer`).

## 4. Job-failure aggregation (Effort: M)

No `add_listener(EVENT_JOB_ERROR, ...)` anywhere in `worker/scheduler.py` (~40 jobs). Failure handling is per-job local try/except → `logger.warning` and move on (e.g. `:1014-1017`, `:1045-1047`). Nothing aggregates "N consecutive failures for job X" — a job dead 3 days looks identical to a single transient blip in the logs.

Fix: one `EVENT_JOB_ERROR` listener → small `job_failures` table + a failure-streak field on `/api/health` (feeds #2's alerting).

## 5. Per-job UW budget attribution (Effort: S — cheapest, answers the stated pain)

`sources/uw_budget.py:102-119` `read_snapshot` already groups `external_api_requests` by `job_name` internally but folds it into just `live`/`research` buckets. The breakdown API (`storage/external_api.py:223-238`) whitelists only `endpoint_key`/`ticker` — `job_name` is deliberately excluded, and `provider_usage.py` has no `/provider-usage/jobs` route. The exact per-job attribution needed to explain "why is the 40k budget gone by 08:00 ET" is sitting in the DB, unused.

Fix: add `"job_name"` to the allowed column set + one router endpoint, reusing existing plumbing. Unlocks smarter per-job ceilings vs the flat live/research split. (Pairs with the provider-usage dashboard candidate.)

## Recommended order

#1 (today, one-liner) → #5 (cheap, answers a live pain point) → #3 → #2 (needs #4's streak signal to be most useful) → #4.
