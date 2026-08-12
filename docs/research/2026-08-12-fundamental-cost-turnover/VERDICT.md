# VERDICT — the ranking earns nothing, and costs are not why

*2026-08-12 · hand-written · numbers in `cost_turnover.json` / `results.md` · reproduce:*

```bash
uv run python scripts/research/fundamental_cost_turnover.py
```

97 knowledge-quarter buckets · quarterly rebalance · 63-day holds · equal-weighted
· benchmarked against the equal-weighted panel.

**Gate passed first:** this panel reproduces the validated signal — 1q composite
IC **+0.0376, t +3.09** over 79 quarters, against the cross-sectional study's
+0.0404. Whatever follows is about the same signal, not a different one.

## The headline

**There is no gross alpha to erode, so transaction costs are irrelevant.** Every
slice of the ranking earns approximately zero before a single basis point is
charged:

| slice | gross quarterly alpha | t | annual turnover |
|---|---:|---:|---:|
| top 10% | **−0.0007** | −0.09 | 1.31× |
| top 20% | +0.0007 | +0.15 | 1.08× |
| top 33% | +0.0006 | +0.16 | 0.81× |
| bottom 10% | +0.0154 | +1.05 | 1.27× |
| bottom 33% | +0.0010 | +0.21 | 0.80× |
| top−bottom spread (10%) | **−0.0161** | −0.86 | — |

Every |t| ≤ 1.06. Read all of these as zero — including the bottom decile's
apparently attractive +0.0154, which is **not** a finding.

The point estimates nonetheless run *against* the ranking in the tails: the
worst-ranked decile out-earned the best-ranked one, and the long/short spread is
negative at every width. The break-even cost column in `results.md` should be
ignored entirely — a break-even computed on a zero numerator is arithmetic, not
information, and quoting "486 bps" for the bottom decile would be the single most
misleading number in this study.

## Why a t = 3.09 ordering produces a zero portfolio

This is the whole finding, and neither statistic alone can show it.

| decile | mean return | median return | mean return-rank |
|---:|---:|---:|---:|
| 0 (worst) | **+0.0601** | **+0.0145** | 0.475 |
| 1 | +0.0495 | +0.0219 | 0.485 |
| 2 | +0.0373 | +0.0241 | 0.489 |
| 3 | +0.0333 | +0.0260 | 0.489 |
| 4 | +0.0410 | +0.0312 | 0.500 |
| 5 | +0.0479 | +0.0333 | 0.513 |
| 6 | +0.0384 | +0.0330 | 0.510 |
| 7 | +0.0491 | +0.0409 | 0.526 |
| 8 | +0.0511 | +0.0365 | 0.522 |
| 9 (best) | +0.0470 | +0.0247 | 0.493 |

Three things are true at once:

1. **The IC is real.** Mean return-rank climbs 0.475 → 0.526 across deciles 0–8.
   The composite genuinely orders the *typical* name, which is exactly what a
   rank correlation measures.
2. **Median return climbs with it** — +0.0145 to +0.0409, near-monotone. The
   typical name in a well-ranked decile really does do better.
3. **Mean return does not, and the worst decile owns the highest mean.** Decile 0
   pairs the *lowest* median (+0.0145) with the *highest* mean (+0.0601). That
   gap is severe right-tail skew: badly-ranked names usually underperform and
   occasionally explode.

An equal-weighted portfolio return **is** the mean. The signal ranks medians; the
book earns means; and the skew that separates them is concentrated precisely in
the names the signal ranks worst. The IC and the P&L were never measuring the
same quantity.

This also kills the obvious salvage. "Just avoid the bottom decile" removes the
biggest winners along with the worst losers — the bottom decile is where the
right tail lives.

## The decile-9 reversal is flagged, not used

Deciles 7–8 carry the best return-rank (0.526, 0.522) and decile 9 falls back to
0.493 — the very best-ranked names underperform the merely-good ones.

**I am not recommending "buy deciles 7–8."** I looked at ten deciles and picked
the best-looking two after seeing the outcome; that is data snooping, and it is
the exact failure the rest of this repo's research apparatus exists to prevent.
The reversal is recorded as an observation needing its own pre-committed test,
with a mechanism stated in advance, or it is noise dressed as insight.

## What this settles, and what it does not

**Settles:** the ranked screen must not be presented as a strategy, sized, or
described as producing return. There is nothing to cost, nothing to size, and no
turnover budget worth arguing about. Item 2 on the work list is closed with a
clear negative.

**Does not settle:** whether the composite is *useful*. It orders median outcomes
with a real t-stat. For a research surface that answers "which of these names
look structurally better," that is a legitimate — if modest — job, and it is the
job §8's screen was scoped to. What it cannot do is pick a book.

## Where this leaves the three tests together

| test | question | answer |
|---|---|---|
| cross-sectional (08-11) | does it order names? | **yes** — IC 0.039, t 2.67 |
| time-series (08-12) | does it time one name? | **no** — powered null, IC ~0.00 |
| cost/turnover (this) | does the ordering pay? | **no** — zero gross alpha, tails inverted |

One consistent reading covers all three: **the composite is a descriptive
cross-sectional quality ranking and nothing more.** It sorts typical outcomes
across names. It does not forecast a name against its own history, and it does
not convert into portfolio return at any slice or cost. The product that follows
is a research and triage surface, not a portfolio construction input — which is
what the card was always scoped to be, now for measured reasons rather than
assumed ones.

## What is NOT tested here

1. **Value-weighting, risk-weighting, or sector-neutralization.** All would change
   the mean/median relationship, and sector-neutralizing in particular could
   remove skew that is concentrated in specific industries. Untested.
2. **Longer holds.** 63-day holds against quarterly statements; a 4–8 quarter hold
   is a different strategy and is not covered.
3. **Trimmed or winsorized returns.** If the mean is skew-dominated, a trimmed
   estimator would show something else — but a trimmed mean is not what a book
   earns, so it would be a statistic about the signal rather than about P&L.
4. **Survivorship**, unchanged and unfixable from these sources — and here it
   plausibly *creates* part of the effect. The right tail in the bottom decile is
   made of distressed names that recovered; the ones that did not recover are
   absent from the panel entirely. A survivorship-free panel could remove much of
   decile 0's mean advantage.
5. **One regime**, unchanged from the cross-sectional work.
