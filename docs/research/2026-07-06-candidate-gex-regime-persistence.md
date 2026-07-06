# Candidate: GEX regime-persistence signal

**Date:** 2026-07-06 · **Status:** UNVALIDATED HYPOTHESIS · **Effort:** S–M
**Basis:** [INFERRED] from a data-in-hand audit. Confidence MED. **Cheapest real alpha test on the board — has statistical power today.**

## The gap (verified)

`uw_scan.gex_snapshots` is durable, append-only since migration 037, with generated scalar columns: `level_gex_flip_strike, net_gex, spot, level_call_wall_strike, level_put_wall_strike, level_max_magnet_strike, iv_30d, hv_30d, scanned_at, data_date`. Months of it exist. But `scanners/gex.py` `compute_directional_bias` returns `flip_migration: []` and days-above-flip is stubbed to `0` ("v1 — no history"). The history now exists; the time-series signal was never built.

## Hypothesis

- **(a) Regime persistence:** consecutive days of spot-vs-flip sign (short-gamma when spot < flip / net_gex < 0, else long-gamma) predicts next-day realized vol and the reversal-vs-trend character of returns. Short-gamma regimes → higher |return|, more trend; long-gamma → pinning, mean-reversion.
- **(b) Flip velocity:** the *rate* of flip-strike migration relative to spot is a leading tell for regime flips.

Pure long/short-gamma labeling from already-indexed columns. Distinct from #179 (that's the per-ticker aggregate greek endpoint; this is the index/SPX GEX snapshot series).

## Cheap validation

Label each session short- vs long-gamma from stored columns. Measure next-day |return|, RV, and mean-reversion (sign-flip rate) in each bucket. Test whether flip-migration slope precedes regime change. **All from columns already indexed with months of history** — unlike the charm/vanna candidate, this validates now, not in a month.

## Why do this one first

Same class of idea as charm/vanna (dealer-positioning → forward behavior) but with the data already banked. Run this validation before investing build time in the forward-accruing candidates — if long/short-gamma buckets don't separate forward RV here, it recalibrates confidence in the whole positioning-alpha thesis cheaply.

## Reproduce

`scripts/research/gex_regime_persistence.py` — read `gex_snapshots`, label regimes, bucket forward returns/RV, write full result set to a durable artifact under `docs/research/`.
