# Volume-profile window choice — stability vs. edge

**Date:** 2026-07-20
**Status:** complete; conclusions acted on in the VP overlay
**Trace:** `docs/research/2026-07-20-volume-profile-window-study.json`
**Reproduce:** `npx tsx scripts/research/volume_profile_window_study.mts`

## Question

The VP overlay shipped as true VRVP — the profile recomputes from whatever bars
are on screen. Panning therefore moves the POC, the value area, the S/R zones,
and redraws the BUY/SELL marks. Which window definition best represents the
profile, and what does the instability cost?

"True" needs restating: a volume profile is a *description of a chosen window*,
so every window is faithful to itself. There is no ground truth to be near. The
answerable version is a trade-off between two measurable properties:

- **Stability** — how far do the derived levels move when the window shifts?
- **Adaptivity** — do the levels still say anything about future price?

Stability alone is maximised by an infinite window, which would be perfectly
steady and possibly worthless. Both are required.

## Method

Imports the **shipped** compute (`web/lib/volumeProfile.ts`) rather than a
re-implementation, so the numbers describe what the chart actually draws.

- **Data:** apex REST `GET /bars/{t}?timeframe=1d&limit=5000` — real daily
  OHLCV, zero null volumes. SPY, QQQ, IWM, AAPL, NVDA, MSFT; 5000 sessions each
  (2006-08-29 → 2026-07-17).
- **Profile settings:** 60 bins, 70% value area — the shipped defaults.
- **Windows tested:** W ∈ {60, 120, 250, 360, 500, 750} bars.
- **Point-in-time throughout:** levels at bar *t* use only bars ≤ *t*. Forward
  returns come from bars strictly after the touch.

Three experiments:

**A. Pan sensitivity.** At a *fixed* date, recompute with W ∈ {150…600} and
measure the spread of the resulting POC, in ATR14 units. This is the panning
complaint measured directly: scrolling changes W.

**B. Time churn.** At a *fixed* W, advance one bar and measure (i) POC movement
in ATR units, and (ii) the fraction of the trailing-250-session BUY/SELL/touch/
reject mark set that flips. The mark rule mirrors `TechnicalsPriceChart.tsx`.
Marks on the newly-arrived bar are excluded so only genuine *redraws of history*
count.

**C. Efficacy.** From point-in-time zones, find the first touch of the nearest
support/resistance within 20 sessions, then measure the 5-session forward return
from the touch close. Compared against a **placebo** level at 1.4× the same
signed distance from spot — without it this measures equity drift, not the level.

## Results

### A. Pan sensitivity — the direct answer

POC spread across a plausible scroll range (W 150→600), in ATR14:

| Ticker | median | P90 | nearest-support spread (median) |
|---|---|---|---|
| SPY | 11.44 | 31.17 | 4.87 |
| QQQ | 13.48 | 27.03 | 4.31 |
| IWM | 6.68 | 18.87 | 2.62 |
| AAPL | 13.58 | 28.02 | 4.67 |
| NVDA | 10.70 | 22.44 | 5.52 |
| MSFT | 11.84 | 23.72 | 4.46 |

**Median ≈ 11.6 ATR, tail to 31 ATR.** Scrolling relocates the POC by roughly
ten average daily ranges, every ticker, no exceptions. For SPY at ~750 with
ATR ≈ 8 that is ~90 points of POC movement purely from how far you zoomed.

This is not a subtle artifact. Visible-range is disqualified as a *reference*
tool: the level is substantially a function of the viewport.

### B. Time churn — repaint, by window

| W | POC move/bar (median) | POC move/bar (P90) | mark churn (mean) | mark churn (P90) |
|---|---|---|---|---|
| 60 | 0.000 | 0.364 | **42.4%** | 1.000 |
| 120 | 0.000 | 0.239 | **33.3%** | 1.000 |
| 250 | 0.000 | 0.208 | **24.7%** | 1.000 |
| 360 | 0.000 | 0.207 | **21.1%** | 0.999 |
| 500 | 0.000 | 0.150 | **17.9%** | 0.945 |
| 750 | 0.000 | 0.108 | **13.1%** | 0.687 |

