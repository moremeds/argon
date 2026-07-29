# Theta Harvester — iron condor vs naked strangle

**Date:** 2026-07-29
**Data:** `option_wizard` (mini), 145 sessions 2025-12-26 → 2026-07-27, 114 tickers,
13,890 candidates with terminal (at-expiry) marks.
**Sweep run:** `uw_scan.backtest_sweep_runs.run_id = 2`, strategy
`theta_harvester_condor`, 21 configs, 0 errors.

**Reproduce:**

```bash
# prerequisite: candidates + terminal markouts must already be populated
uv run python scripts/backfill/theta_harvester_backfill.py
uv run python scripts/research/theta_harvester_condor_sweep.py
```

---

## Why this was run

The 2026-07-28 weight sweep found the score orders candidates (IC +0.075) while
the selected set still lost money held to expiry. The terminal distribution
explains why, and it is a tail problem rather than a grind:

| n | win rate | median | p05 | p01 | worst |
|---:|---:|---:|---:|---:|---:|
| 13,890 | 74.7% | +1.42% | −16.6% | −52.2% | −186% |

Three quarters of these trades win. The mean is negative purely because of the
left tail: the 7.9% of trades losing more than 10% of spot account for **225% of
the total P&L sum** — they erase everything the other 92% earned, twice.

Capping the loss with **free** wings flips the sign:

| Max loss | Mean return / spot |
|---|---:|
| uncapped | −0.00968 |
| −20% | −0.00137 |
| −10% | **+0.00423** |
| −5% | **+0.00927** |

That is the upper bound, not the answer. This study prices the wings and
subtracts them. It also settles a standing-rule conflict independent of P&L: a
condor is defined-risk, a naked strangle is not.

## Method

For each candidate, the wing is the **nearest listed strike at or beyond** a
target offset (5% / 10% / 20% of entry spot), taken from
`option_surface_grid_daily` on the entry session, with a non-null IV. Wings are
priced Black-Scholes off the **same grid IV surface** that priced the short legs,
so no entry edge can be manufactured by pricing the two sides from different
sources. Settlement is intrinsic against the expiry close.

**Payoff self-check:** the recomputed naked-strangle P&L reproduces the stored
production markout to `max |diff| = 0.00000000` across all 13,890 rows. Since
the condor differs from the naked payoff by exactly one term (the wing refund),
this validates the condor arithmetic by construction.

