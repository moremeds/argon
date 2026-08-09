# Magnet view — Phase 1 research verdict

**Date run:** 2026-08-09 (supersedes the 2026-08-09 first pass — see "Correction")
**Spec:** `docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md`
**Plan:** `docs/superpowers/plans/2026-08-08-magnet-view-phase1-research.md`
**Git SHA at run time:** `a8dd3d53799ae01e66eb458232aadd339210e1c2`
**Source DB:** `100.66.147.98/option_wizard` (mini prodlike, **read-only**)
**Sweep DB:** `option_wizard_local` (writes kept off the mini per the three-tier isolation policy)

## Headline

**The cone ships. The 0.618 target does not.**

- **G1 FAIL — confirmed.** The 0.618 measured move carries no measurable edge.
  Cleaning the data moved every edge estimate by less than 0.003. This is a real
  null result and it survived the correction below.
- **G2 PASS at 5d**, FAIL at 10d/21d — and the 10d/21d failures are a defect in
  how the gate fits its scale factor, not a property of the cone.
- **G3 — a per-ticker `k` table is now justified** at all three horizons, the
  opposite of the first pass.

## Correction — the first pass was wrong about G2 and G3

The first pass reported all three gates FAIL and concluded that "no
one-parameter scale factor can repair a distributional shape mismatch," so no
cone should ship at any horizon. **That conclusion was an artifact of 87 corrupt
observations out of 47,121 (0.18%).**

Two independent data defects, both now guarded:

**1. Unadjusted corporate actions in `daily_ohlc`.** The table is not reliably
back-adjusted (the livewire `adj_close` problem). Three events leaked through:

| Ticker | Date | Ratio | What it is |
| ------ | ---- | ----- | ---------- |
| CRWD | 2026-04-14 | 0.2477 | 4:1 split, `402.24 -> 99.6225` |
| KORU | 2026-04-27 | 0.0523 | 20:1 split |
| SPCX | 2026-06-12 | 7.32x | not a split — see below |

**2. Positional `i + h` indexing across calendar gaps.** `observations()` took
row `i+h` as "h trading days later." SPCX broke that assumption: the ticker
belonged to a SPAC ETF trading near $21.9 (5 sparse sessions, options back to
2025-12), was reused, and relisted 2026-06-12 at $150 on 522M shares. Row `i`
was 2026-03-30 and row `i+5` landed in **June**, so a +113% relisting gap was
scaled by `sigma*sqrt(5/252)`, giving `z = 53.9`. That single observation
contributed roughly 16% of the pooled variance the gate then fit `k` on.

Measured across all 151 grid tickers, the gap defect fires on SPCX alone
(15 observations) — narrow today, but it is the next ticker reuse's bug too.

### What those 87 rows did to the statistics

| Statistic (5d) | First pass | Corrected |
| -------------- | ---------- | --------- |
| `std(z)` | 1.1157 | **0.9748** |
| `MAD(z)` | 0.9129 | **0.9126** |
| excess kurtosis | 361.0 | **0.85** |
| skew | +5.32 | **+0.00** |

`std` is quadratic, so one `z = 53.9` moves it on its own; `MAD` is rank-based
and barely shifted (0.9129 -> 0.9126). **`std` and `MAD` disagreeing in
direction was never evidence of fat tails — it is the textbook signature of a
handful of corrupt points.** The first pass read it as a distributional property
and concluded the lognormal family was unusable. It is not: cleaned, `z` is very
nearly normal with a scale a few percent below 1.

Guards added: `find_price_discontinuities` / `trim_to_clean_segment` in
`reports/magnet_data.py` (threshold `ln(2)`, read off a measured 2.6x gap between
the largest real move at 0.5428 and the smallest split at 1.3957), plus a
calendar-span check in the E1 runner.

