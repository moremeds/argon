# Brand-New Improvement Candidates — 2026-07-07 system scan

Five-probe scan (data-assets, alpha ideation, code health, perf/ops, product/UX)
looking for candidates **not** already on the backlog / shortlist / worktrees.
Exclusions honored: all open issues (#163/167/180/190/202/203/207/118/90/89/86),
SVI fit, alerts engine, Polymarket, L2 book, DeepSeek tab, Docker migration,
every folded/parked research line.

Filed as GitHub issues: #223 (pick 1), #224 (pick 4), #225 (pick 5), #226 (pick 2), #227 (pick 3).

## The 5 picks (decision)

### 1. Trade-lifecycle layer: positions, P&L attribution, review — close the loop on the live edge
The system is strong at signal computation + persistence and has **nothing** for
tracking/review. `vrp_macro_entry` banks a full markout series (8 marks/day × 30d
per captured entry) and **no router or UI reads it back** — capture-and-forget.
No "list my entries", no P&L curve, no `/today` briefing, no regime replay.
- Build: read-only router over `vrp_macro_entry` → Positions panel (open entries,
  per-entry markout/P&L, expiry status) → then a `/today` briefing page composing
  regime state + VRP signal + open entries + scanner hits + health warnings.
- Why it compounds: it's the substrate #163 (kill-switch) needs, the render target
  the future alerts engine needs, and a reusable entry→marks→P&L pattern for every
  future signal. Sits directly on the only validated edge (Sharpe ~1.65).
- Effort M. Pure read-composition of existing tables.

### 2. Implied-correlation / dispersion richness gate on the validated index VRP edge
Index IV richness = vol premium + **correlation premium**. The macro edge sizes only
on vrp-z (IV−RV level); implied-corr richness is a second, near-orthogonal axis.
All data in hand: VIX / `vol_index_daily`, `option_surface_grid_daily` (SPX/QQQ),
component IVs in `vrp_daily`/`stock_analytics_daily`, pairwise realized corr from
`daily_ohlc`, backtest via the #210 harness.
- First falsification (~1 day): rolling implied-corr proxy
  ρ ≈ (σ²_idx − Σw²σ²)/(Σwᵢwⱼσᵢσⱼ) from VIX vs top-10 component IVs; z-score;
  test whether index short-vol P&L is monotone in ρ-z buckets. Not monotone → kill.
- Prior MED. Extension of the one working edge, untouched hypothesis space,
  literature-backed (Driessen–Maenhout–Vilkov dispersion premium).

### 3. Flow-signal verdict: do UW aggressor/vanna/charm signals beat RV−IV? (systematic residualization)
Goyal–Saretto: 46 option characteristics collapse to ~1 factor ≈ RV−IV, all dead
net of 30% quoted spread — but their set contains **no aggressor-tagged flow, no
GEX/vanna/charm**. Whether UW-native signals survive residualization against RV−IV
is the one question only argon can answer, and it's unbuilt. Data:
`matrix_state_snapshots`, `flow_events`, `vrp_daily`, ~12mo × ~100 names.
- First test: residualize 3-day aggressor premium-imbalance (+ net vanna/charm)
  against RV−IV cross-sectionally; decile-sort fwd 1/5-day returns; report net of
  30% spread vs the RV−IV-only spread.
- Prior LOW–MED that flow survives, but **highest decision value on the board**:
  a clean negative prunes the entire positioning-signal stack argon is built on;
  a positive is a new alpha axis. Either way it recalibrates the roadmap cheaply.

### 4. Positioning intelligence: exploit `uw_positioning` (banked daily, read by nothing but an LLM prompt)
Migration 065; refreshed daily; contains short interest %float, days-to-cover,
**borrow fee/rebate rates**, analyst counts + targets, institutional counts/value,
insider buy/sell/net flow, earnings-reaction base rates, next ER date. Sole reader:
`api/routers/trade_insights.py:351` (prompt stuffing). No endpoint, panel, or signal.
- Build: stock-page Positioning card + watchlist screener (squeeze-risk:
  si_pct_float × days_to_cover × fee-rate spike; insider net-flow tilt; analyst
  implied upside; pre-ER reaction base rate). Optional cross-sectional signal
  research on top (borrow-fee spikes are a documented return predictor).
- Value HIGH / effort LOW–MED — the data is already there and fresh. New
  information axis orthogonal to the dead price-pattern space. Deeper cut: parse
  the 13F/insider `raw_jsonb` already fetched-then-discarded.

### 5. UW same-day fetch dedupe cache — attack the binding constraint
Budget is chronically exhausted by 08:00 ET, and 6+ jobs independently re-fetch
the same slow-moving contract/greek-exposure data per ticker per day
(`option_surface_capture`, `cockpit_daily_snapshot`, `flow_data_refresh`,
`skew_swing_greeks`, `vrp_macro_entry`, full_scan `pipeline.py`). The new budget
governor gates spend but does not dedupe.
- Build: a `(ticker, endpoint, as_of_date)` memo layer in `sources/uw.py`
  (DB-backed or in-proc per worker-day) consulted before `fetch_option_contracts`
  / `fetch_greek_exposure_by_expiry`.
- Why it compounds: every reclaimed request is research budget — this directly
  unblocks the parked alpha-probe line and prevents #180-style silent gaps.
  Effort M.

## Runner-ups (worth doing, not top-5)
- **config.py → pydantic-settings** (893 lines, 127 manual `os.environ.get` dup of
  139 declared fields) + a **live test-isolation bug found by the probe**:
  `tests/unit/test_settings_option_surface.py::test_settings_reads_option_surface_flags`
  fails in the full suite on this machine (`.env.local` Tailscale URL leaks past the
  expected default; order-dependent). Fix the bug regardless.
- **scheduler.py declarative job table** (1842 lines, 63 add_job calls, imperative).
- **Sector-neutral single-name short-vol basket** (cash in the validated
  `vrp_harvest_by_sector` finding via the harness; condor died on execution, not premium).
- **Backtest-sweep browser** (`backtest_sweep_*` tables have zero read surface).
- **`option_intraday_buckets` retention job** (unbounded append, ~400k rows/day at
  full coverage); **QueueProgress `document.hidden` guard**; **remove unused `d3` dep**;
  **`api/routers/regime.py` at 1057 lines** needs a split plan.

## Sequencing view
#5 (budget dedupe) multiplies all future data-hungry work → do early.
#1 (lifecycle) and #4 (positioning card) are product wins with zero new data.
#3 is the cheapest big-information research; #2 is the best new-alpha bet.

Reproduce: 5 parallel probe agents, 2026-07-07 session (this doc is the trace).
