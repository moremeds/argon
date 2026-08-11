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

## Follow-up: the valuation control — hypothesis rejected

Rev 4 withdrew the direction claim on `profitability` and offered a reason: nothing
in the harness controls for valuation, and high-margin firms are usually richly
priced, so a margin ranking might be an expensiveness ranking in disguise. That
was a story with no test behind it. `fundamental_valuation_control.py` is the
test — market cap from **raw** close × as-reported shares (never `adj_close`,
which would mix reference frames across every split), ratios formed as yields so
the ranking stays monotone through zero earnings, and a rank-based partial
correlation reusing the same `spearman`.

**The hypothesis fails.** 2q, 245 names, 80 quarters:

| | uncontrolled | \| `earnings_yield` | \| `book_to_price` | \| `fcf_yield` |
|---|---:|---:|---:|---:|
| `gross_margin` | −0.0194 | −0.0180 | −0.0271 | −0.0144 |
| `op_margin` | −0.0270 | −0.0231 | −0.0306 | −0.0298 |

`op_margin` barely moves under any control — and against `book_to_price` both
margins get *stronger*, not weaker. Expensiveness does not explain the
inversion. **Keep withholding the direction on `profitability`, now for the
stronger reason: the inversion is real and unexplained.**

### The finding that matters more: value is inverted here too

| Signal | IC | t |
|---|---:|---:|
| `fcf_yield` | +0.0285 | 2.84 |
| `earnings_yield` | −0.0194 | −1.43 |
| `book_to_price` | **−0.0365** | **−2.32** |

Cheap-on-book predicted *lower* returns over 2005–2026. That is the documented
post-GFC value drawdown, not a discovery — and note survivorship should have
biased this *toward* value (cheap names that went bankrupt are excluded), so the
true effect was likely worse than measured.

**This qualifies the headline result more than the margin question does.** The
signals that worked — low leverage, high asset turnover, FCF yield — are exactly
the quality/growth profile that led one long regime, while the signals that
failed are the value profile that lagged it. The earlier robustness split
(2005–2015 vs 2016–2026, both positive) is therefore weaker evidence than it
appeared: **both halves sit inside the same regime.** A genuine out-of-regime
test needs a period where value led, which this 245-name survivor universe does
not contain.

Treat the composite as measured-in-one-regime until that is tested. It does not
retract the result; it bounds what the result covers.

## What would change the verdict

- ~~**A valuation control.**~~ **Done — hypothesis rejected** (above). The
  margins stay inverted; the incidental finding that value itself is inverted is
  the more consequential one.
- **An out-of-regime window.** Now the top item. Every quarter measured here
  sits in one quality-led, value-lagging regime, so "present in both halves"
  does not establish regime-independence. Needs a period where value led —
  pre-2005 data, or a universe that is not 245 US large-cap survivors.
- **A non-survivorship universe.** Not constructible from UW or the lake.
  Requires a source carrying delisted tickers (CRSP, Sharadar) — the one gap
  that money, not method, fixes.
- **Costs and turnover.** The first thing that would move this from "orders
  returns" toward "is worth trading".