Median POC move is exactly 0 — the POC is a bin midpoint and the argmax bin
usually survives one new bar. The action is in the tail: occasional jumps to a
different shelf.

Mark churn falls monotonically with W but **never becomes small**. At the Pine
default (360) one mark in five is redrawn *every day*, and the P90 of 0.999 says
that on the worst 10% of days essentially the entire historical mark set is
rewritten — the nearest level hopped to another shelf and every arrow moved.
Even at W=750, 13% churn daily.

Longer windows help. No window fixes this.

### C. Efficacy — no reliable edge

Edge = (real level forward return) − (placebo level forward return), 5 sessions,
basis points. Support should be positive, resistance negative.

| W | support edge (bp) | tickers positive /6 | resistance edge (bp) | tickers negative /6 |
|---|---|---|---|---|
| 60 | +6.7 | 5 | +7.5 | 2 |
| 120 | +9.0 | 4 | +4.9 | 2 |
| 250 | +14.9 | 5 | −2.6 | 3 |
| 360 | +3.6 | 3 | −3.2 | 3 |
| 500 | −7.3 | 3 | +6.5 | 2 |
| 750 | −25.5 | 1 | +3.0 | 3 |

**Resistance is a coin flip** — 2–3 of 6 tickers show the correct sign at every
window. No effect.

**Support is not robust.** Per-ticker at the best-looking W=250, raw support
returns are +44 to +188bp — but the *placebo* returns are +14 to +132bp over the
same events. Nearly all of the apparent effect is 20 years of equity drift plus
the fact that touching a level below spot means buying a dip in a bull market.

Read as a whole: **the zones carry no measured predictive information.**

> **Analyst note on how this was misread twice.** With six windows the support
> column (+6.7, +9.0, +14.9, +3.6, −7.3, −25.5) looks like a single-peaked curve
> — the shape a real effect would make if short windows are noisy and long ones
> stale. That reading was wrong. Extending to nine windows (below) gives
> +6.7, +9.0, +14.9, +3.6, −7.3, −25.5, +16.1, +29.5, −40.1, which oscillates.
> Six points were not enough to distinguish a peak from noise, and confident
> claims in *either* direction were unsupported at that sample size.

### D. Extended windows — does "longer is always better" hold?

| W | ~years | mark churn (mean) | mark churn (P90) | support edge | sup ✓/6 | resistance edge | res ✓/6 |
|---|---|---|---|---|---|---|---|
| 60 | 0.2 | 0.424 | 1.000 | +6.7 | 5 | +7.5 | 2 |
| 120 | 0.5 | 0.333 | 1.000 | +9.0 | 4 | +4.9 | 2 |
| 250 | 1.0 | 0.247 | 1.000 | +14.9 | 5 | −2.6 | 3 |
| 360 | 1.4 | 0.211 | 0.999 | +3.6 | 3 | −3.2 | 3 |
| 500 | 2.0 | 0.179 | 0.945 | −7.3 | 3 | +6.5 | 2 |
| 750 | 3.0 | 0.131 | 0.687 | −25.5 | 1 | +3.0 | 3 |
| 1000 | 4.0 | 0.086 | 0.337 | +16.1 | 3 | +20.3 | 2 |
| 1260 | 5.0 | **0.058** | **0.058** | +29.5 | 5 | +14.8 | 2 |
| 2000 | 7.9 | 0.024 | 0.000 | −40.1 | 1 | +72.0 | 0 |

Stability keeps improving all the way out, and the P90 collapse is dramatic:
the "entire mark history rewrites at once" event (P90 ≈ 1.0 at W ≤ 360) is
essentially gone by 5 years (P90 = 0.058).

