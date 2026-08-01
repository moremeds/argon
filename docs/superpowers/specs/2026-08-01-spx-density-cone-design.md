# SPX 1–5 Day Conditional Density Cone — Market Tide Tab

**Status:** design, approved 2026-08-01
**Source research:** [moremeds/signal-lab#44](https://github.com/moremeds/signal-lab/pull/44) — `2026-08-01-spx-density-v13` (`PASS`) + `2026-08-01-spx-fan-forward`
**Surface:** `/regime` → Market Tide sub-tab

---

## 1. What this ships, and what it is not

A **display-only fan chart**: the calibrated 1–5 trading-day conditional density of cumulative
SPX return, redrawn daily, plus a strip of the five previously-issued cones with their realised
outcomes overlaid.

The v13 verdict's authorisation ceiling carries over verbatim and is **not** widened by this work:

> ✅ An experimental, clearly-labelled display-only fan chart.
> ✅ Prospective shadow logging — forecasts recorded forward-in-time and scored later.
> ❌ Not position sizing, not an order, not a risk limit, not a trading signal of any kind.

Three consequences that constrain the UI, not just the docs:

1. **`PASS` is not `PROMOTE`.** Both signal-lab exporters refuse this run mechanically. Nothing
   downstream of this panel may consume the cone as an input to a trade decision.
2. **The median is not a direction call.** The sibling directional study
   (`2026-07-25-spx-direction-multifamily`) was KILLED at AUC 0.472–0.516. The p50 must not be
   rendered as a forecast line.
3. **It is not "tighter than EWMA".** The aggregate width ratio (0.914–0.946) is a ratio of means
   driven by the high-volatility tail; the mean of per-day ratios is 0.967–0.984 and on ~43% of
   days the candidate band is *wider*. The one committed forward run (2026-07-30) was **1.085×
   wider** than EWMA at H=1.

The strip is the second half of the authorisation. v13 §3 caveat (f) records that prospective
shadow logging **does not exist yet** — building it here is the point, not decoration.

## 2. The model

Inherited whole from v13, arm `G` / family `normal`. Nothing about it is chosen by argon.

| Component | Value |
|---|---|
| Conditional scale | GJR-GARCH(1,1,1), `ZeroMean`, fitted on `100·log1p(r)` |
| Fitter | `arch.univariate.ZeroMean + GARCH(p=1,o=1,q=1) + Normal()` |
| Start grid | `MULTI_STARTS` — arch default, then 4 fixed vectors; all evaluated, argmax over admissible, ties to lowest grid index |
| Innovations | empirical standardised-residual **contiguous block** bootstrap |
| Paths | `M_PATHS = 10000` |
| Burn-in / min pool | `OVERLAY_BURN_IN = 252` / `OVERLAY_MIN_POOL = 756` |
| Horizons | drawn 1…5; **scored by v13 only at `HORIZONS = (1,2,3,5)`** |
| Quantiles | `(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)`; `BAND_80` = the (0.10, 0.90) pair |
| Baseline | RiskMetrics EWMA λ=0.94, Gaussian, zero-drift, √H — analytic, seed-independent |
| Seed | `seed_for(i) = 20260728 + (i − 755)`, a function of the **panel index** |
| Fallback | GJR fit returns `None` → `ewma_cone`, **labelled**, never silent |

**There are no frozen coefficients.** v13 froze the estimator and the gates, not an
`(omega, alpha, gamma, beta)` vector — the params are re-estimated from the expanding window on
every run. "Using the latest parameters" is therefore automatic, not a scheduled action.

### 2.1 Refit cadence: fresh at every anchor

v13's walk-forward refits every 21 days with a carry ladder (`_v13_walk.py:88-101`); the forward
application refits fresh at each anchor (`_forward_cone.py:189`, `fitted_fresh_at_anchor: True`).
**Argon matches the forward application.** Two reasons:

- signal-lab's own convention docstring: `is_refit` is *"v5's exact refit phase. Arbitrary as
  statistics, frozen as a parity convention."* (`_shd_v6.py:464`) — the cadence is a
  reproducibility device across v5–v8, not a modelling claim.
- Measured impact is negligible. Refitting at the 2026-07-30 anchor against params 5/21/42/63
  trading days stale, holding history, seed and `M` identical:

  | Param age | persistence α+γ/2+β | 80% band H=1 | H=5 | worst Δ vs fresh |
  |---|---|---|---|---|
  | fresh | 0.96623 | 2.4022% | 5.0996% | — |
  | 5d | 0.96625 | 2.4023% | 5.0996% | 0.09 bp |
  | 21d | 0.96648 | 2.4008% | 5.0964% | 0.37 bp |
  | 42d | 0.96709 | 2.3992% | 5.0941% | 0.55 bp |
  | 63d | 0.96733 | 2.3982% | 5.0919% | 0.77 bp |

  Three months of staleness moves the band under 1 bp on a 240–510 bp band. `gjr_var_path`
  re-runs the recursion over full history at every call, so the fast-moving conditional variance
  updates daily regardless of fit vintage.

  *Reproduce:* `uv run python scripts/research/spx_density_refit_staleness.py` — the measurement
  script is a deliverable of this work (§6); it was run from a scratchpad to produce the table
  above and must be committed alongside the implementation so the numbers stay reproducible.

**Honesty rail:** the strip's hit-rate is evidence about fresh-fit-daily, which is adjacent to —
not identical with — the 21-day procedure whose PIT coverage v13 measured at 79.6–80.4%. The
panel says so.

## 3. Fidelity strategy

Exact numerical reproduction is the primary requirement. Three mechanisms, in order of strength.

### 3.1 Vendor verbatim — never reimplement

~300 lines lifted **unchanged** from five signal-lab modules into `src/uw_scan/density/`, each
carrying a header naming its origin file and the v13 artifact commit `d2a88628`.

| Origin | Symbols |
|---|---|
| `scripts/forward_paths.py` | `QUANTILES`, `Cone`, `cone_from_paths`, `GJR_MIN_OBS`, `_to_pct_log`, `gjr_var_path`, `_gjr_simulate`, `gjr_std_residuals`, `gjr_std_boot_cone`, `ewma_cone`, `_gbm_samples` |
| `research/runs/_shd_v5.py` | `HORIZONS`, `H_MAX`, `M_PATHS`, `LAM`, `_ewma_sigma_series`, `arm_a_quantiles` |
| `research/runs/_shd_v6.py` | `V5_ANCHOR=755`, `SEED_BASE=20260728`, `seed_for` |
| `research/runs/_v8_estimator.py` | `MULTI_STARTS`, `T_START_NU`, channel constants (= the 9 `CHANNEL_*` strings), `Attempt`, `_guard`, `_attempt`, `fit_v8`, `select_attempt` |
| `research/runs/_v8_arms.py` | `ArmSpec`, `ARMS["G"]`, `EWMA_LAMBDA`, `OVERLAY_BURN_IN`, `OVERLAY_MIN_POOL`, `_fit` |
| `research/runs/_shd_v8.py` | `LOGLIK_TOL=1e-6`, `MAX_FAILURE_CARRY_DAYS=10` |
| `research/runs/_v6_certification.py` | `BAND_80` |

`fit_gjr` (`scripts/forward_paths.py`) is vendored but dead on arm G (`ArmSpec.legacy=False`) —
kept only so `_fit` stays verbatim.

Deliberately **not** ported: the `recovery_ladder` / carry / status machinery from `_shd_v8`
(§2.1 — unused by the forward path), and every scoring primitive that needs a realised forward
return (`pinball`, PIT, non-inferiority). Those belong to the study, not the drawing.

### 3.2 Pin `arch==8.0.0` exactly

Not `>=`. The GJR MLE runs through scipy's optimizer and is the only genuinely fragile link.
Argon already matches signal-lab at **scipy 1.18.0**.

Everything else was measured insensitive. Running the committed forward cone under both stacks:

| | signal-lab | argon | cone delta |
|---|---|---|---|
| numpy | 2.5.1 | 2.4.4 | |
| pandas | 3.0.3 | 3.0.2 | **max abs `cum_return_q` delta = 0.0** |
| python | 3.13 | 3.12 | **max abs param delta = 0.0** |

Bit-identical. `default_rng(seed).integers` (PCG64) and the MLE both held across the drift.

### 3.3 Panel-index alignment — the silent-drift trap

`seed_for(i)` is a function of the **panel index**, and the panel begins **2009-09-18** (4237
rows, ending 2026-07-24). Argon's `vol_index_daily` SPX history begins **1975** (12,960 rows).

Feeding argon's own series would make index `i` mean something entirely different → different
seed → different bootstrap draws → **the same model emitting different numbers, silently, with no
error and a perfectly plausible-looking cone.**

Two rails, both already present in `_forward_cone.py`:

1. **Anchor the return series at 2009-09-18** so index arithmetic lands in the panel's frame.
   The runner's convention (`ret[1:]`, `i = len(r)-1`) is pinned empirically by the golden test
   rather than re-derived.
2. **Zero-tolerance agreement check.** Every close overlapping the frozen panel must differ by
   **exactly 0**, or the job refuses to publish. This also covers the `vol_index_daily.close
   NUMERIC(14,4)` round-trip: SPX closes carry ≤2 decimals so the conversion is lossless today,
   and if that ever stops being true the check fires instead of the cone quietly shifting.

### 3.4 The gate: a zero-tolerance golden parity test in CI

Behavioural, not textual — it tests what the code *does*, so an edit to a vendored line fails
even if it looks harmless.

The fixture is reproducible **offline, with no lake and no network**: the committed
`forecast.json` records its four post-panel bars verbatim under
`provenance.fresh_bars_appended`, so `panel.parquet` (212 KB, shipped as package data at
`src/uw_scan/density/data/panel.parquet` — the runtime agreement rail needs it too; tests
read the same file) plus those four rows reconstruct the exact 4,240-return input.

Assertions, all `== 0.0`, never a tolerance:

- `sha256(panel.parquet) == "bd95c2ab96610b49…"`
- fitted params equal `forecast.json`'s `model.params`
- `cum_return_q` equals `forecast.json`'s, every horizon × every quantile

Three fixtures so all branches are covered: the GJR path, the EWMA fallback path (params forced
`None`), and a short-history degraded case (`pool < min_pool + H`).

*This test failing means the cone on the screen is not the validated model. It is a hard CI gate,
never skipped, never given a tolerance.*

## 4. Data flow

```
vol_index_daily (SPX, nightly vol_index_lake_sync)
  └─ series anchored at 2009-09-18 ──┐
                                     ├─ agreement check vs vendored panel (delta == 0) ─→ refuse on mismatch
  vendored panel.parquet ────────────┘
        │
        ├─ _fit(ARMS["G"], hist)           → params | None
        ├─ gjr_std_boot_cone(...)          → Cone   | None → ewma_cone (labelled fallback)
        ├─ _ewma_sigma_series → arm_a_quantiles → baseline band
        ▼
  spx_density_forecast  (as_of, h)
        │
        ├─ GET /api/regime/spx-density         → cone panel
        └─ GET /api/regime/spx-density/issued  → 5-up strip + realised outcomes
```

## 5. Schema — migration `111_spx_density_forecast.sql`

Keyed `(as_of, h)`. One row per issued forecast per horizon.

| Column | Notes |
|---|---|
| `as_of DATE` | the anchor trade date |
| `h SMALLINT` | 1…5 |
| `target_date DATE` | forward weekday from the anchor — weekday-advance estimate at issue; the settle pass corrects it to the actual H-th trading day (the model's horizon is trading days: bootstrap steps, matching v13's own panel-index scoring) |
| `scored_horizon BOOL` | `h IN (1,2,3,5)` — v13 only scored these |
| `q05 … q95 NUMERIC` | 7 cumulative simple-return quantiles |
| `baseline_q05 … q95 NUMERIC` | the EWMA arm-A band |
| `band80_width` / `baseline_band80_width` / `width_ratio` | derived, stored for the readout |
| `anchor_close NUMERIC` | price rendering is `anchor_close × (1 + q)` |
| `params_jsonb` | `omega, alpha, gamma, beta`, plus persistence |
| `fallback_used BOOL` | GJR failed → EWMA cone |
| `origin TEXT` | `prospective` \| `reconstructed` |
| `provenance_jsonb` | panel sha256, series index, seed, overlap days checked, max close disagreement |
| `realised_return NUMERIC` | filled once `target_date` closes; NULL until then |
| `inside_band80 BOOL` | derived on fill |

`origin` is load-bearing. Backfilled rows predate ship and are **in-sample to the design
process** (v13 caveat (f)) — they are `reconstructed`, badged differently, and tallied
separately from `prospective` rows in the hit-rate readout.

### Registry enrolment (CI gates — must ride this PR)

- `reports/data_freshness.py` → `MONITORED_TABLES` entry (ticker-less, freshness-only).
- `reports/data_gap_healer.py` → `DatasetRegistryEntry`, then regenerate
  `docs/runbooks/data-gap-dataset-policy.md`; `tests/unit/reports/test_data_gap_dataset_policy.py`
  asserts the doc matches the registry.

## 6. Components

| Path | Role | Budget |
|---|---|---|
| `src/uw_scan/density/constants.py` | every frozen constant, one place | ~60 |
| `src/uw_scan/density/fit.py` | `Attempt`, `_guard`, `_attempt`, `fit_v8`, `select_attempt`, `ArmSpec`, `ARMS`, `_fit` | ~140 |
| `src/uw_scan/density/cone.py` | `Cone`, `cone_from_paths`, GJR helpers, `ewma_cone`, `arm_a_quantiles` | ~150 |
| `src/uw_scan/density/forecast.py` | orchestration: series build, agreement check, fit, cone, baseline, rows | ~120 |
| `src/uw_scan/storage/spx_density_repository.py` | own module from method one (never `repository.py`) | ~120 |
| `src/uw_scan/worker/jobs/spx_density_forecast.py` | nightly job | ~90 |
| `src/uw_scan/models/spx_density.py` | API contract models | ~60 |
| `src/uw_scan/api/routers/regime.py` | two read-only routes | +40 |
| `web/lib/regime/useSpxDensity.ts` | hook, follows `useMarketTide` | ~50 |
| `web/components/regime/DensityConePanel.tsx` | the headline cone | ~220 |
| `web/components/regime/DensityConeStrip.tsx` | 5-up issued forecasts + realised overlay | ~160 |
| `scripts/backfill/spx_density_backfill.py` | seeds `reconstructed` history | ~80 |
| `scripts/research/spx_density_refit_staleness.py` | the §2.1 measurement, committed | ~90 |

Every module under the 500-line budget; the vendored numerics split by role rather than dumped
into one file.

## 7. Scheduling

Nightly, **after** `vol_index_lake_sync` (it needs the day's SPX close), massive-0 lane — zero UW
budget, no IB. Gated `UW_SCAN_SPX_DENSITY_ENABLED` (the `UW_SCAN_` prefix per config.py's stated convention for new gates), default **false** until the parity test and
a first manual run are both green on the mini.

Cost is ~3 s: five multi-start MLE fits on ~4,240 returns plus a 10,000-path simulation.

The job runs two passes in order. **Pass 1 (settle)** fills `realised_return` / `inside_band80`
for any existing row whose `target_date` has since closed — cheap, pure SQL plus a close lookup.
**Pass 2 (issue)** draws today's cone and writes the new `(as_of, h)` rows. Settling first means a
failure in pass 2 never blocks yesterday's outcomes from being recorded.

## 8. UI

Layout mirrors the existing tide arrangement — one large current panel, a strip of five below.

```
┌─────────────────────────── SPX 1–5D DENSITY CONE ────────────────────────────┐
│ anchor 2026-07-30 · 7437.63 · GJR arm G/normal · fitted ✓     DISPLAY ONLY    │
│                                                                              │
│  +6% ┤                                             ░░░░░░░░  ← 5–95          │
│      │                                        ░░▒▒▒▒▒▒▒▒▒▒                   │
│  +3% ┤                                   ░▒▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← 25–75          │
│      │    ╭──╮      ╭─╮              ░▒▓▓▓·─·─·─·─·─·─·─·─  ← p50 · NOT a    │
│   0% ┤───╯  ╰─╮  ╭──╯ ╰──╮  ╭───●░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓      direction    │
│      │        ╰──╯       ╰──╯   ░▒▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                        │
│  -3% ┤   realised (20 sessions)  ░░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                          │
│      │                            ░░░░░░░░░░░░░░                             │
│  -6% ┤                          ┄┄┄┄┄ EWMA λ=.94 80% band (outline)          │
│      └────────────────────────────┬────┬────┬────┬────┬─────                 │
│                              anchor H1   H2   H3   H4   H5                   │
│ 80% band: 2.40% 3.33% 4.05% 4.51% 5.10%  ·  vs EWMA 1.09× 1.06× 1.06× …      │
└──────────────────────────────────────────────────────────────────────────────┘

┌── ISSUED 7-29 ──┐┌── 7-28 ──┐┌── 7-27 ──┐┌── 7-24 ──┐┌── 7-23 ──┐
│  ░▒▓▓●▓▓▒░      ││ ░▒▓▓▒░   ││  ░▒▓▓▒░  ││ ░▒▓●▓▒░  ││ ░▒▓▓▒░   │
│    ●──●         ││   ●─●    ││    ●──●  ││  ●─●     ││   ●──●   │
│  IN 5/5    ✓    ││ IN 4/4 ✓ ││ IN 3/3 ✓ ││ OUT@H2 ✗ ││ IN 5/5 ✓ │
└─────────────────┘└──────────┘└──────────┘└──────────┘└──────────┘
   80%-band hit rate · prospective 12/15 · reconstructed 41/50 (in-sample)
```

Rendering rules:

- **Y axis is cumulative % return**, the model's native output. The tide chart's spot is SPY, the
  model is SPX, and the SPX/SPY ratio drifts with dividends — a converted axis would be a lie.
  Percent sidesteps it and makes all six charts share one scale.
- Hand-rolled SVG per `web/CLAUDE.md`; `lib/svgChart.ts` helpers; no chart library.
- Three nested bands (5–95, 10–90, 25–75) at increasing opacity; **p50 dotted and explicitly
  annotated as not a direction call**.
- EWMA baseline drawn as a thin outline, never as a filled band — it is a reference, not a
  forecast.
- H=4 is drawn but marked unscored (v13 scored 1, 2, 3, 5 only).
- `fallback_used` → the panel says `EWMA FALLBACK — GJR fit unavailable` in warning colour. It is
  never silently substituted.
- A permanent `DISPLAY ONLY · NOT A TRADING SIGNAL` chip in the header.
- Copy may never claim the band is tighter than EWMA; show the per-day ratio, which is honest and
  frequently `> 1`.

## 9. Error handling

| Condition | Behaviour |
|---|---|
| Panel/DB close disagreement ≠ 0 | **refuse to publish**, log loudly, leave yesterday's row standing |
| SPX series shorter than `GJR_MIN_OBS` (756) | no row; job reports `too_short` |
| GJR fit returns `None` | `ewma_cone` fallback, `fallback_used = true`, surfaced in the UI |
| Residual pool `< min_pool + H` | `gjr_std_boot_cone` returns `None` → same labelled fallback |
| `vol_index_lake_sync` produced no new SPX bar | skip; do not re-anchor on a stale close |
| API has no row for today | panel renders the most recent row with its `as_of`, never interpolates |

The unifying rule: every degradation is **labelled and visible**, never silent. A wrong cone that
looks right is the failure mode this whole design is built against.

## 10. Testing

| Level | Test |
|---|---|
| **Parity (the gate)** | `tests/unit/density/test_parity_golden.py` — 3 fixtures, `== 0.0` assertions, offline |
| Unit | series anchoring at 2009-09-18; agreement check rejects a 1-tick disagreement; `select_attempt` tie-breaks to lowest grid index; fallback labelling |
| Integration | repository round-trip; job writes expected `(as_of, h)` rows; realised-fill pass sets `inside_band80` correctly |
| Web unit | vitest on band-path geometry and the hit-rate tally splitting prospective vs reconstructed |
| E2E | Playwright: Market Tide tab renders the cone panel and the 5-up strip |
| Smoke | real worker path — job → DB → API → web page, per the standing rule. Never a `/tmp` script calling the function directly |

## 11. Monitoring and re-validation

**Refit** is daily and needs no monitoring. **Re-validation is trigger-based, never calendar-based** —
a scheduled quarterly review would be theatre, because the statistics cannot resolve anything at
small `n`:

| Prospective days | 95% band on an 80% hit rate (binomial — an optimistic floor) |
|---|---|
| 60 | ±10.1 pp |
| 125 (~6 mo) | ±7.0 pp |
| 250 (~1 yr) | ±5.0 pp |
| 750 (~3 yr) | ±2.9 pp |

Those are floors. Tail exceedances cluster — precisely v13's weakest component
(`G2_p_ind@0.20` at H=1, `p = 5.1e-02`, the argmin of 32 component p-values) — and consecutive
H=5 forecasts overlap by 4 days, so a calendar year yields ~50 independent observations at the
long horizon, not 250.

- **Slow gate.** Re-run v13's gates in signal-lab once the prospective log reaches ~250 days —
  roughly Aug 2027 if logging starts now. That is the honest first re-validation date.
- **Fast alarms** (no sample size required, fire in days): `fallback_used` rate > 0,
  non-convergence in the attempt set, persistence α+γ/2+β drifting toward 1.0, and
  `max_abs_close_disagreement ≠ 0`. The job computes all four anyway; surfacing them to
  `/api/health` is ~15 lines.

Fast alarms catch the failures that actually happen — a data break or a fit collapse — while the
calibration question accumulates `n` in the background.

## 12. Out of scope

- Any consumption of the cone as a trading input, sizing rule, or alert threshold. The
  authorisation forbids it.
- Any directional read. The direction study was killed; this model does not attempt it.
- Porting `recovery_ladder` / carry / status machinery (§3.1).
- Extending the model to other underlyings. v13 validated SPX on one frozen window; QQQ or RUT
  would each need their own pre-registration in signal-lab.
- Re-running v13's gates inside argon. Validation lives in signal-lab; argon draws and logs.

## 13. Open items for implementation

1. ⚠️ **Verify SPX freshness on the mini.** This MacBook's lake mirror stops at 2026-05-29 while
   signal-lab's lake had 2026-07-30. Confirm `vol_index_daily` SPX is current on the mini before
   enabling the job — a stale anchor would silently draw a cone from the wrong close.
2. Confirm the vendored `panel.parquet` (212 KB) is acceptable in-repo as a test fixture; it is
   the authenticated artifact and the digest check depends on its exact bytes.
3. Decide backfill depth for the `reconstructed` strip — 60 sessions is ~1 minute of compute and
   fills the strip plus a meaningful (if in-sample) hit-rate tally.

## 14. Delivery

One PR: vendored numerics, migration `111`, repository, job, models, routes, both web components,
the backfill and staleness scripts, both registry enrolments with the regenerated policy doc, the
parity fixtures, and the `[Unreleased]` CHANGELOG entry — all on one branch, per the standing
one-change-one-PR rule. Branch prefix `feat/`.