**Reproduction of the prior study:** `default/naked_full` returns mean −0.00035,
IC +0.0751, t 6.35, 8 months, 2,636 trades — identical to the 2026-07-28 sweep's
published `default` row. The earlier concern that the published numbers could
not have come from the committed code is resolved: the *markout data* was sound;
only the re-run path was broken (the `underlying_spot` KeyError, fixed in #312).

### Wing availability is not random

| Width | Put wing found | Call wing found | **Both** |
|---|---:|---:|---:|
| 5% | 13,859 | 13,092 | **13,063 (94.0%)** |
| 10% | 13,685 | 12,121 | **11,986 (86.3%)** |
| 20% | 12,635 | 9,640 | **8,981 (64.7%)** |

The **call wing is the binding constraint** and it worsens with width — equity
chains list fewer far-OTM calls than puts. At 20% the surviving rows are
disproportionately large names with deep chains, i.e. a *different universe*, not
merely a smaller one.

**Every width therefore evaluates both arms on the identical row set.** Comparing
a condor built on the 65% of rows that have wings against a strangle built on
100% would reproduce the radon trap in a new costume. `naked_full` is reported
for continuity and labelled as a different sample.

## Results

Matched samples. Monthly equal-weighted mean return per unit of entry spot.

### Control arm — no score, sell everything

| Width | Naked | Condor | Δ (condor − naked) | Trades |
|---|---:|---:|---:|---:|
| 5% | −0.00712 | **−0.00222** | +0.00490 | 13,063 |
| 10% | −0.00746 | **−0.00320** | +0.00426 | 11,986 |
| 20% | −0.00731 | **−0.00501** | +0.00230 | 8,981 |
| *(full sample)* | *−0.00801* | — | — | *13,890* |

**Wings help the control arm at every width and never rescue it.** The best
condor still loses 0.22% of spot per trade. Against the free-wing upper bound of
+0.00423 at a 10% cap, the realised 10% condor is −0.00320 — **the wing premium
consumes the entire tail saving and roughly 0.7% of spot more.**

### Selected arm — `default` weights

| Width | Naked | Condor | Δ (condor − naked) | Trades |
|---|---:|---:|---:|---:|
| 5% | **+0.00095** | +0.00032 | −0.00063 | 2,419 |
| 10% | **+0.00117** | +0.00024 | −0.00093 | 2,269 |
| 20% | **+0.00395** | +0.00249 | −0.00146 | 1,680 |
| *(full sample)* | *−0.00035* | — | — | *2,636* |

**The condor is worse than the naked strangle at every width for the selected
set.** This is the study's central finding and it is coherent: the score already
avoids the tail, so wings add cost without adding protection. Net wing cost rises
with width (0.00063 → 0.00146) because far wings are cheap but almost never pay.

### Information coefficient — the primary metric

| Config | IC | t | Sessions |
|---|---:|---:|---:|
| `default/naked_full` | +0.0751 | 6.35 | 130 |
| `default/naked@20pct` | +0.0970 | 7.75 | — |
| `default/condor@10pct` | +0.0816 | 7.19 | — |
| **`default/condor@20pct`** | **+0.1001** | **7.76** | — |
| `radon/*` | −0.0784 … −0.0007 | −2.08 … −0.01 | — |

**The condor structure improves the IC** (+0.075 → +0.100), the highest in either
study. Capping the tail removes idiosyncratic outliers the score cannot predict,
leaving the part it can. As a *ranking* target, condor P&L is more learnable than
strangle P&L — even though it is less profitable.

## The radon trap reproduces itself, visibly

| Config | Mean | Sharpe | Months | IC |
|---|---:|---:|---:|---:|
| `radon/naked_full` | +0.01304 | 2.23 ± 2.20 | 3 | −0.0520 |
| `radon/condor@20pct` | +0.01439 | **4.39 ± 2.69** | 3 | −0.0044 |
| `radon/naked@20pct` | +0.01915 | 4.15 ± 2.62 | 3 | −0.0007 |

radon's Sharpe inflates to **4.39** under the condor — the best-looking number
produced by either study, on 3 months, 186 trades, with a negative IC. The
instrumentation added here (`sharpe_se`, `effective_n_months`, `first_month`/
`last_month`) makes it self-evidently uninterpretable at the point of reading
rather than several analysis steps later. That was the design goal.

**No Sharpe in this study is more than ~1 SE from zero** except radon's, whose SE
is larger than most of the other point estimates.

## Verdict

**Do not adopt the condor for P&L. Do adopt it for defined risk.**

1. **Wings do not rescue the strategy.** The control arm improves but stays
   negative at every width. "Sell strangles broadly and buy wings" does not work
   over this window.
2. **Wings cost more than they save once the score selects.** `default/naked`
   beats `default/condor` at 5%, 10% and 20%. The score is already performing
   the tail-avoidance job wings would perform, for free.
3. **The condor is still the right structure to ship**, because the standing rule
   is defined-risk-only and the measured cost of compliance is now known and
   small: **6–15 bp of spot per trade**. That is the honest price of not holding
   an undefined-risk position, and it is worth paying.
4. **The strongest ranking result in either study is `default/condor@20pct`,
   IC +0.100 (t 7.76)** — but it is a ranking claim, not a profitability claim,
   and the t-stat is computed over overlapping sessions so it is a screen rather
   than a p-value.

### An unresolved lead: chain depth as a filter

`default/naked@20pct` returns +0.00395 — the best legitimate mean in the table —
and its sample is defined by *having a deep enough options chain*. That is an
ex-ante observable filter with no lookahead, so it may be a real and
implementable edge (trade only names with deep chains). It is equally consistent
with selection noise on 1,680 trades and a Sharpe of 0.51 ± 1.23. **Not claimed
as a result; recorded as the most promising thing to test next.**

## Constraints carried by every number above

- **No bid-ask, and this cuts against the condor specifically.** A condor crosses
  **four** spreads, not two, and the wings are the least liquid strikes in the
  chain. The measured 6–15 bp condor penalty is therefore a *floor*; the real
  penalty is larger. This does not change the direction of the verdict.
- **Same-close entry.** Candidates are built from a session's closing surface and
  entered at that same close — a lookahead no live trade has.
- **Effective N is months, not rows.** 8 months, one broad regime.
- **Wing availability censoring.** 6% / 14% / 35% of rows are dropped at 5% / 10%
  / 20% width. Matching the arms removes the *comparison* bias but not the
  *universe* bias: the 20% rows are large-cap-tilted.
- **Survivorship.** The universe is today's watchlist; argon stores no membership
  history. Names dropped mid-window are absent, which runs optimistic.
- **European settlement on American options.** Early assignment would have closed
  short legs sooner and usually worse, so terminal P&L is an optimistic bound on
  the loss — for both arms, but it matters more for the naked one.
- **Not a strategy return.** No slippage, no position sizing, no management rule,
  no exit before expiry. Model P&L on a fixed structure held to settlement.
