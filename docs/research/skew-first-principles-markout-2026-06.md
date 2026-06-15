# Skew First-Principles — Tier-1 Markout (2026-06)

**Date:** 2026-06-15
**Data:** `skew_analytics_snapshot` backfill 2025-06-01 → 2026-06-11 (16,791 snapshots,
~100 watchlist tickers) on `option_wizard_local`. Harness: `reports/skew_markout.py`.
**Status:** In-sample validation folded into V1. Findings govern the read engine's
allowed directional language (see spec §7).

## Method

Two hypotheses, per spec §7 step 2:

1. **Primary — RV mean-reversion.** Per `(asset_class, deviation_class)` bucket, mean
   forward ΔRR over T+20 trading days. Does extreme RR revert toward baseline?
2. **Secondary — directional, borrow-conditioned.** Per `(asset_class, deviation_class,
   drive_class, regime)` bucket, mean **cross-sectionally-demeaned** T+20 forward stock
   return on the **borrow-clean** subset (`borrow_flag != hard_to_borrow`). A bucket
   earns `TRADABLE_BULL`/`TRADABLE_BEAR` only if |mean excess| ≥ 1%, n ≥ 20, and it
   survives the per-time-window (calendar-quarter) catastrophic-degradation gate.

**Cross-sectional demeaning is load-bearing.** Raw forward returns are uniformly
positive in this up-trending backfill window (market beta) and the watchlist is
growth/high-beta heavy, so even SPY-subtraction leaves a beta>1 drift that paints
almost every bucket `TRADABLE_BULL`. Demeaning each name by the universe's same-date
mean forward return measures **separation vs peers** — the only thing that could be
skew edge rather than beta. This is consistent with Muravyev-Pearson-Pollet (2025 JFE):
after proper conditioning the residual single-name option edge is largely not
exploitable.

## Primary hypothesis — RR mean-reversion (forward ΔRR, T+20)

| Bucket | mean ΔRR | n |
|---|---:|---:|
| single_name RICH | **−0.0029** | 4,352 |
| single_name CHEAP | **+0.0514** | 1,472 |
| single_name NORMAL | +0.0010 | 7,356 |
| sector_etf RICH | −0.0049 | 164 |
| sector_etf CHEAP | +0.0329 | 62 |
| index_macro RICH | +0.0008 | 584 |
| index_macro CHEAP | +0.0012 | 98 |

**Read:** the sign is the textbook mean-reversion signature for single-names and
sector ETFs — **RICH skew drifts down, CHEAP skew drifts up** toward baseline. This
supports the tab's *relative-value* framing (the core, always-interpretive read). It is
descriptive, not a tradeable trigger on its own.

## Secondary hypothesis — directional verdicts (cross-sectional excess, borrow-clean)

Of 57 populated buckets: **32 NONE, 16 TRADABLE_BEAR, 9 TRADABLE_BULL.** Latest-day
leans across ~88 tickers: **63 NEUTRAL, 16 BULLISH_TILT, 9 BEARISH_TILT** — i.e. ~72%
of names carry **no** directional lean, which is the intended conservative posture.

Representative TRADABLE buckets (excess = demeaned T+20 forward return):

| Bucket | verdict | excess | n | conf |
|---|---|---:|---:|---|
| index_macro RICH/PANIC/HIGH_VOL | TRADABLE_BEAR | −0.0564 | 202 | high |
| single_name RICH/PANIC/LOW_VOL | TRADABLE_BEAR | −0.0453 | 228 | high |
| single_name CHEAP/PANIC/HIGH_VOL | TRADABLE_BEAR | −0.0224 | 184 | high |
| single_name NORMAL/CHASE/LOW_VOL | TRADABLE_BULL | +0.0669 | 518 | high |
| single_name RICH/CHASE/HIGH_VOL | TRADABLE_BULL | +0.0275 | 348 | high |
| single_name CHEAP/CHASE/LOW_VOL | TRADABLE_BULL | +0.0251 | 205 | high |

`confidence` reflects **sample size + separation magnitude only** — it is NOT an
out-of-sample claim. Every verdict here is in-sample over a single ~13-month window.

## Limitations (must stay loud in the UI)

- **In-sample.** No walk-forward / out-of-sample test. Xing-Zhang-Zhao and
  Cremers-Weinbaum both document decay; treat `TRADABLE_*` as a tilt, not a forecast.
- **Borrow history is shallow** (latest-per-run `uw_positioning`), so borrow-clean
  conditioning is current/cross-sectional, not fully point-in-time.
- **Earnings is not point-in-time** in backfilled rows (`earnings_gate='unknown'`); it
  only gates the *live* lean, not the historical separation (which is earnings-agnostic).
- **`drive`/`regime` buckets are coarse** (PANIC/CHASE/STRUCTURAL × HIGH/LOW_VOL).

## Governance

The deterministic read's relative-value body stays interpretive in all cases. The
**directional lean** is NEUTRAL unless a `TRADABLE_*` verdict exists for the live
bucket AND the borrow/earnings/regime gates pass — and even then it is surfaced with
its confidence + basis prominent and capped as a low/med-conviction tilt. Re-run
`run_skew_markout` after each backfill extension to refresh verdicts.
