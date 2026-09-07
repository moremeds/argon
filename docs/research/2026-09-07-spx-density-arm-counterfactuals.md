# SPX density cone — innovation-family arm counterfactuals (runs 4–7)

**Verdict (2026-09-07): line CLOSED. `ARM` stays `G`.** No innovation-family arm can move
the cone's tails, because the cone never samples the fitted distribution. Further work on
the left tail must change the cone's *sampling* or the *variance dynamics*, not the
likelihood family. The desk decided not to fund that next step.

Process: every run below was a helium improvement-loop commitment, minted write-ahead
(thresholds fixed before any number existed) and settled from the persisted
`backtest_sweep_runs` row. Argon PRs #421 (runs 4–6) and #423 (run 7, stacked).

## Method

`scripts/research/spx_density_arm_h.py` replays every published `spx_density_forecast`
as_of (64 reconstructed 2026-05-05..08-14, 19 prospective 07-31..09-04; 82 anchors have a
settled h=1 cell) through `density.forecast.compute_forecast(bars, as_of=…, arm=…,
seed_offset=…)` — the backfill script's own as_of-truncation path, so the panel rail pins
the index frame and `seed_for(i)` pins the Monte-Carlo seed. `realised_return` and the
EWMA `baseline_q*` columns are READ from the published rows, never recomputed. Metric
code is imported from `scripts/research/spx_density_calibration.py` (run 3). Each run is
one `backtest_sweep_runs` row with 17 result cells (origin × h, pooled) in run 3's shape.

Reads `spx_density_forecast`; writes `backtest_sweep_*` only. The 83-as_of set and run 3
exist only on the mini's `option_wizard` (local has 21 as_of and a different run 3).

Reproduce (each row's `reproduce_cmd` carries its exact flags):

```bash
eval "$(ssh macmini 'grep -E "^UW_SCAN_DB_(USER|PASSWORD|PORT)=" /opt/argon/.env')"
env UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
    UW_SCAN_DB_USER="$UW_SCAN_DB_USER" UW_SCAN_DB_PASSWORD="$UW_SCAN_DB_PASSWORD" \
    UW_SCAN_DB_PORT="$UW_SCAN_DB_PORT" UW_SCAN_DB_SCHEMA=uw_scan UW_SCAN_API_KEY=not-used \
  uv run --frozen python scripts/research/spx_density_arm_h.py            # run 4, arm H
  # --arm G --seed-offset 1   -> run 5 ;  --arm F -> run 6 ;  --arm SKEWT -> run 7
```

## Runs

| id | strategy | arm (`density/fit.ARMS`) |
| --- | --- | --- |
| 3 | `spx_density_calibration` | **G** — Normal innovations, multi-start, §3.4 retry ladder, carry (production) |
| 4 | `spx-density-calibration-arm-H` | H — Student-t innovations, otherwise G |
| 5 | `spx-density-calibration-arm-G-seed1` | G with every cone seed `seed_for(i)+1` — Monte-Carlo noise floor |
| 6 | `spx-density-calibration-arm-F` | F — Student-t, multi-start, **no** retry, carry 0 |
| 7 | `spx-density-calibration-arm-skewt` | SKEWT — Hansen (1994) skewed-t, otherwise G |

## Pooled results (pinball ratio = model / EWMA baseline, < 1 is better)

Reconstructed, n=320 (the decision set):

| metric | run 3 G | run 4 H | run 5 G seed+1 | run 6 F | run 7 SKEWT |
| --- | --- | --- | --- | --- | --- |
| q05 ratio | 1.0476 | 1.0790 | 1.0474 | 1.0790 | 1.0804 |
| q90 ratio | 0.9048 | 0.9038 | 0.9046 | 0.9038 | 0.9039 |
| q95 ratio | 0.8682 | 0.8611 | 0.8699 | 0.8611 | 0.8605 |
| mean pinball (model) | 0.003059 | 0.003072 | 0.003062 | 0.003072 | 0.003074 |
| PIT deciles 1+2 | 73 (33+40) | 75 (32+43) | 72 (34+38) | 75 (32+43) | 74 (32+42) |

Prospective, n=80 (the live holdout):

| metric | run 3 G | run 4 H | run 5 G seed+1 | run 6 F | run 7 SKEWT |
| --- | --- | --- | --- | --- | --- |
| q05 ratio | 0.9601 | 0.9461 | 0.9616 | 0.9461 | 0.9569 |
| q90 ratio | 0.9026 | 0.8841 | 0.9011 | 0.8841 | 0.8817 |
| q95 ratio | 0.9186 | 0.8876 | 0.9102 | 0.8876 | 0.8791 |
| mean pinball (model) | 0.002230 | 0.002204 | 0.002232 | 0.002204 | 0.002207 |
| PIT deciles 1+2 | 8 (1+7) | 9 (2+7) | 8 (2+6) | 9 (2+7) | 9 (2+7) |

Pre-registered bars and outcomes:

- Run 4 (bar: holdout q05 drop ≥ 0.03 AND mean pinball rise ≤ 0.01): drop 0.014 → **flat**.
  Reconstructed q05 worsens by 0.031, so no flip regardless.
- Run 5: |Δ q05| 0.0002 reconstructed / 0.0015 holdout → the **noise floor is ~0.002**.
  The 0.03 bar is ~20× noise; H's 0.014 gain is real (≈10× noise) but under the bar.
- Run 6: **byte-identical to run 4** in every cell. Zero labelled fallbacks in any run: the
  retry ladder and parameter carry never engaged on this window, so F ≡ H here. The
  hypothesis "H's left-tail overshoot comes from carry" is refuted; it is the t likelihood.
- Run 7 (bar: holdout q05 drop ≥ 0.01; reconstructed q05 ≤ 1.0526 for any flip): drop
  0.003, reconstructed 1.0804 → **flat**, flip ceiling breached. The skew IS identified
  (λ negative in 82/82 sessions, −0.192..−0.188, never at a bound; η 6.31..6.42), and it
  still lands on top of H within noise.

## Why every arm lands on the same numbers

`gjr_std_boot_cone` block-bootstraps innovations from the **empirical** standardized-
residual pool; it never draws from the fitted innovation distribution. The family therefore
enters the likelihood only: it can shift `omega/alpha/gamma/beta` and hence the variance
path and the resampled pool, but cannot put a t or skewed shape into a simulated path.
Runs 4, 6 and 7 are one experiment three ways, and run 5 shows their spread is noise.

## What this means for the desk

- The cone's 50/80/90% bands are well calibrated on both sets (reconstructed cov50 0.53,
  cov80 0.85, cov90 0.91 for G). The only shortfall is the q05 line, ~5% worse than the
  EWMA baseline by pinball — small, and it is the number that sizes a defined-risk short
  put spread's short leg, so it is worth knowing it runs slightly optimistic.
- Closing the line: fixing q05 would require a sampling change (parametric or filtered
  historical draws) or new variance dynamics, half a day of work for at best a few bp of
  short-leg placement. Not funded. Do not propose another innovation-family arm.
- Left in code, production-inert: `compute_forecast(arm=, seed_offset=)`, `ARMS["SKEWT"]`,
  and the replay script, so a future sampling experiment can be scored the same way.

Caveats 1–4 of `spx_density_calibration` bind: overlapping targets for h > 1 make the
Wilson/KS numbers optimistic; only origin='prospective' is a live record; PIT tails outside
the histogram clip are midpoints; every run re-scores the SAME window arm G was selected
on, so none is an out-of-sample arm-selection test.
