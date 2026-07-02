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

## Deep-dive — skew as a momentum *filter*: concentrates, doesn't improve

`scripts/oneshot/skew_momentum_filter.py`. The one survivor beats its momentum-decile
peers by +3.6% (Track 1) — so does filtering a momentum portfolio by the skew condition
improve it? Portfolio test (single names, equal-weight, market-excess, 2025-08..2026-07):

| strategy | breadth (names/day) | mean excess @20d | hit | non-overlap Sharpe |
|---|---:|---:|---:|---:|
| MOM (top momentum quintile) | 16.5 | +8.15% | 0.83 | **5.81** |
| MOM ∩ CHASE | 7.4 | +12.38% | 0.75 | 3.87 |
| **MOM ∩ (NORMAL&CHASE)** | **4.0** | +13.50% | 0.70 | **3.25** |
| NORMAL&CHASE (any momentum) | 9.2 | +5.68% | 0.70 | 1.47 |

**The skew filter raises mean return (+8.15% → +13.5%, spread t=4.39) but lowers
risk-adjusted return (Sharpe 5.81 → 3.25) and collapses breadth to ~4 names/day.** It
concentrates the momentum book and chases return; it does not make momentum more
efficient. As a portfolio overlay it is a *worse* risk-adjusted bet than plain momentum.

**And the base momentum effect is not trustworthy.** +8.15% market-excess/20d with a
non-overlapping Sharpe of 5.81 for plain top-quintile momentum is an in-sample mirage:
the universe is *today's* watchlist (survivorship) and the sample is a single raging-bull
regime (net-up, AI/semi/crypto names). This is precisely the "Sharpe ~2.0" trap — a huge
number a saved trace later proves was regime + survivorship, not durable alpha. The
per-quarter breakout confirms fragility: MOM_NC's 2025Q3 "+32%/20d excess" rides ~4 names
(small-n). Horizon sweep (5d +0.8% → 40d +10.0%) just buys more momentum exposure-time,
Sharpe peaking ~1.4–1.5.

Traces: `momentum_filter_portfolios.csv`.

## Can it be a sentiment / trend gauge? — YES (aggregate), as a coincident thermometer

`scripts/oneshot/skew_sentiment.py`. Different question from alpha: does skew reliably
*reflect* the market's fear state and its trend? Aggregate daily over single names
(mean `rr_z_180d`; net-fear breadth = %PANIC − %CHASE), test vs SPY. 284 days, ~75
names/day.

| property | result | reading |
|---|---|---|
| **persistence** | net_fear autocorr lag1 **0.94**, lag5 0.75, lag20 0.31 (mean_rrz 0.87/0.78/0.53) | smooth, trendable — cross-sectional averaging kills the single-name 0-DTE noise |
| **coincident** | net_fear vs **trailing** 20d SPY = **−0.62** (mean_rrz −0.47) | strong, valid fear thermometer — fear high *after* the market falls |
| **leading** | net_fear vs **forward** 20d SPY = **+0.20** (mean_rrz +0.11) | not predictive; reflects, doesn't forecast (consistent with the alpha nulls) |
| **extremes** | top fear-quintile: trailing −1.9%, forward **+2.0%**; bottom: forward +0.3% | mild *contrarian* — extreme aggregate fear ≈ weak dip-buy, matches the VCG "PANIC mean-reverts" descriptive finding |

**So skew is usable as sentiment — but only in the aggregate, and only as a coincident /
contrarian gauge, never a per-ticker forecast.** The per-name `/stock` reading stays too
noisy (0-DTE `rr_25d`); the signal lives in the breadth. This is the honest home for it:
a market-level risk-on/off thermometer and regime overlay, not a directional trade.

**Untested caveat (do not overclaim):** a −0.62 coincident correlation with trailing
returns is partly mechanical (skew *is* positioning, positioning reflects recent price).
Whether aggregate skew-fear carries information *beyond VIX / the market's own return* is
not tested here — the next step before treating it as a distinct gauge. Traces:
`sentiment_leadlag.csv`, `sentiment_series.csv`.

## Overall verdict

**No tradable edge.** The Skew tab's directional verdict is not a reliable forward signal
as displayed: the index (QQQ) reading is beta with an inverted sign (rawABS positive), the
single-name "bear" readings are momentum, RR level at any delta has ~no IC. The one
statistical survivor — **single_name / NORMAL / CHASE**, +3.6%/20d momentum-neutral — is
real but, examined as a portfolio overlay, **concentrates momentum (breadth 16→4 names)
and lowers its risk-adjusted return (Sharpe 5.81→3.25) rather than improving it.** It
return-chases, it doesn't add efficiency. And the momentum base it rides is itself an
in-sample mirage (survivorship × one bull regime) — not forward-tradable.

**Conclusion: don't trade the directional verdict — but there is a real non-alpha use.**
Three durable outputs:
1. **A valid sentiment/regime gauge** (the positive result): the *aggregate* cross-sectional
   skew (net-fear breadth) is a smooth (autocorr 0.94), strongly coincident (−0.62 vs
   trailing) fear thermometer with a mild contrarian tilt at extremes. Usable as a
   market-level risk-on/off overlay — not a per-ticker forecast. Pending: incremental value
   over VIX.
2. **An engine defect** worth fixing — the DEVIATION pillar's `rr_25d` rides the noisy
   nearest (often 0-DTE) expiry; a stable ~30d tenor would clean the z-score.
3. **A research note**: skew is not orthogonal alpha to momentum in this data; filtering
   momentum by skew concentrates rather than improves it.

Two dormant *alpha* leads, both needing a *down*-regime the 14-month sample lacks (the
term-slope IC on a validated tenor; a skew×`momentum-moments` fusion) — not actionable
until the sample spans a drawdown.