## Reproduce

    uv run python scripts/research/magnet_cone_calibration.py \
        --host 100.66.147.98 --dbname option_wizard --user argon_app \
        --out docs/research/2026-08-08-magnet-cone-calibration

    uv run python scripts/research/magnet_first_passage.py \
        --host 100.66.147.98 --dbname option_wizard --user argon_app \
        --sweep-dsn "dbname=option_wizard_local" \
        --out docs/research/2026-08-08-magnet-cone-calibration

Password comes from `UW_SCAN_DB_PASSWORD` in the environment or the repo dotenv —
never a CLI argument.

## Sample

Surface window 2025-12-26 -> 2026-07-31. **47,034 observations, 119 tickers**
after dropping 72 split-spanning and 15 calendar-gap windows.

| Horizon | Observations | Included (>=100 obs) |
| ------- | ------------ | -------------------- |
| 5d      | 16,141       | 105                  |
| 10d     | 16,043       | 111                  |
| 21d     | 14,850       | 111                  |

21d now runs. Its CIs are the widest (mean band CI width 7.9pt vs 4.5pt at 5d)
and should be read as such, but withholding it entirely was over-cautious.

## E1 — cone calibration

| Horizon | cov@1σ (nom 68.27%) | cov@1.96σ (nom 95.00%) | std(z) | MAD(z) | mean(z) | k 95% CI (panel) | PIT KS p | n indep |
| ------- | ------------------- | ---------------------- | ------ | ------ | ------- | ---------------- | -------- | ------- |
| 5d  | 70.91% | 95.09% | 0.9748 | 0.9126 | +0.135 | [0.9077, 1.0260] | 7.79e-14 | 3,229 |
| 10d | 71.18% | 94.66% | 0.9834 | 0.9247 | +0.158 | [0.9018, 1.0555] | 9.44e-06 | 1,605 |
| 21d | 67.70% | 93.31% | 1.0439 | 0.9973 | +0.214 | [0.9279, 1.1097] | 3.27e-06 | 708 |

`std` and `MAD` now agree in direction at every horizon. The 1.96σ band is close
to exact at 5d and 10d (+0.09pt, −0.34pt).

### Measured confidence per band — the table the UI labels from

Full curve in `confidence_curve.csv`. CI is a panel block bootstrap (resample
blocks of dates, keep every ticker on a sampled date).

| Band | Nominal | 5d measured | 5d 95% CI | 10d measured | 21d measured |
| ---- | ------- | ----------- | --------- | ------------ | ------------ |
| 0.50σ | 38.29% | 41.69% | [38.34, 45.26] | 41.55% | 38.35% |
| 1.00σ | 68.27% | 70.91% | [67.75, 75.51] | 71.18% | 67.70% |
| 1.28σ | 79.95% | 81.96% | [79.17, 85.26] | 81.40% | 78.79% |
| 1.50σ | 86.64% | 87.81% | [85.36, 90.38] | 87.46% | 85.08% |
| 1.65σ | 90.00% | 90.87% | [88.93, 92.90] | 90.34% | 88.40% |
| 1.96σ | 95.00% | 95.09% | [93.89, 96.33] | 94.66% | 93.31% |
| 2.50σ | 98.76% | 98.30% | [97.82, 98.77] | 98.09% | 97.30% |

**At every band a view would actually draw, nominal lognormal coverage falls
inside the measured 95% CI**: 7/8 bands at 5d, 8/8 at 10d, 7/8 at 21d. The only
two rejections are 0.50σ at 5d and 2.50σ at 21d, neither of which is a drawn
band. Errors run conservative (band too wide) at 5d and 10d, and slightly narrow
at 21d (−1.7pt at 1.96σ).

State this as a non-rejection, not as proof: the CIs are 4.5–7.9pt wide, so a few
points of miscalibration cannot be ruled out either.

Inverse direction — the multiplier that delivers a target confidence:

