# Radon Feature Probe — 2026-07-03

Source repo: `~/projects/radon` (VERSION `0.7.0` at probe time, verified via `cat VERSION`).
Purpose: full-repo pass over radon to identify feature candidates argon could adopt, since
radon and argon overlap conceptually (both run CRI / GEX / VCG regime scanners) despite
different scope — radon executes trades via IB and holds a portfolio; argon is read-only
analytics/scanner over UW + massive data with no execution and no portfolio object.

Method: dispatched an Explore subagent over the radon working tree (CLAUDE.md, git log,
docs/, tasks/, scripts/, web/) with instructions to cite concrete file paths. A follow-up
manual spot-check (`ls`, `cat VERSION`, `find -iname "*changelog*"`) confirmed the load-bearing
file-existence claims below (marked ✅ verified). Commit-hash citations came from the subagent
pass only and were not independently re-verified — treat those as reported, not confirmed.

## What radon is

A solo-operator market-structure reconstruction / trading terminal: detects institutional
positioning from dark-pool/OTC flow, IB, Unusual Whales, and MenthorQ CTA data, designs convex
options structures, sizes with fractional Kelly. Every candidate trade passes a **Four-Gate
framework**: Convexity (gain ≥ 2x loss), Edge (specific data-backed signal), Risk (fractional
Kelly, 2.5% bankroll cap), and a currently-disabled no-naked-shorts gate. Stack: Python 3.13 +
Next.js 16/bun + Turso libSQL (cloud DB, no embedded replica) + JSON disk fallback. Four live
processes (Next.js :3000, FastAPI :8321, IB WS relay :8765, newsfeed scraper). `git push origin
main` is the deploy (GitHub Actions → SSH → `scripts/deploy.sh`).

**No `CHANGELOG.md` exists in radon** ✅ verified (`find . -maxdepth 1 -iname "*changelog*"`
returns nothing at repo root; the only hit anywhere is an unrelated
`data/presets/changelog.json` scanner-preset log). The large feature list pasted into this
session (LEAP+GARCH tabs, Turso source-of-truth, FinCept Adoption suite, etc.) matches radon's
git commit history near-verbatim per the subagent's pass — it reads as commit-log-derived, not
pulled from a maintained doc.

## Confirmed-shipped items from the pasted list (subagent-reported, spot-checked subset ✅)

All of the following were reported as present with commit/file evidence; independently spot-checked
✅ for `scripts/vol_surface.py`, `scripts/backtest/`, `scripts/alerts/evaluate.py`,
`scripts/clients/polymarket_client.py`, and `VERSION`:

- LEAP + GARCH candidate tabs on the scanner page
- NYSE advance/decline BREADTH tab on `/regime`, IB-fed collector (`scripts/breadth_scan.py`,
  `web/app/regime/breadth/page.tsx`)
- Turso as source-of-truth for previously disk-only routes (menthorq, journal, blotter)
- DB performance: bounded connection pool + reset-on-timeout, TTL read cache on hot polled
  routes, journal effective-time index + SQL-aggregate next-id
- IV skew telemetry for risk-reversal orders
- Calibrated gauge in instrument panel (global edge marker)
- Demo environment: trial gate/blockade/quotas/rate-limit/admin (Phases 1–6), Yahoo futures
  fallback + newsfeed mirror, Vercel→demo-VM trusted-service FastAPI auth
  (`docs/demo-environment.md`)
- Sign-out control (desktop header + mobile sticky CTA)
- IB Gateway sidecar removed (dropped `willfarrell/autoheal` + docker.sock mount)
- Tooltip flip on measured popup height (was a 120px guess)
- Journal end-of-session blind spot fixed + retroactive backfill hardening
- GitHub Actions deploy gate bound to a gated GitHub Environment
- **FinCept Adoption suite, all 14 features** ✅ (dirs verified): paper trading / shadow-fill
  engine (`scripts/paper/`), strategy backtester + walk-forward harness (`scripts/backtest/`),
  order-book imbalance + microprice microstructure (`scripts/microstructure.py`), SABR/SVI
  vol-surface fit (`scripts/vol_surface.py`), agentic tool-calling assistant loop
  (`web/lib/assistant/`), user-configurable alert rules engine (`scripts/alerts/evaluate.py`),
  visual flow-pipeline node-graph composer (`scripts/workflow/`, `web/app/workflow/`), informed
  flows (Congress/insider), Polymarket event-odds client (`scripts/clients/polymarket_client.py`).
  Plan: `tasks/fincept-adoption-todo.md`; ship report: `tasks/fincept-adoption-ship-report.html`.

Caveat noted by the subagent: `docs/features.md` in radon is untracked in git and its mtime
predates the FinCept merge — it's a stale snapshot, don't trust it as current inside radon
either.

## 5 candidates identified for argon (ranked as presented to the user)

