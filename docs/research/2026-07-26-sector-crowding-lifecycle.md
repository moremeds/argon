# Sector crowding: is there an entry sweet spot or a climax warning?

**Date:** 2026-07-26 · **Sample:** 2021-06-22 → 2026-07-24, 15 sector ETFs,
16,706 sector-days · **Verdict: NO. Do not build thresholds on this.**

**Reproduce:**

```bash
uv run python scripts/research/sector_crowding_lifecycle.py
```

Writes the full panel to `docs/research/2026-07-26-sector-crowding-lifecycle.json`.

## Question

The panel reduces three legs to one label via a min-band rule (`STATE` =
weakest present leg's band, `binding_leg` names it). That rule is a modelling
choice copied from the source framework's conjunctive claim — it was never
measured. The ask: find empirically where a sector is *entering* crowding
(forward returns still positive) and where it *climaxes* (forward returns turn
negative), and replace the arbitrary rule with calibrated thresholds.

Only the price leg has a testable sample, so it is tested alone first. See
"Not tested" for why the other two were not.

## Result 1 — percentile level does not separate anything

Forward return is SPY-relative, in percentage points. `t` is computed on
non-overlapping windows (every h-th bar per ticker).

```
bucket        n     fwd5  hit   t    fwd10  hit   t    fwd21  hit   t    fwd42  hit   t
pct 0-10   2438    +0.15   51  1.6   +0.34   54  1.1   +0.58   55  1.3   +0.69   50  0.5
pct 10-25  2446    -0.03   49 -0.3   -0.03   49  0.3   -0.09   46 -0.2   +0.03   46 -0.9
pct 25-50  3693    -0.16   46 -2.0   -0.25   45 -1.4   -0.27   44  0.1   -0.31   44  1.1
pct 50-75  3686    +0.11   52  0.3   +0.19   51  0.8   +0.23   50  0.0   +0.43   48 -0.1
pct 75-90  2235    +0.17   53  1.6   +0.25   53  1.1   +0.46   51  1.8   +0.43   49  0.0
pct 90-95   817    -0.02   48  1.3   -0.11   47  0.4   -0.04   44 -0.3   -0.29   45 -2.2
pct 95-100 1391    -0.08   48 -0.5   -0.19   46 -0.8   -0.25   45 -0.9   +0.11   49  1.6
```

Every effect is inside ±0.7% and hit rates sit in a 44–55% band. The shape is
non-monotonic (bottom decile mildly positive, 25–50 negative, 50–90 positive,
90+ negative), which is not what a crowding lifecycle predicts and is what
noise looks like. Roughly 84 cells were examined; two cleared |t|=2, which is
the number chance supplies.

## Result 2 — the momentum overlay looks like a story, then dies

Splitting the top decile by recent 10-day relative momentum produces a
coherent-looking picture: still-accelerating is fine (`fwd42 +0.83`),
rolling-over is bad (`fwd42 -1.80`). Split the sample in half and the sign
flips:

```
                              full            2021-23          2024-26
ENTRY   50<=p<90 mom>+2    +0.99 (t+0.6)   -0.01 (t+0.2)    +1.68 (t+0.5)
DIP-BUY 50<=p<90 mom<-2    +0.39 (t+2.3)   +1.10 (t+2.0)    -0.12 (t+1.6)
OK      p>=90    mom>+2    +0.28 (t-0.8)   -0.01 (t-2.2)    +0.57 (t+0.0)
CLIMAX  p>=90    mom<=0    -0.52 (t+0.4)   +1.16 (t+2.3)    -1.94 (t-1.8)
```

`CLIMAX` is the clearest failure: **+1.16 with a 63% hit rate in 2021–23 and
−1.94 with a 29% hit rate in 2024–26.** The full-sample −0.52 is the average of
a buy signal and a sell signal. Nothing here is stable.

Ticker concentration finishes it. The `ENTRY` bucket's positive mean is the
semis complex in the AI run — `SMH +3.97`, `SOXX +2.16`, `MAGS +2.87`,
`XLK +1.41`, against `XLU −0.76`, `XLY −1.03`, `XLV −0.74`, `XLC −0.60`.
"Extended and accelerating works" is "semiconductors went up 2024–26."

## Not tested: flow and premium legs

Underpowered by construction, so running them would only manufacture noise.
Forward 21-day SPY-relative return has SD 4.91%, so the detectable effect at
|t|=2 is:

| leg | usable history | non-overlapping n | detectable @ fwd21 |
|---|---|---|---|
| price | 5y (apex bars) | ~1100 | 0.30% |
| flow | ~250d (`etf_flows_daily`) | ~170 | 0.75% |
| premium | 140d (`volatility_stats_history`, from 2026-01-02) | ~85 | 1.06% |

The best-powered leg detects down to 0.30% and found nothing stable. Asking a
leg that cannot see below 1.06% to confirm is not a test.

## Data caveats

- **XLE and SMH carry apex adjustment seams** at 2021-06-11/06-18/06-21
  (~±100% single-day moves where a longer series is spliced onto the common
  one). Sample starts 2021-06-22 to exclude them. Both series also end
  **2026-07-13**, 11 sessions behind the other thirteen.
- **MAGS starts 2023-11-09** (fund inception), so it contributes ~677 of the
  16,706 sector-days and none of the 2021–23 half.
- Sector-relative returns are cross-sectionally correlated, so the effective
  independent sample is smaller than the non-overlapping count implies. The
  reported `t` values are therefore optimistic, not conservative.

## What this means for the panel

The crowding panel is a **descriptive** surface, not a timing one. It says what
the legs currently read; it does not carry evidence that any configuration
predicts forward returns. Consistent with two prior findings in this repo:
VCG forward-returns (descriptive, not predictive) and GEX regime-persistence
(weak and confounded, not built).

Two consequences:

1. **Do not calibrate thresholds to this data.** Any "sweet spot" fit here is
   the 2024–26 semis run.
2. **The `binding_leg` critique stands on its own and is separable.** The
   min-band reduction hides the three leg values behind one label, and the
   empirical work gives no reason to prefer min over any other aggregator —
   but it gives no reason to prefer a *fitted* aggregator either. The honest
   fix is a display change (show all legs and which are absent), not a new
   rule dressed up as calibrated.

Revisit when the flow leg has ≥3 years — and note the flow leg's own
dependency is unreliable: UW's `in-outflow` endpoint dropped SOXX, IGV and IAU
on 2026-05-15 and only restored SOXX/IGV on 2026-07-01.