| Target | Lognormal | 5d empirical | 10d empirical | 21d empirical |
| ------ | --------- | ------------ | ------------- | ------------- |
| 50%    | 0.674 | 0.618 | 0.620 | 0.678 |
| 68.27% | 1.000 | 0.945 | 0.936 | 1.011 |
| 80%    | 1.282 | 1.222 | 1.234 | 1.315 |
| 90%    | 1.645 | 1.600 | 1.629 | 1.732 |
| 95%    | 1.960 | 1.947 | 2.005 | 2.139 |
| 99%    | 2.576 | 2.768 | 2.780 | 3.005 |

The 99% row is the one real departure: the far tail needs ~8% more width than
lognormal at 5d/10d and ~17% at 21d. Do not draw a 99% band from the closed form.

### G2 — OOS scale calibration

| Horizon | k_train | n test | cov@1σ raw → calibrated | G2 |
| ------- | ------- | ------ | ----------------------- | -- |
| 5d  | 0.9747 | 6,456 | 0.7000 → 0.6873 | **PASS** |
| 10d | 1.0303 | 6,417 | 0.7518 → 0.7641 | FAIL |
| 21d | 1.1066 | 5,940 | 0.7263 → 0.7694 | FAIL |

At 5d the fit now moves coverage the right way and lands 0.5pt from nominal.

The 10d/21d failures are the **gate's** defect, not the cone's. It fits scale by
`std`, which positive excess kurtosis pushes above 1; dividing `z` by `k > 1`
shrinks `z` and *raises* coverage — but coverage was already above nominal, so
the correction can only ever move away from the target. A gate that fits `std`
cannot fix an over-coverage failure. Fitting by `MAD`, or fitting the quantile
directly against the target coverage, is the correct estimator. **Not re-run
here: changing the estimator after seeing the outcome is exactly the move that
invalidates a gate.** It goes in the next plan, pre-registered.

Note the PIT KS test still rejects at all horizons. With 3,229 independent
observations it has enough power to detect the +0.135 mean shift alone — which is
the equity risk premium, since the cone is drawn risk-neutral with zero drift.
The KS statistic is 0.069, so the effect is real but small, and the band-level
CIs above are the decision-relevant measurement.

### G3 — per-ticker dispersion

| Horizon | per-ticker k std | pooled CI width | pooled k | table justified |
| ------- | ---------------- | --------------- | -------- | --------------- |
| 5d  | 0.1349 | 0.1183 | 0.9748 | **yes** |
| 10d | 0.1637 | 0.1536 | 0.9834 | **yes** |
| 21d | 0.2235 | 0.1818 | 1.0439 | **yes** |

Reversed from the first pass, because cleaning collapsed the pooled CI width
(0.4441 -> 0.1183 at 5d) far more than it moved per-ticker dispersion. The
margins are thin (0.135 vs 0.118), and the gate only asks whether dispersion
exceeds pooled uncertainty — **it does not establish that a per-ticker `k` beats
a pooled `k` out of sample.** That is a different test and it has not been run.
Ship the pooled constant; treat the per-ticker table as an open question.

## E2 — 0.618 first passage

111 tickers with >=200 bars after trimming at corporate actions (CRWD −195 bars,
KORU −204, SPCX −5; all three then fall below the 200-bar floor and drop out).
Entries at `confirmed_index + 1`. CI is a **ticker-clustered** bootstrap at
α = 0.05/5 = **0.01** (Bonferroni over the sweep).

| k_atr | legs | hit   | null  | edge    | OOS edge | **OOS CI [lo, hi]**   | clusters | G1 |
| ----- | ---- | ----- | ----- | ------- | -------- | --------------------- | -------- | -- |
| 2.0 | 938 | 0.483 | 0.506 | −0.0233 | −0.0429 | [−0.1019, **+0.0210**] | 111 | **FAIL** |
| 2.5 | 656 | 0.485 | 0.491 | −0.0059 | −0.0231 | [−0.0905, **+0.0400**] | 108 | **FAIL** |
| 3.0 | 423 | 0.470 | 0.468 | +0.0026 | −0.0162 | [−0.0978, **+0.0605**] | 100 | **FAIL** |
| 3.5 | 304 | 0.457 | 0.446 | +0.0113 | −0.0058 | [−0.1034, **+0.0940**] |  85 | **FAIL** |
| 4.0 | 226 | 0.438 | 0.413 | +0.0248 | +0.0220 | [−0.0823, **+0.1392**] |  72 | **FAIL** |

