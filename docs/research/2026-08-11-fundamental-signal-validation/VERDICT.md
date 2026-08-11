# VERDICT — the composite orders returns at 245 names and is noise at 25

*2026-08-11 · hand-written, not regenerated · numbers in `results{,_wide}.md` /
`validation{,_wide}.json` · reproduce:*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_universe_breadth_probe.py
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py --wide
```

Run **before** P1b built any ingest, on the reasoning that the whole dataset sits
behind ~1,000 API calls and it is cheaper to test a method than to build storage
for one that may not work. That reasoning held: this file has now been rewritten
twice on evidence, at no cost in shipped code.

## Revision history — this file has been wrong twice, in opposite directions

| Rev | Claim | Why it was wrong |
|---|---|---|
| 1 | "The ranked composite has no predictive content." | Never asked what the test could detect. Its floor was \|IC\| 0.072; a real factor is 0.02–0.05. |
| 2 | "Untestable at this universe size; and `asset_turnover` is significantly inverted (t −4.30)." | The size point was right and is now resolved. The inversion was a **bucketing bug**, not a finding. |
| 3 | *this file* | — |

Both earlier errors shared one shape: a number was read correctly and the
inference drawn from it was too strong.

## The headline

**At 245 names the fundamental composite orders forward returns. At the 25-name
AI cohort it does not, and cannot — the cross-section is too thin to measure.**

| | AI cohort (25) | Wide (245) |
|---|---:|---:|
| median cross-section | 18 | **241** |
| per-quarter IC σ | 0.307 | **0.108** |
| 2q composite mean IC | 0.0238 | **0.0590** |
| 2q t-stat | 0.68 | **4.84** |
| 2q hit rate | 51.9% | **71.8%** |
| 1q composite IC / t | −0.0077 / −0.23 | 0.0404 / 3.28 |

Same code, same features, same horizons, same 20-year span. The only change is
breadth — and breadth is what the power calculation said was the binding
constraint. It was.

### The most defensible single number is 0.039, not 0.059

Restricted to observations carrying a **real** `filing_date` (no 45-day
fallback, so no possibility of scoring on data before it was public):

**2q composite IC 0.0391, t 2.672, over 66 quarters.**

Lead with that one. The full-sample 0.059 is inflated by whatever leakage the
fallback introduces, and a 34% attenuation is roughly what you would expect if
part — not all — of the headline came from timing optimism.

## The bucketing bug, which is the methodological lesson here

The panel was keyed on `fiscal_date_ending`. Filers do not share a fiscal
calendar: NVDA's quarter ends 01-31, MSFT's 12-31, AAPL's 12-28. Keying on the
raw period end shatters one economic cross-section into many thin ones, each of
which then fails `MIN_CROSS_SECTION` and is dropped **silently**.

Measured on the wide universe: 268 "periods" with a median width of **23** out
of 245 available names. Re-keyed on the **knowledge-date quarter** — which is
the correct construction anyway, since a rank IC is only meaningful among names
whose information was available at the same time — the same data yields 97
buckets at a median width of **241**.

What it cost: revision 2's most quotable finding. `asset_turnover` at
1q IC −0.155, t −4.30 became −0.014, t −0.49. I attached a coherent economic
story to it ("the companies investing beat the companies harvesting — a clean
description of the AI capex buildout") and even flagged that its coherence was
suspicious. It was. The cause was more mundane than the caveat I wrote:
comparing NVDA's January quarter against MSFT's December quarter and calling the
result a cross-section.

**A silent drop is worse than a crash.** The bug did not error; it quietly
discarded ~90% of the cross-section and returned a confident, well-formatted,
wrong number. The guard that would have caught it — assert the realised
cross-section width against the universe size — costs one line.

## Robustness — both checks the result had to survive

Chosen before seeing them, as the two ways a positive result here is most likely
fake. Neither can prove the effect; both could have killed it.

| 2q composite | IC | t | quarters |
|---|---:|---:|---:|
| full sample | 0.0590 | 4.84 | 78 |
| **real `filing_date` only** (no PIT fallback) | **0.0391** | **2.67** | 66 |
| first half (≤2015) | 0.0719 | 4.36 | 38 |
| second half (≥2016) | 0.0468 | 2.61 | 40 |

Survives both. Present in both eras, and **decaying** — 0.072 → 0.047.

The same table on the 25-name cohort flips sign between halves (+0.145 then
−0.088) and goes negative on the filing-date subset (−0.038). That is what noise
looks like, and it is the correct reading of the cohort run.

## Per-component, 2q, wide

| Signal | IC | t | reading |
|---|---:|---:|---|
| `neg_net_debt_ebitda` | 0.0888 | 6.21 | low leverage predicts higher returns |
| `asset_turnover` | 0.0813 | 7.10 | capital efficiency |
| `fcf_margin` | 0.0379 | 3.64 | cash conversion |
| `roe` | 0.0262 | 2.09 | weak |
| `rev_growth` | 0.0228 | 1.72 | not significant |
| `gross_margin` | −0.0223 | −2.02 | **inverted** |
| `op_margin` | −0.0244 | −2.56 | **inverted** |

The two margin signals are still inverted, now on a well-powered test rather
than a broken one. The likely reason is that nothing here controls for
**valuation**: high-margin firms are usually richly priced, so a margin ranking
is partly an expensiveness ranking. That is a hypothesis, not a finding — no
price ratio was tested.

## What this is NOT

1. **Not novel alpha.** Profitability, low investment and low leverage are the
   documented quality factors (Novy-Marx; Fama-French 5F). Recovering them is
   evidence the **pipeline is correct**, not that an edge was discovered. The
   decay from 0.072 to 0.047 is consistent with a known, crowded factor.
2. **Not survivorship-free, and this cannot be fixed.** Both sources carry live
   tickers only — ATVI, XLNX, TWTR, SIVB, FRC and VMW are absent from the lake
   **and** return HTTP 200 with an empty array from UW. Widening buys power; it
   cannot buy back the names that failed. One mild reassurance: survivorship
   should bias the leverage result *negative* (levered names that survived
   recovered strongly), and it came out positive.
3. **Not a strategy.** No transaction costs, no capacity, no borrow, no
   shorting constraints, no turnover limit. An IC of 0.04 is an ordering, and
   the distance from ordering to net-of-cost P&L is where most of these die.
4. **Not independent observations.** 2q windows overlap across adjacent
   quarters, so t = 4.84 overstates confidence. Read it as "clearly not zero",
   not as a p-value.
5. **Prices are split-adjusted** — verified against NVDA's 4:1 and 10:1 and
   AAPL's 4:1 (continuous ratios, no cliffs). Dividend adjustment was *not*
   verified; the stack review's "livewire `adj_close`" blocker may concern that
   narrower claim.

## What this changes for argon

The awkward part: **the signal works on a universe argon does not have.** The
watchlist is ~173 names heavily concentrated in AI/semis, and the fundamental
agent's cohort is 25 of them. On that cross-section the composite is
indistinguishable from noise — not because the method fails, but because 18
correlated names cannot produce a measurable ranking at any history length.

1. **Ship the descriptive card for the AI cohort** — per-subscore values,
   trends and absences, presented beside the options surface. Unchanged
   recommendation, but now for a *measured* reason rather than an assumed one:
   at cohort width the ordering is unmeasurable.
2. **Do not put a sortable composite score on a 25-name page.** It would be a
   validated-elsewhere number applied where its validation does not hold.
3. **A ranked composite becomes legitimate the moment the surface is broad.**
   If a screen ever covers 200+ names, the ranking has a real basis — leading
   with 0.039, 2q horizon, quarterly rebalance.
4. **Drop the direction claims on `op_margin` and `gross_margin`** in §5.2, or
   test them against a valuation control first. Both are inverted on the
   powered test.
5. **P1b remains worth building.** Nothing here argues against ingesting the
   data.

## What would change the verdict

- **A valuation control.** The inverted margins point at a missing price
  dimension; adding one would test whether the composite survives it.
- **A non-survivorship universe.** Not constructible from UW or the lake.
  Requires a source carrying delisted tickers (CRSP, Sharadar) — the one gap
  that money, not method, fixes.
- **Costs and turnover.** The first thing that would move this from "orders
  returns" toward "is worth trading".
