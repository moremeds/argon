# Theta Harvester — anatomy of the loss

**Date:** 2026-07-29
**Data:** `option_wizard` (mini), 13,890 terminal marks, 2025-12-26 → 2026-07-27,
114 tickers. Exploratory SQL against `theta_harvester_{candidates,markouts}`,
`option_surface_grid_daily`, `daily_ohlc`, `corporate_actions`.

This is a diagnostic study, not a sweep. It asks *why* the strangle lost, rather
than whether a variant loses less. The answer is specific enough to redirect the
whole line of work.

---

## Verdict

**The strategy does not have a volatility problem. It has a short-call problem
concentrated in one theme, and the entire loss lives in a single bucket of
outcomes.**

Stated precisely, because the aggregate is misleading: **short strangles on the
2026 AI complex lost badly, and were flat on everything else** (+0.00002 per
trade over 7,374 non-AI trades). The watchlist is ~46% AI-complex-and-semi-ETF by
trade count, so the headline number is largely a statement about the watchlist's
composition rather than about short strangles.

| Realized move over the hold | n | Put leg | Call leg | Total | Σ contribution |
|---|---:|---:|---:|---:|---:|
| < −15% | 1,441 | −0.0427 | +0.0185 | −0.0242 | −34.9 |
| −15…−5% | 2,570 | +0.0068 | +0.0115 | +0.0183 | +46.9 |
| −5…+5% | 4,600 | +0.0093 | +0.0083 | +0.0176 | +81.0 |
| +5…+15% | 2,581 | +0.0122 | +0.0009 | +0.0132 | +34.0 |
| +15…+30% | 1,337 | +0.0180 | −0.0204 | −0.0024 | −3.2 |
| **> +30%** | **1,218** | +0.0236 | **−0.2210** | **−0.1974** | **−240.4** |

Every bucket from −15% to +15% is profitable (+161.9 combined). The crash tail
costs −34.9. **The melt-up tail costs −240.4** — 8.9% of trades, averaging −19.7%
of spot each, and it is larger than the entire rest of the study combined.

Excluding only the `> +30%` bucket, the strategy returns **+0.0099 per trade over
12,529 trades**.

## Leg decomposition

On 13,747 split-clean rows:

| Leg | Mean / spot | Σ | Loss rate | Worst |
|---|---:|---:|---:|---:|
| **Put** | **+0.00603** | **+82.9** | 11.2% | −0.332 |
| **Call** | **−0.01451** | **−199.5** | 17.2% | −1.909 |
| Net | −0.00848 | −116.6 | | |

**Selling puts made money. Selling calls destroyed it.** The worst single call
outcome is −191% of spot against −33% for the worst put.

## Why — and how much of it repeats

Two effects, and they must be separated because only one of them generalises.

| | Value |
|---|---:|
| Mean put IV at entry | 0.5624 |
| Mean call IV at entry | 0.5307 |
| **Skew (put − call)** | **+0.0318** |
| Sessions where put IV > call IV | **74.3%** |
| Put premium collected / spot | 0.0140 |
| Call premium collected / spot | 0.0120 |
| **Mean underlying move per hold** | **+4.36%** |
| Holds ending higher | 53.1% |

1. **Skew is structural.** The put is richer by 3.2 vol points and is richer
   **74% of the time**. The volatility risk premium is concentrated on the put
   side — a documented, persistent feature of equity options, not an artifact of
   this window. Selling the put collects 17% more premium than selling the call
   at matched delta. **This part should repeat.**
2. **Drift is regime.** +4.36% mean move per ~30-day hold is roughly +65%
   annualised — a violent bull market, and 8.9% of holds moved more than +30%.
   The call leg was run over by direction, not by volatility. **This part should
   not be assumed to repeat, and in a crash it inverts** — note the put leg
   returns −0.0427 in the `< −15%` bucket.

**CORRECTION (same-day, after the sector partition below).** An earlier draft of
this document argued that the put-side edge was structural and therefore
actionable. That claim does not survive removing the watchlist's sector
concentration. Outside the AI complex the two legs are near-symmetric noise
(+0.00179 put vs −0.00176 call). The skew *measurement* stands — the put really
is richer 74% of the time — but the realised put-side P&L advantage is +486bp
inside the AI complex and only +36bp outside it. **The put-side edge is mostly a
2026 semiconductor melt-up, not a structural premium.** See "Universe bias".

## Data-quality findings

### Split contamination is real, bounded, and does not flip the verdict

`daily_ohlc` is back-adjusted to *today's* scale; grid strikes are as-traded. A
split therefore corrupts a mark whenever it falls **after entry** — it does not
need to fall inside the hold, because the settlement close is rescaled by every
split up to the present.

Splits in window (`corporate_actions`, 9 events): XLY/XLE/XLK/XLU/XLB 2:1
(2025-12-05), KLAC 10:1 (2026-06-12), CRWD 4:1 (2026-07-02), KORU 20:1
(2026-07-15).

