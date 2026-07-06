# Candidate: backtest explorer + provider-usage + benchmark dashboards

**Date:** 2026-07-06 · **Status:** DRAFT (candidate) · **Basis:** [COMPUTED] from web-gaps probe. Confidence HIGH.
**Effort:** M total. One web sprint surfacing three fully-built-but-unwired backends.

## 1. Backtest Sweep Explorer (highest value×buildability)

`backtest_sweep_runs` / `backtest_sweep_results` (migration 095) are fully populated by `src/uw_scan/backtest/sweep.py` + `BacktestRepository` (id, created_at, config, metrics, gates, n_trades, status, error) — but there is **no API router and no web page**. Sweep results are readable only via SQL/scripts today.

Build: a thin FastAPI router wrapping `BacktestRepository` read methods (no router exists yet) → `/backtest` page: sortable runs table, drill into per-config metrics/gates JSON, diff two runs. This is the direct payoff of the walk-forward harness (PR #210) and the natural home for future kill-switch (#163) sweep results.

## 2. Provider-Usage / UW-budget dashboard (Effort: S — endpoints already shipped)

`api/routers/provider_usage.py` has 4 working endpoints (summary, breakdown by endpoint/ticker, raw request log, incl. `uw_latest_daily_count/limit`, latency p95, per-endpoint/ticker error rates). **Zero** web page consumes any of them.

Build: `/admin/provider-usage` (or promote off `/admin`) — daily request-count/latency/error-rate charts + a UW daily-limit gauge. Directly answers "are we about to hit the UW rate limit." Pairs with ops-hardening #5 (add `job_name` breakdown → per-job budget attribution on the same page).

## 3. Pipeline-Benchmark dashboard (Effort: S — shipped, never wired)

`api/routers/benchmark.py` `/health/benchmark/current` and `/history` (composite score, subscores, snapshot history, reasons) are fully implemented, have generated TS types, and even a unit test (`healthBenchmarkApi.test.ts`) — but **no page renders them**. Looks shipped-then-abandoned.

Build: a scorecard page — current score + subscore breakdown + benchmark-history sparkline. Wire-up only.

## Also-noted (not in this bundle)

- **Ops/Admin rebuild** (health + jobs currently a raw `JSON.stringify` blob at `/admin`) — S–M, more UI surface; fold in if doing #2/#3 anyway.
- **Cross-ticker comparison** (`/compare?tickers=A,B,C` matrix of GEX/skew/VRP/IV-pctile) — M, all per-ticker endpoints exist; deferred as lower-priority.

## Order

#2 + #3 first (pure frontend, backends done) → #1 (needs a small new router) → optional admin rebuild.
