# Magnet view — Phase 1 research verdict

**Date run:** 2026-08-09
**Spec:** `docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md`
**Plan:** `docs/superpowers/plans/2026-08-08-magnet-view-phase1-research.md`
**Git SHA at run time:** `10927c4b6045b623e5d3adac111d8789513cb332`
**Source DB:** `100.66.147.98/option_wizard` (mini prodlike, **read-only**)
**Sweep DB:** `option_wizard_local` (writes kept off the mini per the three-tier isolation policy)

## Headline

**All three gates FAIL.** The 0.618 measured move carries no measurable edge, and
the ATM-IV cone cannot be calibrated by a single scale factor. The view still
ships — support/resistance, the magnet profile and the sub-panels stand on their
own — but **with no forecast content whatsoever**.

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

Surface window 2025-12-26 → 2026-07-31 (forward closes required, so the last
grid sessions drop out). 32,215 observations, 119 tickers.

| Horizon | Observations | Tickers | Included (≥100 obs) | Excluded |
| ------- | ------------ | ------- | ------------------- | -------- |
| 5d      | 16,147       | 119     | 105                 | 14       |
| 10d     | 16,068       | 119     | 111                 | 8        |

21d withheld — too few independent windows. Forward-only accrual; no backfill is
possible. Revisit once the surface deepens.

## E1 — cone calibration

| Horizon | cov@1σ (nom 68.27%) | cov@1.96σ (nom 95.00%) | k = std(z) | k = MAD(z) | mean(z) | k 95% CI (panel bootstrap) | PIT KS p | n indep |
| ------- | ------------------- | ---------------------- | ---------- | ---------- | ------- | -------------------------- | -------- | ------- |
| 5d      | 70.88%              | 95.06%                 | 1.1157     | 0.9129     | +0.1321 | [0.9217, 1.3657]           | 5.45e-14 | 3,230   |
| 10d     | 71.07%              | 94.51%                 | 1.2526     | 0.9268     | +0.1552 | [0.9310, 1.6743]           | 6.03e-05 | 1,607   |

OOS calibration (fit k on the front window, apply to the held-out tail):

| Horizon | k_train | n train | n test | cov@1σ raw → calibrated | cov@1.96σ raw → calibrated | G2       |
| ------- | ------- | ------- | ------ | ----------------------- | -------------------------- | -------- |
| 5d      | 1.2005  | 9,688   | 6,459  | 0.6999 → 0.7894         | 0.9599 → 0.9830            | **FAIL** |
| 10d     | 1.4373  | 9,641   | 6,427  | 0.7512 → 0.8958         | 0.9711 → 0.9947            | **FAIL** |

### Why G2 fails — a shape problem, not a scale problem

`std(z)` and `MAD(z)` disagree in *direction*: 1.116 vs 0.913 at 5d. That gap is
the finding, and the spec anticipated exactly it.

The cone is **too wide in the body and too narrow in the tails, simultaneously**.
Coverage at 1σ is 70.9% against a nominal 68.3% (over-covered — the body is
narrower than the cone, consistent with a variance risk premium, and MAD < 1
measures that directly at ≈9% shrink). But realised tails are fatter than
lognormal, which drags `std(z)` above 1.

Because the gate fit scale by `std`, `k_train > 1`, and dividing by `k > 1`
*shrinks* `z`, pushing coverage further **above** an already-too-high nominal —
0.6999 → 0.7894. It moved the wrong way.

Post-hoc diagnostic `[INFERRED, post-hoc — not a gate re-run]`: refitting with
MAD gives k = 0.8946 (5d) / 0.9643 (10d). At 10d that improves coverage
(0.7512 → 0.7339, toward 0.6827); at 5d it over-corrects (0.6996 → 0.6448). So
**MAD does not rescue G2 either.**

The PIT KS test settles it: p = 5.45e-14 at 5d on **3,230 independent**
observations. The residuals are not uniform, and no one-parameter scale factor
can repair a distributional shape mismatch. A calibrated cone would need a
different family (Student-t, or a skew-aware fit off the full smile), which is
out of scope here.

## E2 — 0.618 first passage

113 tickers with ≥200 bars. Entries at `confirmed_index + 1`. `edge_vs_null` is
paired per leg; CI is a **ticker-clustered** bootstrap at α = 0.05/5 = **0.01**
(Bonferroni over the sweep).