1. **No-arbitrage SVI vol-surface fit → surface mispricing signal.** Radon's
   `scripts/vol_surface.py` fits Gatheral raw-SVI per expiry with butterfly/calendar
   no-arbitrage constraints, feeding the fitted-vs-marked residual into risk-reversal/LEAP
   scanners instead of raw point IV. Argon already captures the raw ingredient nightly
   (`option_surface_capture.py` full-chain IV grid) but only uses it as an IB freshness canary,
   not a mispricing signal. Lowest-lift candidate — no new data source, layers on an existing
   captured table.

2. **Reusable backtest + walk-forward harness** (item started — see worktree below). Radon:
   `scripts/backtest/{engine,cost_model,metrics,signal_replay,strategies}.py`, a generic
   no-look-ahead walk-forward runner. Argon has repeatedly hand-rolled this per-study
   (`_vrp_macro_param_sweep.py`, `darkpool_oos_markout.py` per project memory) and has a standing
   rule ("persist every research/backtest trace") written *because* an unsaved sweep result
   ("Sharpe ~2.0") turned out unreproducible (true figure: 1.65). A shared harness fixes a
   problem argon has already paid for once.

3. **User-configurable alert rules engine + push notifications.** Radon:
   `scripts/alerts/evaluate.py` + watchdog's Pushover/Discord dispatch. Argon's scanner, VRP-z
   signals, and GEX/CRI/VCG regime flips are all pull-only today (dashboard/API). No new
   upstream data needed — a rule-eval job + notification sink on top of existing signals.

4. **Polymarket odds vs. options-implied-probability divergence.** Radon:
   `scripts/clients/polymarket_client.py`. Cross-market edge signal, same fetcher →
   storage → router shape argon already uses for Gold Compass's FRED/GPR/CFTC blend. Net-new
   data source, more integration lift than 1–3.

5. **Order-book imbalance / microprice strip** (flagged as the expensive one). Radon:
   `scripts/microstructure.py` + `MicrostructureStrip.tsx`. Argon has no L2 depth feed —
   xenon's bridge (`xenon_query.py`, `xenon_ws.py`) only gives single-contract greeks snapshots
   and top-of-book spot ticks, not order-book depth. Would need new xenon-side plumbing first.
   Included because it's radon's most differentiated capability, not because it's cheap.

**Explicitly skipped as poor fits for argon:** paper trading/shadow-fill, IB `whatIfOrder`
margin preview, portfolio correlation risk-budget guard, visual node-graph workflow composer —
all assume argon executes trades or holds a portfolio, which it deliberately does not (API is
read-only, mutations only via `/jobs`).

## Other raw candidates surfaced but not carried into the top 5

(From the subagent pass — not independently verified beyond file existence; re-check before acting.)

- X/Twitter sentiment + ticker extraction via xAI's live-search API
  (`scripts/fetch_x_xai.py`, `scripts/fetch_x_watchlist.py`) — could feed argon's Trade Insights
  AI or scanner as an informed-flow-like signal.
- OAuth-against-consumer-LLM-subscription auth (`docs/oauth-subscription-auth.md`) — idea-stage
  only in radon, no implementing code; would reduce AI provider costs if ever built.
- LLM Token Expenditure Index (`scripts/llm_token_index.py`) — treats AI inference cost trends
  across model families as a macro-regime input; novel, cheap, no new infra category.
- VPIN / toxic-flow signal — explicitly deferred inside radon too, pending its own Time & Sales
  tape.

## Directory structure summary (radon)

```
radon/
├─ CLAUDE.md / README.md / PROGRESS.md   Runbook, product overview, dated dev log
├─ scripts/                              Python: scanners, evaluators, broker adapters, daemons
│  ├─ clients/                           Broker/data-provider adapters (IB, UW, MenthorQ, Polymarket)
│  ├─ api/                               FastAPI server (server.py)
│  ├─ db/                                Turso writers + SQL migrations
│  ├─ backtest/ paper/ workflow/ alerts/ FinCept-adoption feature modules
│  └─ ~90+ top-level *.py scripts        evaluate.py, gex_scan.py, cri_scan.py, vcg_scan.py, vol_surface.py, microstructure.py, portfolio_risk.py, ...
├─ web/                                  Next.js 16 terminal + Clerk auth
│  ├─ app/                               [ticker], admin, alerts, cta, journal, kit, orders, regime/*, scanner, workflow
│  └─ components/ticker-detail/          "Cockpit" per-ticker workspace
├─ site/                                 Standalone marketing site (separate Vercel project)
├─ docs/                                 ~35 topic docs
├─ tasks/                                Session logs, plans, ship reports, backlogs
└─ config/                               launchd plists per background service
```

## Standout radon capabilities (context, not necessarily candidates)

- Gatheral raw-SVI vol-surface calibration with no-arbitrage constraints
- Cross-asset regime stack: CRI, VCG-R, GEX, GRG — now feeding a walk-forward backtester
- Order-book microstructure (signed imbalance + microprice), RTH-only, entitled L2 depth
- MenthorQ CTA vol-targeting positioning ingestion via Playwright vision extraction
- LLM Token Expenditure Index as a macro-regime input
- Polymarket prediction-market odds vs. options-implied-probability divergence
- Visual, gated node-graph strategy composer reusing the same Kelly/gate logic as manual trading
