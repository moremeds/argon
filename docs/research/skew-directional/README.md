# Skew directional-verdict validation

Does the `/stock` **Skew** tab's directional verdict (e.g. QQQ "BEARISH — index_macro
bucket separated −5.3%/20d, survived the per-quarter catastrophic gate, VALIDATED")
carry real forward-return edge, or is it beta / momentum / an in-sample artifact?

Probe born from a live observation that the QQQ bearish skew read "followed the trend
3 of 3." Extended to individual stocks per request.

## TL;DR verdict

Of all 36 `(asset_class, deviation, drive)` buckets, **exactly one survives the full
gauntlet** (out-of-sample + beta-neutralization + momentum-neutralization):

| bucket | engine sep (univ) | beta-neutral (pool) | **momentum-neutral** | OOS (mom) | eff_n | verdict |
|---|---:|---:|---:|---:|---:|---|
| **single_name / NORMAL / CHASE** | +6.29% | +5.90% (t 2.67) | **+3.60% (t 2.20)** | **+2.66%** | 245 | ✅ real, modest |
| single_name / RICH / CHASE | +6.03% | +5.46% (t 1.27) | +2.58% (t 0.25) | +2.75% | 156 | ✗ momentum |
| single_name / CHEAP / CHASE | +1.68% | +1.43% (t 2.01) | +0.21% (t 1.39) | −0.02% | 165 | ✗ momentum |
| single_name / RICH / PANIC | −2.13% | −2.89% (t −1.98) | −0.96% (t +0.72) | −0.37% | 295 | ✗ momentum |
| single_name / CHEAP / PANIC | −1.81% | −2.07% (t −2.51) | −0.74% (t −1.66) | −1.92% | 126 | ~ residual, weak |
| **index_macro / NORMAL / PANIC** (the QQQ screenshot) | −5.31% | −0.44% (t −0.33) | −1.62% (t −0.49) | −1.32% | 17 | ✗ **beta** |
| index_macro / RICH / PANIC | −6.31% | −0.03% (t −0.28) | −3.18% (t −1.49) | −4.78% | 28 | ✗ beta |

**The single tradable core is not "skew predicts direction" — it is "skew confirms
momentum":** among single names with *equal 3-month price momentum*, a NORMAL-deviation
(skew not stretched) + CHASE-drive (price up, vol confirming) read adds ~3.6%/20d of
genuine excess, holding out-of-sample. It is a momentum-quality filter, not standalone
alpha — a direct bridge to the parked `momentum-moments` research.

## The index (QQQ) signal is worse than beta — it inverts

The screenshot's "−5.3%/20d" is a **cross-sectional-demean artifact**, and reading it as
"BEARISH → short QQQ" would have lost money:

| index_macro bucket | sep (univ demean) | **raw absolute fwd** | class baseline fwd |
|---|---:|---:|---:|
| NORMAL / PANIC | −5.31% | **+0.59%** | +1.53% |
| RICH / PANIC | −6.31% | **+1.63%** | +1.53% |

After the "bearish" reading the index **rose** (+0.6% / +1.6% over 20d). The −5.3% only
means the index rose *less than the single-name-heavy universe* it is demeaned against
(single-name baseline +5.85%). Against the correct benchmark — the other indices
(pool-demean) — separation is −0.44%, t=−0.33: **no index-specific edge.** The engine's
`forward_sep` uses a universe demean that, for an index, measures the index-vs-single-name
beta gap, not downside.

## Method

`scripts/oneshot/skew_directional_validate.py` (read-only; no writes to prod tables).

- **Data:** `skew_analytics_snapshot` (basis='eod') for the daily
  `(asset_class, deviation_class, drive_class)` classification per ticker×date, joined to
  T+20 forward returns from `realized_volatility_history.price`. 14 months banked:
  2025-05-13 → 2026-07-01, ~24.9k borrow-clean ticker-days, 103 tickers.
- **Reproduction gate:** universe-demeaned bucket means reproduce the engine's
  `skew_directional_verdicts` exactly — index_macro/NORMAL/PANIC = −0.0531, n=42 (engine
  −0.0530558, n=42); single_name/NORMAL/CHASE = +0.0629, n≈1859 (engine +0.0629, n=1863).
  The harness is faithful, so the rigor deltas below are apples-to-apples.
- **Three neutralizations** (excess forward return, common component removed per date):
  - `univ` — vs the whole-universe mean (**reproduces the engine's method**).
  - `pool` — vs same-`asset_class` mean (strips shared index/sector beta).
  - `mom` — vs same-date, same-trailing-3-month-momentum-decile mean (strips the
    **momentum factor** + beta). This is the acid test for CHASE buckets, which are
    up-momentum by construction.
- **Overlap correction:** the engine's `n` counts every daily firing; consecutive firings
  share ~95% of their 20-day forward window. `eff_n` keeps only firings ≥20 trading days
  apart *within each ticker*; `t_stat` uses that independent subsample.
- **OOS split:** IS < 2026-02-01, OOS ≥ 2026-02-01 (also per-quarter in the CSVs).

## Why the engine over-reports

1. **No walk-forward for the directional layer.** `skew_directional_verdicts` is a pure
   in-sample bucket mean gated only by a per-quarter catastrophe check. Its sibling
   `skew_rv_reversion_verdicts` *has* a 40% holdout (`survives_walkforward`); the
   directional layer just doesn't. We add IS/OOS here.
2. **`n` overstates independence.** n=42 for the QQQ bucket ≈ 17 independent 20-day
   observations after overlap correction; no dispersion/t-stat is persisted at all.
3. **Universe demean ≠ tradable direction.** For indices it measures a beta gap and even
   flips the sign of the real absolute move (see above).

## Per-ticker heterogeneity (the pooled bear bucket is not one signal)

`single_name/RICH/PANIC` (engine "−2.13% bear") is wildly cross-sectionally
heterogeneous: strongly negative in defensives/software (ISRG −15% t=−6.8, MSFT −8%,
META −10%, CRM, MSTR) but **positive in semis/high-beta** (AMD +6.5%, AVGO +3.9%,
ARM +19%, MU, TER). Pooling hides a sign flip. Full breakout:
`per_ticker_key_buckets.csv`.

## Honest caveats

- Momentum deciles are ranked across the full universe per date; single names dominate
  (~87/103) so it is ~a within-single-name control, not exactly. `[COMPUTED, MED]`
- The survivor's +3.6% is a *modest* increment on a larger momentum/beta base (raw +6.3%,
  of which ~2.3pp was momentum+beta). It confirms momentum; it does not stand alone.