The efficacy columns past W≈750 must be discarded — touch events become rare:

| touch events (sup/res) | 250 | 500 | 1000 | 1260 | 2000 |
|---|---|---|---|---|---|
| SPY | 302/230 | 206/173 | 92/77 | 44/35 | 3/4 |
| AAPL | 265/254 | 170/169 | 40/29 | 17/15 | **0/0** |
| NVDA | 234/210 | 167/146 | 72/49 | 28/47 | 3/2 |

### E. Relevance — where do long-window levels actually sit?

Distance from the latest close to the POC (%), and to the nearest support zone:

| | W=250 POC | W=1260 POC | W=250 nearest sup | W=1260 nearest sup |
|---|---|---|---|---|
| SPY | −8.9% | −43.5% | −9% | −9% |
| QQQ | −13.2% | −49.3% | −10% | −13% |
| IWM | −17.2% | −35.2% | −11% | −24% |
| AAPL | −18.7% | −56.5% | −19% | −49% |
| NVDA | −10.0% | −91.9% | −6% | −92% |
| MSFT | +1.1% | +4.2% | −5% | −7% |

**This is the mechanism behind the stability.** A 5-year profile is steady
because it is anchored to prices the market has left behind — NVDA's 5-year POC
sits 92% below spot, and its nearest 5-year "support" is a 2021 price that will
realistically never trade again. The levels stop moving because they stopped
being about the present.

A stable level that price cannot reach is not a better level. It is a worse one
that fails to advertise the fact.

## Conclusions

1. **Fixed window, not visible-range.** 11.6 ATR of POC movement from scrolling
   alone makes viewport-dependent levels unusable as a reference. This confirms
   the Pine original's default (`useFixed = true`, 360 bars), which the argon
   implementation had inverted.
2. **Longer is better for stability, but it is NOT free.** Churn falls
   monotonically all the way to 7.9 years (42% → 2%), so on stability alone the
   answer would be "use everything". Section E shows what that buys: by 5 years
   the POC sits 35–92% below spot for five of six names. Stability is purchased
   by describing a market that no longer exists. **Do not use 5 years.**
   The usable band is roughly 250–360 sessions (1–1.4 years), where levels stay
   within ~10–20% of spot and can still be reached.
3. **The BUY/SELL marks should be removed.** They redraw 21% of history per day
   at W=360, rewrite essentially all of it on the worst 10% of days, and the
   underlying levels show no edge. An arrow labelled BUY that moves tomorrow and
   predicts nothing is worse than no arrow — it implies a signal the data does
   not support. The profile, POC and value area are honest descriptive
   structure and should stay.
4. **Removing the marks dissolves the trade-off.** Churn is almost entirely a
   *mark* phenomenon — the histogram itself barely moves (median POC move per
   bar is 0.000 ATR at every window). With the arrows gone there is no longer
   any pressure to lengthen the window for stability's sake, so the choice
   collapses to relevance alone, and relevance says 250–360. The two findings
   are complementary, not competing.

## Limitations

- Daily bars only. Intraday profiles may behave differently; volume distribution
  within a daily bar is approximated as uniform across its high–low.
- Single forward horizon (5 sessions) and a single touch definition (first touch
  within 20 sessions). A different horizon could change the efficacy read,
  though the absence of cross-window coherence argues against a hidden effect.
- The placebo at 1.4× distance is imperfectly matched: it is touched less often
  and later than the real level. This biases toward *false positives*, and none
  were found for resistance — so the main risk is that the weak positive support
  numbers are placebo mismatch rather than signal.
- Six large-cap US names over one predominantly rising 20-year sample.
  Cross-sectionally correlated; the "tickers with correct sign" count is a
  robustness check, not an independent-sample p-value.
- Zone parameters (60 bins, 45% strength floor, per-side caps) held fixed. The
  study varies the window, not the zone-detection knobs.