| | n | Mean | Σ |
|---|---:|---:|---:|
| Clean | 13,747 | −0.00848 | −116.58 |
| **Contaminated (CRWD, KORU)** | **143 (1.03%)** | **−0.12505** | **−17.88** |

**1% of rows carry 13.3% of the loss.** The negative verdict survives their
removal (−0.00848, still solidly negative), but every published mean is ~13% too
pessimistic.

Two guard notes:

- The **entry** strike-range guard in `load_spot` is the effective one — it
  removed KLAC entirely and most of KORU/CRWD before candidates were built.
- The **settlement** guard `_settlement_scale_ok` (`1/4 < ratio < 4`) is too
  loose in principle: 2:1 and 3:1 splits sit inside the bound and would pass. No
  2:1 or 3:1 split affected a live candidate in this window, so the exposure is
  latent rather than realised. **Replace the ratio heuristic with a
  `corporate_actions` join** — the table exists and has exact `split_ratio`.

### The semiconductor losses are genuine

The worst-losing names — SOXL, INTC, ARM, AMD, ALAB, MU, MRVL, QCOM, SNDK, AAOI,
BE, CRCL — show settle/entry ratios up to 3.35, which looks like split
corruption. **None of them split.** Cross-referenced against `corporate_actions`,
these are real moves: a semiconductor melt-up that the short call leg absorbed in
full. The loss concentration is sector concentration, not a data artifact.

## Universe bias — the watchlist is the study's biggest limitation

The option grid covers **exactly the 114 watchlist tickers**. There is no wider
option universe in the warm store, so the universe cannot be widened by
querying; it can only be partitioned. Partitioned by the watchlist's own sector
taxonomy:

| Group | Tickers | Trades | Put | Call | Total | Σ |
|---|---:|---:|---:|---:|---:|---:|
| AI/Semi complex | 35 | 4,277 (31%) | +0.01358 | −0.03503 | −0.02146 | **−91.8** |
| Sector ETFs | 17 | 2,096 (15%) | +0.00557 | −0.01750 | −0.01192 | −25.0 |
| **Everything else** | **59** | **7,374 (54%)** | +0.00179 | −0.00176 | **+0.00002** | **+0.2** |

**79% of the loss comes from 31% of the trades, all expressing the same bet.**
Outside the AI complex and the (largely semi-weighted) sector ETFs, the strangle
is exactly flat: +0.00002 per trade over 7,374 trades.

This is the single most important qualification in this document. The headline
"short strangles lost money" is more precisely **"short strangles on the 2026 AI
complex lost money, and were flat on everything else."**

### Trend conditioning does not work in its directional form

Tested directly: bucket entry `trend_20d_pct`, measure each leg.

| Entry trend | n | Put | Call | Total | n (non-semi) | Put | Call | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| < −10% | 1,735 | +0.0074 | −0.0181 | −0.0107 | 1,128 | +0.0033 | −0.0025 | +0.0008 |
| −10…−3% | 2,351 | +0.0041 | −0.0154 | −0.0113 | 1,417 | +0.0013 | −0.0045 | −0.0032 |
| −3…+3% | 3,250 | +0.0021 | −0.0093 | −0.0072 | 2,028 | −0.0008 | −0.0002 | −0.0010 |
| +3…+10% | 2,443 | +0.0049 | −0.0089 | −0.0040 | 1,321 | +0.0030 | −0.0015 | +0.0014 |
| +10…+25% | 2,163 | +0.0083 | −0.0177 | −0.0094 | 969 | +0.0043 | −0.0048 | −0.0005 |
| > +25% | 1,805 | +0.0130 | −0.0230 | −0.0100 | 511 | +0.0021 | **+0.0065** | **+0.0086** |

Neither half of the proposed rule survives:

- **"Don't sell puts in downtrends"** — the put leg is *positive in every trend
  bucket*, including the deepest downtrend (+0.0074 full, +0.0033 non-semi).
- **"Don't sell calls in uptrends"** — the call leg is negative in *every* bucket
  including downtrends, so it is not an uptrend effect. On non-semi names the
  strongest-uptrend bucket has the **most positive** call leg (+0.0065) and the
  best total (+0.0086) — the opposite of the rule.

The mechanism is a sign flip in trend persistence between themes:

| Group | n | corr(trend, fwd move) | corr(trend, \|fwd move\|) | avg fwd | avg \|move\| |
|---|---:|---:|---:|---:|---:|
| Everything else | 7,374 | **−0.0447** | +0.0661 | +0.75% | 10.6% |
| AI complex + ETFs | 6,373 | **+0.0938** | +0.1388 | **+8.54%** | 17.0% |

Trend predicts **continuation** in the AI complex and mild **reversion**
elsewhere. A single directional trend rule therefore cannot be right for both
halves of the universe, which is exactly what the bucket table shows.