| k_atr | legs | median lag | hit   | stop  | ambig | neither | hit ex-amb | null hit | edge    | OOS edge | **OOS CI [lo, hi]**   | clusters | G1       |
| ----- | ---- | ---------- | ----- | ----- | ----- | ------- | ---------- | -------- | ------- | -------- | --------------------- | -------- | -------- |
| 2.0   | 955  | 5          | 0.483 | 0.388 | 0.000 | 0.129   | 0.483      | 0.505    | −0.0222 | −0.0448  | [−0.1091, **0.0149**] | 113      | **FAIL** |
| 2.5   | 669  | 6          | 0.486 | 0.347 | 0.000 | 0.167   | 0.486      | 0.491    | −0.0052 | −0.0289  | [−0.0929, **0.0326**] | 110      | **FAIL** |
| 3.0   | 433  | 8          | 0.473 | 0.316 | 0.000 | 0.210   | 0.473      | 0.471    | +0.0025 | −0.0207  | [−0.1040, **0.0608**] | 102      | **FAIL** |
| 3.5   | 309  | 10         | 0.456 | 0.291 | 0.000 | 0.252   | 0.456      | 0.445    | +0.0110 | −0.0099  | [−0.1111, **0.0906**] | 87       | **FAIL** |
| 4.0   | 231  | 11         | 0.437 | 0.294 | 0.000 | 0.268   | 0.437      | 0.414    | +0.0230 | +0.0158  | [−0.0931, **0.1275**] | 74       | **FAIL** |

Every OOS interval spans zero. Null hit rates (0.414–0.505) track observed hit
rates (0.437–0.486) almost exactly: **the geometry carries no information about
which barrier gets touched first.**

### The gate guard earned itself

Under the plan's original test — "does some `k_atr` show `oos_edge > 0`" —
**k_atr = 4.0 would have PASSED** (OOS edge +0.0158), and 3.0/3.5/4.0 all show
positive in-sample edge. The research would have shipped STRETCH/DOWN as
validated targets. Reading the clustered CI lower bound at a Bonferroni-adjusted
level rejects all five. That change was made during review, before any data was
seen.

`ambiguous` is 0.000 everywhere: the barriers are far enough apart that no single
bar spanned both. The bucket cost nothing and remains correct to keep.

## Gate rulings

- **G1 — some `k_atr`'s OOS clustered CI lower bound clears zero (≥30 decided
  legs, ≥10 clusters): FAIL.** All five intervals contain zero. Leg and cluster
  floors were met throughout, so this is a genuine null result, not
  underpowering.
  → STRETCH/DOWN ship as **unlabelled geometry**. Role text becomes
  "0.618 extension (no measured edge)". The read drops its target sentences. The
  "+30.7%" headline framing is **dropped entirely**.
- **G2 — calibrated cone reaches nominal coverage OOS: FAIL at both 5d and 10d.**
  → **No cone ships at any horizon.** The right-edge projection carries the
  volume profile only.
- **G3 — per-ticker `k` dispersion exceeds the pooled panel-bootstrap CI width:
  FAIL at both horizons.**

  | Horizon | per-ticker k std | pooled CI width | pooled k | table justified |
  | ------- | ---------------- | --------------- | -------- | --------------- |
  | 5d      | 0.2982           | 0.4441          | 1.1157   | no              |
  | 10d     | 0.3094           | 0.7433          | 1.2526   | no              |

  → A pooled constant would ship, **no table and no refit job** — moot, since G2
  already withholds the cone.

  Counterfactual check on the panel-bootstrap fix: on this data the naive
  single-series CI is only **1.3× narrower** (0.3376 vs 0.4525 at 5d), and G3
  fails under both. The fix was correct in principle but **did not change this
  verdict** — `z` is already standardised by each ticker's own IV, which removes
  much of the common volatility factor that the synthetic ρ=0.6 demo assumed.

## Chosen production parameters

- `k_atr` = **n/a — G1 failed.** Pivots still drive support/resistance for
  display; `k_atr = 3.0` is retained as the drawing default purely because it is
  the existing `last_pivot_index` default, **not** because it was selected.
- `k_shrink` = **n/a — G2 failed. No cone ships.**
- Horizons shipped: **none.**

## What Plan B must change

1. **No fan, no cone.** The right edge is the volume-profile dot cloud only.
   The three scenario paths must not be drawn to unvalidated targets.
2. **Levels are context, not forecasts.** STRETCH/DOWN render as thin dotted
   geometry with the "no measured edge" role text. No distance-% headline.
3. The visual-fidelity requirement (spec §5.1) still holds for everything else.
   Losing the forecast layer does not license redesigning the rest.

## What this does NOT establish

- **Whether 0.618 specifically is the problem.** Alternatives (0.5, 1.0, 1.618)
  were not tested. The finding is about this target, not about measured moves
  generally.
- **Whether a better-specified cone could work.** Only a one-parameter scale fit
  on a lognormal was tested. The PIT rejection points at the distributional
  family; a Student-t or smile-aware fit is untested and out of scope.
- **Earnings conditioning.** ATM IV widens into a print and the cone widened with
  it; no earnings flag was used as a covariate.
- **Regime stability.** One window, 2025-12-26 → 2026-07-31, one vol regime. A
  null result here is not proof of a null result in all regimes.
- **Longer horizons.** 21d was never run.
