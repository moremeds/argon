# Candidate Master Menu — unified (2026-07-07)

Single ranked menu merging the **2026-07-06 sweep** (`2026-07-06-candidate-index.md`, 6 picks)
and the **2026-07-07 sweep** (`2026-07-07-brandnew-improvement-candidates.md`, 5 picks →
issues #223–#227). Supersedes both split indexes as the thing to revisit. Uniform schema
per row; full detail in the source docs / issue bodies (Anchor column).

**Class:** alpha · product · perf · ops · refactor · new-page
**Status:** LIVE (open) · PARTIAL · DONE · KILLED · GATED (falsify first)

> **Resolution audit (2026-07-07):** C8.1 deploy-gate = **DONE** (#222, c075d8c — gate now `.ok == true`).
> C11 GEX = **DONE/killed** (#228 committed the negative-result doc). C2 = **PARTIAL** (per-cohort
> entry read endpoints exist in `regime.py`; no positions list / P&L / `/today`). All others confirmed
> unbuilt.

## Master table

| ID | Title | Class | Effort | Value | Status | Anchor |
|----|-------|-------|--------|-------|--------|--------|
| C1 | UW same-day fetch dedupe cache | ops | M | ★★★★★ | LIVE | #225 · `sources/uw.py` |
| C2 | Trade-lifecycle layer (positions/P&L/`/today`) | product | M | ★★★★★ | PARTIAL | #223 · `vrp_macro_entry` |
| C3 | Exploit `uw_positioning` (card + screener) | product | S–M | ★★★★ | LIVE | #224 · migration 065 |
| C4 | Flow-vs-RV−IV residualization verdict | alpha | S–M | ★★★★ | LIVE | #227 · `matrix_state_snapshots` |
| C5 | Implied-corr / dispersion gate on VRP edge | alpha | M | ★★★★ | GATED | #226 · `#210` harness |
| C6 | Charm/vanna per-strike positioning + term slope | alpha | M | ★★★ | GATED | `2026-07-06-candidate-charm-vanna-positioning.md` |
| C7 | `/stock/{ticker}` perf (N+1, pool, cache) | perf | S+M+S | ★★★★ | LIVE | `...-stock-page-perf.md` |
| C8 | Ops-hardening (alert sink, staleness, agg, budget attr) | ops | S→M | ★★★ | PARTIAL | `...-ops-hardening.md` · #222 |
| C9 | Observability dashboards (backtest/provider/benchmark) | new-page | M | ★★★ | LIVE | `...-observability-dashboards.md` |
| C10 | Quant Technicals tab | new-page | M–L | ★★★ | LIVE | `...-quant-technicals-page-design.md` |
| C11 | GEX regime-persistence | alpha | — | — | DONE (killed) | `2026-07-06-gex-regime-persistence-result.md` · #228 |

## Per-candidate detail (uniform)

### C1 — UW same-day fetch dedupe cache · ops · M · ★★★★★ · LIVE
- **What:** 6+ jobs (surface capture, cockpit, flow refresh, skew greeks, vrp entry, full_scan) independently re-fetch identical per-ticker contract/greek data daily; governor gates spend but doesn't dedupe. Add a `(ticker, endpoint, as_of_date)` memo in `sources/uw.py`.
- **Why:** budget dies by 08:00 ET; every reclaimed request becomes research budget → unblocks parked alpha-probe, prevents #180 gaps.
- **Next:** build the memo layer before `fetch_option_contracts`/`fetch_greek_exposure_by_expiry`. Do early — multiplies all data-hungry work.

### C2 — Trade-lifecycle layer · product · M · ★★★★★ · PARTIAL
- **Already there:** `regime.py:541/586/587` reads the **current cohort's** entry + quotes (`fetch_vrp_macro_entry[_quotes]`) for the MacroShortVol card. That's a single-entry preview, not a portfolio.
- **Still missing:** a "list ALL my entries" positions router, per-entry markout/P&L curve, expiry status, and the `/today` briefing page (no `web/app/today`).
- **Why:** substrate #163 needs; render target future alerts need; reusable entry→marks→P&L for every signal.
- **Next:** generalize the existing per-cohort read into a list+P&L router, then `/today`.

### C3 — Exploit `uw_positioning` · product · S–M · ★★★★ · LIVE
- **What:** migration 065 (SI %float, days-to-cover, borrow fee/rebate, analyst targets, insider net flow, ER base rates) read only by the LLM prompt (`trade_insights.py:351`). Build Positioning card + squeeze/insider/analyst screener.
- **Why:** fresh data, zero new fetch; orthogonal to the dead price-pattern space.
- **Next:** card + screener; deeper cut parses discarded 13F/insider `raw_jsonb`.

### C4 — Flow-vs-RV−IV residualization verdict · alpha · S–M · ★★★★ · LIVE
- **What:** Goyal–Saretto collapse 46 option chars to ~RV−IV (all dead net of costs) but have NO aggressor flow / vanna / charm. Residualize argon's flow signals against RV−IV cross-sectionally, net of 30% spread.
- **Why:** highest decision value on the board — a clean negative prunes the whole positioning stack; a positive is a new axis.
- **Next:** residualize 3-day aggressor imbalance (+ net vanna/charm) vs RV−IV; decile-sort fwd 1/5d returns. Cheapest big-information research.

### C5 — Implied-corr / dispersion gate · alpha · M · ★★★★ · GATED
- **What:** index IV richness = vol premium + correlation premium; the edge sizes only on vrp-z. Add implied-corr richness as a second orthogonal axis. All data in hand.
- **Why:** best new-alpha bet — extends the one working edge; literature-backed (dispersion premium).
- **Next:** ~1-day falsification — implied-corr proxy z-score, is short-vol P&L monotone in its buckets? Not monotone → kill.

### C6 — Charm/vanna per-strike positioning + term slope · alpha · M · ★★★ · GATED
- **What:** `option_surface_grid_daily` banks per-strike vanna/charm nightly, read by nothing. Net charm → expiry-week delta drift; net vanna → hedging direction on IV moves. Bundle durable ATM term-structure slope.
- **Why / caveat:** per-strike history unrecoverable — urgency to start banking. BUT **C4 gates this** — don't accrue the derivation job until flow-beats-RV−IV survives; C11's result already leans skeptical on the whole family. NOT SVI, NOT skew (both closed-negative).
- **Next:** run C4 first; if it survives, C6 becomes the build.

### C7 — `/stock/{ticker}` perf · perf · S+M+S · ★★★★ · LIVE
- **What:** (1) N+1 — `_build_intraday_profiles` calls `fetch_buckets` 10× per load → batch `WHERE (option_symbol, trade_date) = ANY(...)`. (2) No conn pool (`api/deps.py`) → `psycopg_pool`. (3) Report cache per `(ticker, run_id)`.
- **Why:** busiest read path; `/watchlist/spots` polled every 2.5s per tab.
- **Next:** N+1 batch is the standalone win; conn pool rides the Docker cutover.

### C8 — Ops-hardening · ops · S→M · ★★★ · PARTIAL
- **DONE:** (1) deploy health-gate now checks `.ok == true` — shipped #222 / c075d8c (`macmini-prod.sh:128,148`). Confirmed.
- **Still open:** (2) alert sink (Pushover/Discord), (3) R2 lake-staleness on `/api/health`, (4) job-failure aggregation via `EVENT_JOB_ERROR`, (5) per-job UW budget attribution (data exists, API hides it).
- **Next:** parts 2–5; all survive Docker.

### C9 — Observability dashboards · new-page · M · ★★★ · LIVE
- **What:** 3 built-but-unwired backends — Backtest Sweep Explorer (`backtest_sweep_*`, no router/page), Provider-Usage/budget gauge (`provider_usage.py`, 4 endpoints no UI), Pipeline-Benchmark scorecard (`benchmark.py`, no page).
- **Why:** one web sprint surfaces finished work; natural home for #163 results.
- **Next:** thin routers + pages. Backtest explorer first (pairs with C2).

### C10 — Quant Technicals tab · new-page · M–L · ★★★ · LIVE
- **What:** new `/stock/[ticker]` tab, all dimensionless. 5 panels: sigmoid trend-maturity (must beat linear R²), MA kinematics (ATR-norm t-stat), return-distribution, RSI/MACD enhanced. Composite z. Data via apex `/bars` over Tailscale; persists `technical_daily` → graduates to a testable signal after ~60 sessions.
- **Next:** confirm apex bar-history depth across watchlist; your idea, already designed.

### C11 — GEX regime-persistence · alpha · KILLED
- **Verdict (tested 2026-07-07):** SPY n=31, short-gamma |fwd ret| 0.82% vs 0.50% but boot95 CI kisses 0 (p=0.41) AND vol-clustering confounded; trend-vs-reversal refuted (0.53 vs 0.55).
- **Next:** keep banking the label; re-test at n≈90 (~2026-09-01) vol-normalized. Do NOT build now.

## Sequencing (unchanged from the two source docs)
1. **C1** (dedupe) — multiplies everything downstream, do first.
2. **C4** (flow verdict) — cheapest big-information research; **gates C6**.
3. **C2 / C3** — product wins, zero new data, sit on the validated edge.
4. **C5** — best new-alpha bet (1-day falsify).
5. **C7** — biggest latency win; conn-pool rides Docker.
6. **C8** — verify #222 first; then ops parts 2–5.
7. **C9 / C10** — web sprints once backends/data are proven.
- **C11** parked. **C6** blocked on C4.

## Overlap notes
- **C4 gates C6** — same signal family (does flow/vanna/charm beat RV−IV?). Run C4's residualization before accruing C6's derivation job.
- **C8 part 1 likely == #222** — verify before rebuilding.
- **C9 backtest explorer + C2 lifecycle** share the `/backtest`+positions surface; build adjacent.

Reproduce: this doc consolidates the two source sweep docs; no new probing.