- Point-in-time borrow is unavailable (engine caps confidence at 'med' for the same
  reason); the borrow-clean subset is approximate.
- Sample is ~14 months, net-up market. The one down-tilt that survived momentum control
  in-sample (RICH/PANIC index) has n≈28 independent obs — thin.

## Reproduce

```bash
export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
uv run --directory /Users/chenxi/projects/argon \
    python .worktrees/skew-directional-probe/scripts/oneshot/skew_directional_validate.py
# self-check the overlap logic:  ... skew_directional_validate.py --selfcheck
```

Full traces: `buckets_{univ,pool,mom}.csv` (all 36 buckets × every metric),
`per_ticker_key_buckets.csv`.

## Track 3 — backfill depth: CLOSED (measured, not inferred)

`scripts/oneshot/skew_backfill_probe.py`. UW `historical-risk-reversal-skew` returns a
**rolling trailing ~250 trading-day window** (2025-07-03 .. 2026-07-01 on the run date),
**identical for every expiry probed** (QQQ 2026-09-18 / 2026-12-18 / 2027-01-15, NVDA,
SPY) — it is not keyed to when the expiry was listed. Consequence:

- Deeper *time* is unavailable at any budget. The API caps at ~1 year rolling.
- The banked `risk_reversal_skew_history` already starts **2025-05-13**, *earlier* than a
  fresh pull's current floor (2025-07-03) — the always-on stack's nightly
  forward-accumulation has captured more history than UW now serves. Nothing to backfill.
- More time only accrues by continuing to bank forward (wait). The "compute" lever
  (surface grid) adds feature richness over ~6mo, not more time — see Track 2.

## Track 2 — richer features: no delta beats 25Δ; a term-slope lead (unvalidated)

`scripts/oneshot/skew_richer_features.py`. Recompute RR at 10Δ/25Δ/40Δ + an RR
term-slope (~30d vs ~75d) from `option_surface_grid_daily` for single names, over the
grid's 6mo overlap (2025-12-26 .. 2026-06-02, 9,207 ticker-days). Rank-IC vs the 20d
momentum-neutral forward return:

| feature | IC (all) | t | IC (CHASE) | t |
|---|---:|---:|---:|---:|
| RR 10Δ | +0.015 | 0.91 | −0.039 | −1.17 |
| RR 25Δ | +0.016 | 0.93 | −0.024 | −0.88 |
| RR 40Δ | +0.016 | 0.98 | −0.005 | −0.20 |
| **RR term-slope** | **+0.038** | **2.31** | +0.049 | 1.77 |

**Trustworthy conclusion:** RR *level* at every delta carries ~no forward signal
(|IC|≈0.015, t<1) — the deep tail (10Δ) is no better than 25Δ. This corroborates Track 1:
the edge is momentum-confirmation, not the skew *level*. No richer delta sharpens the
NORMAL/CHASE survivor.

**The RR term-slope lead is NOT trusted** and is logged as a lead only, for two reasons:
1. **Sanity gate failed.** Grid-interpolated 25Δ RR correlates only 0.04 with the engine's
   banked `rr_25d` (means match: 0.0159 vs 0.0160; per-day values don't). Cause diagnosed:
   the engine's `rr_25d` **rides the front/nearest expiry — often 0–1 DTE** (it equals
   `front_rr`; e.g. NVDA 2026-07-01 front-expiry = same day, rr_25d = −1.65, swinging
   −1.65→+0.67→+0.03 day-to-day). My feature used a stable ~30d tenor. The interpolation
   math is verified (self-check + mean match) — it's a tenor mismatch, not a bug — but it
   means my slope is on a different tenor than production and can't be cross-validated
   against it here.
2. Only ~108 days / one 6-month, net-up window.

**Incidental engine finding:** the DEVIATION pillar's raw `rr_25d` is computed on the
nearest expiry, which is numerically unstable near 0-DTE. A steadier ~30d-tenor RR (as
computed here) would likely make the deviation z-score cleaner — a candidate engine
improvement, independent of whether the directional verdict has edge.

Full traces: `richer_feature_ic.csv`, `richer_features_panel.csv`.

## Overall verdict

The Skew tab's directional verdict is **not a reliable forward signal as displayed.** The
index (QQQ) reading you screenshotted is beta with an inverted sign; the single-name
"bear" readings are momentum; RR level at any delta has ~no IC. The one thing that
survives every control is **single_name / NORMAL / CHASE**: a modest (+3.6%/20d,
momentum-neutral, OOS +2.7%) *momentum-confirmation* edge — long names whose up-move is
confirmed by a non-stretched skew. Two forward leads, both requiring more (out-of-sample)
data that only accrues by waiting: (a) the term-slope IC, on a validated tenor; (b) the
NORMAL/CHASE edge combined with the `momentum-moments` vol-scaler.
