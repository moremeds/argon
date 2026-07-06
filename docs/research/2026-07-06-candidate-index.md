# 2026-07-06 candidate sweep — index

A probe sweep (4 agents: code-health, underused-data/alpha, web-gaps, ops/reliability) produced these brand-new candidates (excluding everything already in issues/worktrees/the next-work shortlist). Each is saved as its own doc.

| # | Candidate | Type | Effort | Doc | Status |
|---|---|---|---|---|---|
| 0 | Quant Technicals tab (sigmoid fit, MA kinematics, return-dist, enhanced RSI/MACD) | new page | M–L | `../superpowers/specs/2026-07-06-quant-technicals-page-design.md` | user's idea, designed |
| 1 | Deploy-gate fix + ops-hardening (alerting, R2 staleness, job-failure agg, per-job budget) | ops/reliability | S→M | `../superpowers/specs/2026-07-06-candidate-ops-hardening.md` | **do #1 first** |
| 2 | Dealer charm/vanna per-strike positioning + term-structure slope | alpha | M | `2026-07-06-candidate-charm-vanna-positioning.md` | unvalidated; start banking history now |
| 3 | GEX regime-persistence (long/short-gamma buckets, flip velocity) | alpha | S–M | `2026-07-06-candidate-gex-regime-persistence.md` | unvalidated; **has power today — test first** |
| 4 | /stock/{ticker} perf (N+1 batch, conn pool, report cache) | perf | S+M+S | `../superpowers/specs/2026-07-06-candidate-stock-page-perf.md` | biggest latency win |
| 5 | Backtest explorer + provider-usage + benchmark dashboards | new pages | M | `../superpowers/specs/2026-07-06-candidate-observability-dashboards.md` | 3 built-but-unwired backends |

Plus the separately-requested, now-in-progress **Docker migration** design: `../superpowers/specs/2026-07-06-docker-migration-design.md`.

## Mastermind sequence recommendation

Ops #1 deploy-gate one-liner (today) → alpha #3 (cheap validation, data ready) → alpha #2 derivation job (start accruing unrecoverable per-strike history) → perf #4 → Technicals tab #0 → dashboards #5. Perf #2 (conn pool) should ride with the Docker cutover.

## Not carried forward (real but weaker)

scheduler god-file split (1,842 lines — fold into next touch); per-strike OI-build velocity + aggressor-ratio z-score (adjacent to parked flow signals — validate #3 first); cross-ticker comparison page; table retention policy (bundle disk gauge into ops #1).