Every OOS interval spans zero. Null hit rates (0.413–0.506) track observed hit
rates (0.438–0.485) almost exactly: **the geometry carries no information about
which barrier is touched first.**

**The cleaning did not rescue G1.** Every edge estimate moved by less than 0.003
versus the contaminated run. Unlike G2/G3, this null is robust.

The gate guard still earns itself: under the plan's original "does some `k_atr`
show `oos_edge > 0`" test, `k_atr = 4.0` (+0.0220) would have PASSED and shipped
STRETCH/DOWN as validated targets.

`ambiguous` is 0.000 everywhere — the barriers are far enough apart that no
single bar spanned both.

## Chosen production parameters

- **Cone:** ships at **5d and 10d** uncalibrated (`k = 1.0`). The measured error
  at the drawn bands is +2.6pt / +2.9pt at 1σ and +0.09pt / −0.34pt at 1.96σ,
  all inside the CI, and the 5d/10d sign is conservative. Shipping `k = 1.0`
  rather than the fitted 0.9748 keeps the drawn band a pure restatement of the
  option market's own price, with the measured error disclosed.
- **21d:** every 21d error is in the narrow direction, so this called for drawing
  at the empirical multiplier (1.011σ / 2.139σ) rather than 1.0/1.96.
  **Superseded at build time** (`cards/magnets.py:CONE_BANDS`, rationale in
  place): 21d draws 1.0/1.96 like the other two horizons and closes the gap in
  the *label* instead — the band is annotated with the 93.31% it actually held,
  never 95%. Same protection against under-reading risk, and all three horizons
  stay a pure restatement of the option price with no per-horizon fitted
  adjustment. Recorded rather than quietly changed.
- **99% band:** do not draw from the closed form at any horizon.
- `k_atr` = **n/a — G1 failed.** `k_atr = 3.0` stays the drawing default only
  because it is the existing `last_pivot_index` default.

## What Plan B ships

1. **The cone ships** at 5d/10d/21d, labelled as the options-implied
   (risk-neutral) range, with the measured coverage in the tooltip — e.g.
   "realised moves landed inside the 1σ band 70.9% of the time vs 68.3%
   advertised (5d, n=16,141)". That disclosure is more than the reference chart
   gives.
2. **The fan ships**, with the same geometry and style. Endpoints move from the
   0.618 measured-move targets to the cone's own quantiles — near-identical
   visually, and market data rather than a failed prediction.
3. **STRETCH/DOWN render as unlabelled geometry** with "0.618 extension (no
   measured edge)" role text. No target sentence, no distance-% headline. The
   "+30.7%" framing is dropped.
4. Visual fidelity (spec §5.1) holds throughout.

## What this does NOT establish

- **That a per-ticker `k` beats a pooled `k`.** G3 shows dispersion exceeds
  pooled uncertainty; it does not show the table predicts better OOS.
- **That the corrected G2 estimator passes.** Fitting by `MAD` or by direct
  quantile targeting is the right fix, deliberately left un-run so it can be
  pre-registered rather than chosen after seeing 10d/21d fail.
- **Whether 0.618 specifically is the problem.** 0.5, 1.0 and 1.618 are untested.
- **Earnings conditioning.** ATM IV widens into a print and the cone widened with
  it; no earnings flag was used as a covariate.
- **Regime stability.** One window, 2025-12-26 -> 2026-07-31, one vol regime.
- **That `daily_ohlc` is now clean.** Two defect classes were found and guarded.
  A third would look exactly like these did before they were found — the guards
  cap known failure modes, they do not certify the table. The livewire
  `adj_close` fix remains the real remedy.
