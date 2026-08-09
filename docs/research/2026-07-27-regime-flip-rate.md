# Regime state flip-rate probe

Step 1 of the adaptive-smoothing evaluation. Measures whether CRI/VCG
regime states chatter enough to justify a debouncer (hysteresis/dwell)
or an adaptive smoother -- before building either.

- Whipsaw definition: a sandwiched run of <= 2 observations
  (state flips out and back to where it came from).
- Source: `uw_scan.{cri,vcg}_snapshots` on the mini (`option_wizard`).
- Reproduce: `uv run python scripts/research/regime_flip_rate_probe.py --host 100.66.147.98 --db option_wizard`

## EOD daily

| Series | Obs | Segments | Flips | Flips/mo | Whipsaws | Whipsaw share | dwell-2 | dwell-3 | dwell-4 |
|---|---|---|---|---|---|---|---|---|---|
| CRI level | 46 | 1 | 8 | 3.5 | 4 | 50% | 4 | 4 | 5 |
| VCG interpretation | 47 | 1 | 5 | 2.2 | 1 | 20% | 1 | 1 | 3 |

- **CRI level** state mix: LOW 40, ELEVATED 6
  - run lengths: 1:4, 3:1, 5:1, 6:1, 12:1, 16:1
- **VCG interpretation** state mix: NORMAL 25, SUPPRESSED 22
  - run lengths: 1:1, 3:2, 9:1, 10:1, 21:1

## Live intraday

| Series | Obs | Segments | Flips | Flips/mo | Whipsaws | Whipsaw share | dwell-2 | dwell-3 | dwell-4 |
|---|---|---|---|---|---|---|---|---|---|
| CRI level | 5299 | 31 | 26 | 17.6 | 5 | 19% | 4 | 6 | 11 |
| VCG interpretation | 6764 | 32 | 67 | 45.3 | 15 | 22% | 12 | 22 | 32 |

- **CRI level** state mix: LOW 5064, ELEVATED 235
  - run lengths: 1:4, 2:2, 3:5, 4:3, 5:1, 6:1, 7:1, 9:1, 10:1, 11:1, 12:1, 17:1, 20:2, 21:1, 33:2, 35:1, 39:1, 40:2, 51:1, 61:1, 62:1, 66:1, 69:1, 93:1, 128:1, 145:1, 152:1, 154:1, 159:1, 167:1, 184:1, 213:1, 239:1, 253:1, 254:2, 269:2, 270:2, 272:1, 277:1, 287:1, 288:1
- **VCG interpretation** state mix: NORMAL 5296, SUPPRESSED 1451, INSUFFICIENT_DATA 14, WATCH 3
  - run lengths: 1:12, 2:10, 3:10, 4:2, 5:5, 6:4, 7:3, 8:1, 9:4, 12:1, 13:1, 14:2, 16:1, 20:2, 22:1, 25:1, 33:1, 37:1, 39:1, 57:1, 58:1, 64:1, 66:1, 74:1, 75:1, 77:2, 78:1, 79:1, 93:1, 120:1, 149:1, 156:1, 164:1, 167:1, 178:1, 181:1, 183:1, 185:1, 187:1, 194:1, 211:1, 238:1, 241:1, 244:1, 251:1, 254:1, 270:2, 271:1, 272:1, 277:1, 279:1, 287:1, 288:1

## Reading this

`dwell-N` counts runs shorter than N observations -- exactly what an
N-bar confirmation filter would suppress. If whipsaw share is near zero
there is no chatter problem and both the debouncer and the adaptive-EMA
work are unwarranted.

Note `dwell-N` >= whipsaw count: it also suppresses short runs that are *not*
sandwiched (genuine brief transitions, and runs at a session boundary). The gap
between the two is the collateral damage of a dwell filter. For VCG live that
gap is 22 - 15 = 7 flips that dwell-3 would kill or delay without them being
whipsaws.

## Verdict (2026-07-27)

**Adaptive EMA is not warranted. Neither, on this evidence, is much else.**

1. **Chatter exists but is low-volume.** CRI EOD flips 3.5x/month; VCG EOD
   2.2x/month. At a 20-50% whipsaw share that is roughly *one to two* spurious
   EOD alerts per month. That is not an alert-fatigue problem.
2. **The EOD sample cannot support parameter fitting.** CRI EOD has **8 flips
   total**. Four are single-day spikes. Any dwell or alpha tuned on n=8 is
   fitted to noise -- the 50% whipsaw share has a confidence interval wide
   enough to contain both 20% and 80%.
3. **Live intraday is the only series with enough events** (CRI 26 flips / 31
   sessions, VCG 67 / 32) and its whipsaw share is the *lower* of the two at
   19-22%. So ~80% of live flips are already clean. A smoother would add lag to
   all of them to fix the other fifth.
4. **Sample is regime-biased.** The window 2026-05-15 -> 07-24 is calm: CRI sits
   LOW on 40 of 46 EOD days (87%) and ELEVATED is rare. Flip statistics measured
   in a quiet tape do not transfer to a stress tape, which is exactly when the
   alert pipeline matters. Re-measure after the next volatility event.

**Recommended action: none on smoothing.** If alert chatter later proves real in
production, apply hysteresis (two thresholds) -- not a smoother -- because it
debounces the *crossing* without distorting the value the UI displays.

### Incidental finding: `vcg_snapshots.regime` is a dead column

`regime` is `DIVERGENCE` on **all 9,526 rows** on the mini across both bases.
It carries zero information over this window. Its sibling `interpretation` is
the only varying VCG state, which is why this probe uses it. Worth a separate
look: either the scoring genuinely cannot emit another regime in a calm tape, or
the generated column is mis-wired. Not investigated here.
