# Next-Work Shortlist & In-Flight Inventory — 2026-07-04

A revisitable menu of what to build next in argon, merging two sources:

1. **argon-native backlog** — existing GitHub issues.
2. **radon → argon adoption candidates** — from the radon feature probe
   (`docs/research/2026-07-03-radon-feature-probe.md`), which ranked 5 radon
   capabilities worth porting into argon.

Plus a full inventory of the **in-flight / parked worktrees** so nothing gets
lost again.

> **Key fact that reframes the plan:** the radon-adoption list's item #2 — the
> reusable walk-forward backtest harness — was **shipped this session as PR #210**
> (`src/uw_scan/backtest/`). So the adoption plan is already **1-of-5 done**. The
> highest-leverage next move is therefore either *cashing in* that harness (#163)
> or taking the next-lowest-lift adoption item (SVI surface).

---

## The choice menu

### Group A — argon-native backlog (GitHub issues)

| # | Item | Value | Effort | Readiness |
|---|---|---|---|---|
| **A1** | **#163 — VRP kill-switch backtest** | ★★★★★ Tests tail-risk on the *only* validated edge (SPX bull-put spread, Sharpe ~1.65) using the harness just merged (#210). Fully spec'd: 3 gate designs (high-VIX cap / drawdown breaker / vol-floor) + a size-down control + fixed benchmarks (iter-3 base 1.68, SPY B&H 0.62). | M | ✅ ready |
| A2 | #180 — mega-cap TAPE coverage bug | ★★ 6 highest-traffic names (TSLA/NVDA/MSFT/GOOGL/META/AVGO) have permanently-blank TAPE column. Cosmetic, no analytical dependency. | S–M | ⚠️ runtime-gated — needs a live instrumented single-ticker run after the UW daily-429 reset to root-cause |
| A3 | #190 — market-tide history backfill | ★★ Enabling infra: unlocks regime/sentiment backtests. | M | ✅ ready |
| A4 | #167 — unify VRP harvest + surface + regime read | ★★ Research consolidation follow-ups. | M | ✅ ready (research) |

**Do NOT build (issue text itself says so):**
- **#202** (build `vrp_leg_nbbo` recorder) — feeds the single-name condor, which is **PARKED, no edge**. The issue says confirm a reason before investing. Skip.
- **#207** (rr_25d 30d-CM tenor fix) — the issue says "**do NOT build expecting better P&L** … ~0 rank-IC." Data-quality cosmetics only.

### Group B — radon → argon adoption (from the 2026-07-03 probe)

| # | Item | Value | Effort | Readiness |
|---|---|---|---|---|
| ~~R2~~ | ~~Reusable backtest / walk-forward harness~~ | — | — | ✅ **DONE — shipped as PR #210** (`src/uw_scan/backtest/`) |
| **R1** | **SVI no-arb surface fit → mispricing signal** | ★★★★ The probe's own #1. argon already banks the full-chain IV grid nightly (`worker/jobs/option_surface_capture.py` → `option_surface_grid_daily`) but uses it *only* as an IB freshness canary. SVI (Gatheral raw-SVI per expiry, butterfly/calendar constraints) turns the dead table into a rich/cheap edge. **No new data source.** radon ref: `scripts/vol_surface.py`. | M | ✅ ready |
| R3 | Alert rules engine + push notifications | ★★★ Turns pull-only signals (scanner, VRP-z, GEX/CRI/VCG flips) into push (Pushover/Discord). No new upstream data — a rule-eval job + notification sink on existing signals. radon ref: `scripts/alerts/evaluate.py`. | M | ✅ ready |
| R4 | Polymarket odds vs options-implied-prob divergence | ★★★ Net-new cross-market edge; same fetcher→storage→router shape as Gold Compass's FRED/GPR/CFTC blend. radon ref: `scripts/clients/polymarket_client.py`. | M–L | ⚠️ net-new data source |
| R5 | Order-book imbalance / microprice strip | ★★★ radon's most differentiated capability, but argon has **no L2 depth feed** — xenon's bridge only gives single-contract greeks + top-of-book spot. Needs new xenon-side plumbing first. radon ref: `scripts/microstructure.py`. | L+ | ❌ blocked on xenon |

**Explicitly skipped in the probe** (assume argon executes trades / holds a portfolio, which it deliberately does not): paper-trading/shadow-fill, IB whatIf margin preview, portfolio correlation risk-budget, node-graph workflow composer.

### Other raw radon candidates (surfaced, not carried into the top 5)
- X/Twitter sentiment via xAI live-search (`scripts/fetch_x_xai.py`) → could feed Trade Insights AI / scanner.
- LLM Token Expenditure Index (`scripts/llm_token_index.py`) → AI-cost trend as a macro-regime input; cheap, novel.
- OAuth-against-consumer-LLM-subscription auth — idea-stage in radon, no code.
- VPIN / toxic-flow — deferred inside radon too (needs its own T&S tape).

---

## Recommendation

Two genuinely good leads:

- **Compound what you just built → A1 (#163).** Tightest value/effort ratio on the
  board. You paid for the harness; #163 is the payoff, and it interrogates the tail
  risk of the one strategy with real capital behind it. argon-native, spec'd, ready.
- **Keep executing the radon-adoption plan → R1 (SVI surface).** Your own top-ranked
  adoption item, lowest-lift, no new data, activates a table you already fill nightly.

Everything else is infra/ops (A3, R3), blocked (A2, R5), or a bigger new-data lift (R4).

---

## In-flight / parked worktree inventory

State as of 2026-07-04. All work is now committed (loose-file rescue done this
session — 2 worktrees were entirely uncommitted and are now on branches + draft PRs).

| Worktree / branch | Commit | Pushed? | PR | Status & revisit trigger |
|---|---|---|---|---|
| `fix/skew-tab-demote` | `9cf5e12a` | ✅ | **#208 OPEN, CI green** | **Ready to merge.** Demotes non-tradable Skew verdict to a positioning descriptor + research trace. Free win. |
| `misc/alpha191-short-swing-scan` | `40e1dcef` | ✅ | **#212 draft** | Preserved short-swing equity research sweep (scripts + persisted traces under `docs/research/alpha191-short-swing/`). Research, not merge-bound. |
| `misc/uw-historical-alpha-scan` | `cda87173` | ✅ | **#213 draft** | WIP UW historical-alpha backfill feature (today-dated). **Pre-merge blocker:** migrations numbered 095/096 collide with main's `095_backtest_harness.sql` → renumber to **096/097** before merge. |
| `feat/darkpool-points` | `bc9190ea` | ❌ local only | — | PARKED. "Buy-pressure leads price ~4d" is mostly market beta; OOS persistence n.s. after market-neutralization. Narrow alpha core survives in ANET/NVDA/COIN/PLTR/TSM. **Revisit trigger: re-run `darkpool_oos_markout.py` on ≥90 fresh live days (~late Aug 2026)** — don't re-slice current data. |
| `misc/momentum-moments` | `30287f75` | ❌ local only | — | PARKED. Barroso–Santa-Clara risk-managed momentum. Scaler validated (Sharpe 0.42→0.83, kurt 12.9→3.0) but **no ready-to-trade strategy yet** — needs more constituent history argon doesn't have. Resume options in memory `project_momentum_moments`. |
| `chore/strategic-master-plan` | `73b8d3b5` | ❌ (empty) | — | Empty scaffold, no work. Remove if not needed. |

**Stale open argon PRs (cleanup candidates):** #93 (`vcg-positioning-docs`, May 27, docs) and #97 (`canary-wf5-fwd-return-probe`, May 28, research) — both green but likely superseded (canary v2-A was STOP'd). Decide merge-or-close.

---

## Source pointers
- radon feature probe: `docs/research/2026-07-03-radon-feature-probe.md`
- radon repo: `~/projects/radon` (feature catalog `docs/features.md`; tracker is `tasks/*.md`, no gh issues)
- argon backtest harness (shipped R2): `src/uw_scan/backtest/` + `docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md`
- #163 spec detail: the issue body (3 gate designs + reproduce via `scripts/research/vrp_robustness_run.py` → `iter5-killswitch.csv`)
