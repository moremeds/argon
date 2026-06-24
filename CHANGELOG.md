# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Added

- VRP macro **forward entry-capture & markout recorder**: records the real forward
  NBBO + greeks of the SPX bull-put-spread the Macro Short-Vol signal would place,
  tracked daily to expiry. A daily-born `auto` cohort (the 4 put contracts bracketing
  the 0.25Δ short / 0.125Δ wing at ~43-cal-DTE) is snapshotted **8×/day** (10:00–15:00
  ET hourly + 15:55 EOD + 16:10 post-close), tapering to EOD-only after 30 calendar
  days. Each leg quotes **xenon/IB-primary** (true NBBO + IV) → **UW fallback** →
  **greeks always BS-computed** from the marked IV (one-model: IB theta is per-day, BS
  per-year — never mixed). New table pair (`vrp_macro_entry` + `vrp_macro_entry_quote`,
  migration `085`), `reports/vrp_macro_entry.py`, `worker/jobs/vrp_macro_entry.py`
  (massive-0, gated by `vrp_macro_entry_capture_enabled`), and
  `GET/POST /api/regime/vrp-macro-signal/entry/{preview,capture}`. The Macro Short-Vol
  regime card gains a strike/ETD preview panel (served from the persisted snapshot —
  zero IB, zero new UW) + a one-click Capture button; the "(gate at 0)" / "stand aside"
  copy is dropped. Live-verified against prod IB (3/4 legs `source=xenon_ib`). Also
  fixes the stale `xenon_query_api_url` default (`:8421`, which was dead → silently
  no-op'd the surface IV canary too) to the mini's authenticated `:8321`; deploy must
  set `XENON_QUERY_API_KEY` in the mini's argon `.env` or the IB path falls back to UW.
  Plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`.
- GOAS put-write delta sweep (research): a self-contained study finding the short-put
  **delta + tenor sweet spot** for the Goldman Options Advisory Strategy (systematic
  always-on OTM index put-writing). Three new `reports/` modules —
  `goas_putwrite_pricing.py` (a parametric downside-skew layer `iv(K)=atm·(1−slope·ln(K/S))`
  calibrated to GOAS's one published quote: 2026-05-05 SPY 96.2%-strike / 0.700%-premium →
  slope 2.693, with flat-vol as the conservative floor), `goas_putwrite_account.py` (a
  laddered, defined-risk **cash-secured** put-write NAV book — held to expiry, intrinsic
  settlement, fair-value daily marks, collateral earning the risk-free per CBOE PUT-index
  convention — plus `curve_metrics`/`putwrite_metrics` and a SPY buy-hold benchmark), and
  `goas_putwrite_sweep.py` (delta×tenor×pricing×fee sweep with regime slices and a
  per-regime catastrophe-gated ranking; management fee modeled as a downstream NAV drag,
  copying GOAS's own fee framing). Runner `scripts/research/goas_putwrite_run.py` reads SPY+VIX
  daily closes directly from the market-warehouse lake (2006→, ~20.4y, no Postgres/network)
  and writes five full-trace artifacts + a master findings note under
  `docs/research/goas-putwrite/`. Headlines: gross Sharpe rises monotonically with delta but
  short (21d) weekly writing fails catastrophically in fast crashes (COVID Sharpe −1.6) — the
  binding constraint is **tenor, not delta**; net-of-1%-fee gated sweet spot is **0.30Δ/63d**
  (Sharpe 0.147), conservative pick **0.15Δ/63d** (Sharpe 0.108, maxDD −14%, 95% win-rate).
  Every unlevered cash-secured cell trails SPY buy-hold risk-adjusted (best 0.15 vs 0.34) but
  at 2–4× smaller drawdown — the premium harvest above cash is only ~0.5–1.4%/yr, so GOAS's
  3–6% net target requires the 20–40% leverage this defined-risk study excludes. Reproduce:
  `uv run python scripts/research/goas_putwrite_run.py`.

## [0.3.1] — 2026-06-23


### Added

- VRP backtest iteration 4 (research): robustness suite on the SPX macro short-vol
  WINNER — `reports/vrp_robustness.py` (min viable capital, SPY buy-and-hold benchmark,
  geometric compounding metrics, weekday sweep, bear-start study, and a seeded
  Monte-Carlo suite: entry-timing jitter, stationary block bootstrap, randomized
  start incl. a GFC-windowed variant, config perturbation) plus six backward-compatible
  flags on the `vrp_capital_account` ledger (compounding, entry-weekday, entry-jitter,
  staggered extra tranche) that reconcile byte-for-byte to the iteration-3 path when off.
  Runner `scripts/research/vrp_robustness_run.py` writes seven `iter4-*.csv` full traces
  (per-config + per-trial Monte-Carlo + long-form bear-start equity path); findings in
  `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` + an Iteration-4 section of
  the master report. Every experiment benchmarked against the iteration-3 SPX base case
  and SPY buy-and-hold. Headlines: the staggered extra tranche marginally beats the base
  (Sharpe 1.71 vs 1.68) while the contract overlay is exposure-not-edge; entry weekday
  matters modestly (1.33–1.53, all below the 1.65 stride); starting at a bear top still
  earns +150–180% over 36m; and config-perturbation p5 Sharpe 1.05 shows the result is
  not a knife-edge overfit. SPX vol-selling is six-figure-capital (one spread's max-loss
  rises ~15× to ~$28k by 2026).
- VRP capital-utilisation backtest (research): new `reports/vrp_capital_account.py`
  — a single shared **$50k cash-account ledger** (`CapitalConfig`,
  `desired_contracts`, `simulate_account`, `account_metrics`) that *reuses* the
  validated macro short-vol `WINNER` engine to measure annualised return, capital
  utilisation, skip/fill rates, Sharpe and max-drawdown on a real dollar account
  (integer contracts floored to a risk-% of capital, capital-capped with logged
  skips). Reconciles exactly with `backtest_laddered` (Δ Sharpe 0.000). Adds SPY
  to macro `INDEX_SPECS`, a sweep runner (`scripts/research/vrp_capital_sweep.py`)
  with full-trace CSVs, and an executed findings notebook + verdict/master report
  under `docs/research/vrp/` (single-name SPX beats the 3-name blend; the overlay
  is leverage not edge; compounding sweet spot ≈ stop at 4–8×). New `research`
  dependency group (matplotlib/nbconvert/ipykernel) for the notebook only.
- Option-surface historical backfill: `option_surface_backfill` function and
  `scripts/option_surface_backfill.py` runner seed `option_surface_grid_daily`
  for up to 30 past trading days in one shot. UW `/greek-exposure/expiry` and
  `/greeks` both accept an optional `date=` param (now forwarded by the fetchers);
  dates already in the table are skipped. Run promptly after first deploy — UW
  403s beyond ~30 trading days.

### Fixed

- `reports/vrp_macro_drawdown._lake_spot` now skips lake rows with a null
  `trade_date`. SPY's equity-lake parquet carries ~73% null-date rows (an
  alternate-schema partition); without the guard `load_index_vol("SPY")` raised
  `TypeError` on the `d >= start` comparison. No-op for symbols with clean dates
  (QQQ/IWM).


## [0.3.0] — 2026-06-23


### Added

- Option-surface capture: a nightly, forward-accumulating per-strike IV/greeks
  grid for every watchlist ticker (`option_surface_grid_daily`, migration 077),
  plus an ATM IB-vs-UW IV canary (`iv_source_validation`, migration 078). New
  `option_surface_capture` job (19:00 ET) and `option_surface_iv_canary` job
  (19:30 ET) on the uw-0 worker, Mon–Fri. Enumerates the full term structure via
  `greek-exposure/expiry` — not `/option-contracts`, which UW silently caps at
  500 contracts by volume and so drops long-dated expiries (measured: SPX 28/53
  missing). One `/greeks` call per expiry, idempotent upsert, per-ticker failure
  isolation. The surface only accrues forward: UW returns 403 for per-strike
  history beyond ~30 trading days, so every uncaptured night is permanently lost.
## [0.2.3] — 2026-06-22


### Fixed

- Release pipeline no longer wedges the mac-mini auto-deploy on `uv.lock` drift.
  `cut.sh prepare` now re-locks `uv.lock` so its editable self-version tracks the
  version bump and commits it with the release, and `version_sync_check` (run via
  system `python3` before `uv sync` in CI, so a stale committed lock can't be
  auto-repaired and hidden) fails the build if the lock self-version ever drifts
  from `VERSION` again. Previously the committed lock lagged the bump; the first
  `uv run` on any host rewrote that one line, dirtied the tree, and the deploy
  poller refused every deploy — silently pinning prod to the last-deployed
  release (the mini sat on v0.1.2 for 4 days while v0.2.0–v0.2.2 published).
## [0.2.2] — 2026-06-22


### Added

- VRP macro signal deploy slice: nightly persistence + read API for the promoted bull-put-spread signal shipped in 0.2.1. New `vrp_macro_signal_daily` table (migration 083), `vrp_macro_signal_refresh` job (03:45 ET, Mon–Fri, primary worker — runs SPX/QQQ/IWM weekly readout + `backtest_laddered` headline and persists one row per name per snapshot date, with per-name failure isolation), and `GET /api/regime/vrp-macro-signal` returning the latest signal per name. Closes the persist-every-research-trace gap for the VRP macro engine.
## [0.2.1] — 2026-06-22


### Added

- VRP macro signal engine (`reports/vrp_macro_signal.py`): promoted bull-put-spread winner config (Δ0.25 short, ramp+ vrp-z sizing, 30 trd-day hold) into first-class engine code with `WINNER` constant, `backtest_laddered` (SPX Sharpe 1.65 / QQQ OOS 1.00), and `current_macro_signal` weekly readout (TRADE/SKIP + modeled strikes/credit/max-loss)
- VRP macro research expansion (`reports/vrp_{candidates,backtest,directional,harvest_axes,gate,rv_validation}.py`): corrected-measurement engine, sector/horizon/directional/ΔVRP sweep axes, per-ticker iron-condor candidates, paper ledger, model-repriced weekly backtest
- Corporate actions refresh job (nightly 17:35 ET) for exact-RV split/dividend adjustment
## [0.2.0] — 2026-06-21


### Added

- VRP harvest markout (`reports/vrp_markout.py`, migration `079_vrp_harvest_verdicts`,
  `GET /api/regime/vrp-harvest`): scores whether selling rich vol (`vrp_z ≥ +1`) earns a
  reliable, positive premium per `(asset_class, deviation_class)` bucket. Reuses the skew
  engine's out-of-sample discipline — time-ordered walk-forward holdout plus a per-quarter
  catastrophic-degradation gate — over the existing `vrp_daily` panel, and excludes any
  forward window spanning a (flow-event-reconstructed) earnings date. Verdicts
  (`HARVEST_SELLABLE` / `NONE`) persist nightly at 18:50 ET (massive-0 worker) to
  `vrp_harvest_verdicts`; the RICH−CHEAP spread is recorded so a flat (no-edge) result
  stays legible.
## [0.1.2] — 2026-06-18


### Fixed

- Stock detail pages (Flow / Market Structure / GEX) no longer render empty
  during US off-hours. `Repository.latest_run_id` selected the newest scan_run
  via a hand-maintained `notes` denylist; the skew engine's `skew_swing_greeks`
  side-channel runs were not on it and — having higher run_ids and no aggregates
  — shadowed the real `full_scan`, blanking every ticker's detail page after
  ~17:30 ET each day. The selector (and the `get_scan_duration_summary` health
  metric) now key on the property the report actually needs —
  `status='ok' AND aggregates IS NOT NULL` — so no future side-channel job can
  re-break it. No data was lost; the fix is read-path only.
## [0.1.1] — 2026-06-17


### Added

- Health sidebar now shows deployed backend version in the collapsed header,
  sourced from the running process via the existing `/api/health` poll.
## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