**The salvageable formulation is magnitude, not direction.** `corr(trend,
|forward move|)` is *positive in both groups* (+0.139 and +0.066). High |trend|
predicts a bigger subsequent move regardless of sign, and a bigger move is bad
for any short-premium structure. A `|trend|` ceiling generalises where a signed
trend filter does not.

## What this means for the sweet-spot question

The original question was where the optimum sits in (delta, DTE). **That is a
second-order question and this study found the first-order one.** The leg
asymmetry is +0.006 vs −0.0145 — an order of magnitude larger than any plausible
delta/DTE tuning. Optimising the strike ladder of a structure whose call leg is
the entire loss is polishing the wrong surface.

A **defined-risk put credit spread** remains the indicated direction, but on
weaker grounds than an earlier draft of this document claimed. It drops the leg
that produced the loss and satisfies the defined-risk standing rule, and it
converges with the desk's independent VRP research (single-name condors parked,
macro bull put spread promoted). What it does **not** have is a demonstrated
structural premium: outside the AI complex the put leg earns +18bp per trade,
which is indistinguishable from zero at this sample size.

**Not yet tested here.** The put-only arm's +0.00603 is a *leg* decomposition of
a strangle, not a backtest of a put-spread strategy — it carries no wing cost, no
re-selected strikes, and the same same-close-entry lookahead. On the non-semi
subset the honest expectation for such a backtest is **flat**, not positive.

### Widening the universe is possible but not free

The bias is real and only new capture fixes it. UW serves historical chains for
~180 calendar days, so a research backfill can reach back to **~2026-01-30
(123 sessions)** — 6 months rather than the current 8, but on any ticker set.

Measured cost drivers: **17.3 expiries per ticker-session** across the full term
structure, **7.6** if capped at ≤60 DTE (which covers the 7–45 DTE the strategy
actually trades). Per ticker-session that is 1 `greek_exposure_by_expiry` call
plus one `greeks` call per expiry.

| Plan | UW calls | vs 120k/day budget |
|---|---:|---:|
| 50 tickers × 123 sessions × all expiries | ~112,500 | ~94% — starves the live pool |
| 50 tickers × 123 sessions × ≤60 DTE | ~52,900 | ~44% |
| **50 tickers × weekly (25 sessions) × ≤60 DTE** | **~10,750** | **~9%** |
| 30 tickers × weekly × ≤60 DTE | ~6,450 | ~5% |

**Weekly sampling is the right call and is not a compromise.** With ~30-day holds,
consecutive daily entries overlap ~95% and are not independent observations — the
weight sweep already equal-weights by month for exactly this reason. Weekly
entries lose little information and cost a fifth as much.

Two implementation notes: `option_surface_backfill` iterates
`repo.list_watchlist_cards()`, so it is watchlist-bound and has no DTE cap or
date-sampling parameter — both would need adding. And adding 50 names to the
watchlist permanently raises the *daily* burn across every per-ticker job, not
just this backfill. **Prefer parameterising the backfill with a research-only
ticker list** over polluting the watchlist.

### Feasibility confirmed for the (delta × DTE) sweep

Should the structural question be settled first, the parameter sweep is
buildable from the warm store with no new capture:

- `option_surface_grid_daily` greeks are **100% populated** (delta, gamma, theta,
  vega per side).
- DTE 0–120 is dense across all 114 tickers and 146 sessions (4.0M rows at 0–14
  DTE, 2.6M at 15–29, 2.1M at 30–44, ~400–800k per bucket out to 120).
- Delta granularity is ~50 strikes per 0.01 bucket at 25–35 DTE.
- `daily_ohlc` covers 129 tickers, 2025-12-01 → 2026-07-28 — **but is
  back-adjusted**, so any synthetic construction must join `corporate_actions`
  rather than trusting the ratio heuristic.

## Constraints

- **8 months, one regime**, and an unusually directional one (+65% annualised
  drift). The single most important caveat in this document.
- **Same-close entry** — lookahead no live trade has.
- **No bid-ask** anywhere.
- **European settlement on American options** — early assignment would usually be
  worse; terminal P&L is an optimistic bound on the loss.
- **Survivorship** — universe is today's watchlist, no membership history.
- The conditional payoff table is **descriptive, not predictive**: it buckets on
  the realized move, which is unknown at entry.

## Reproduce

Exploratory SQL, run against `option_wizard` on the mini. The contamination
filter used throughout:

```sql
AND NOT EXISTS (SELECT 1 FROM uw_scan.corporate_actions ca
                 WHERE ca.ticker = c.ticker AND ca.event_type = 'split'
                   AND ca.event_date > c.as_of)
```

Leg decomposition: `(c.put_mark - m.put_mark)/c.underlying_spot` and
`(c.call_mark - m.call_mark)/c.underlying_spot`, joined on `(ticker, as_of)` with
`m.horizon_days = -1`. Conditional table buckets on
`(m.spot - c.underlying_spot)/c.underlying_spot`.
