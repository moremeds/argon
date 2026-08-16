# CLUSTER VERDICT — the chain is a sector, and it does not propagate

*2026-08-13 · numbers in `growth_clusters_revenue.json` / `growth_clusters_capex.json` · reproduce:*

```bash
uv run python scripts/research/growth_factor_clusters.py --metric=revenue
uv run python scripts/research/growth_factor_clusters.py --metric=capex
```

Round 3 closed the ledger on a returns test that could only ever measure one
thing (see below). This round asks the prior question directly in fundamentals,
where the sample is **370 tickers x 79 quarters, 2006-2026** rather than 35
months — and answers it without needing prices at all.

## What was measured

Per-ticker quarterly YoY log revenue and capex growth. The common factor —
"everything moved together" — is the cross-sectional mean of per-ticker
standardised growth; every ticker is residualised on it before anything is
correlated. Groups are then discovered from the residuals (hierarchical +
kNN) rather than declared, and the hand-authored `watchlist_chain` taxonomy is
tested as a hypothesis rather than assumed.

## The hypothesis this round tested, and which part of it failed

Operator's, 2026-08-13, in three parts:

> "we cant use one group to group the universe … we can use the first 8 tickers
> to be one group, then create more tickers with different categories … then we
> can probably find the interaction with each group" — later refined to
> "it is more like clusters".

**Part 1 — one basket is wrong. CORRECT, and it identified a real defect.**
`capex_returns_test.py` multiplied each supplier's `gamma` by ONE scalar per
month, so it ranked by `gamma` and merely reversed the sort when the scalar went
negative. A common shock cannot generate a cross-section; it can only reorder
one. Round 3's verdict was therefore narrower than it claimed. See
`reference_scalar_shock_cannot_make_cross_section`.

**Part 2 — discover groups rather than declare them. WORKS.** Clustering
residual revenue growth recovers a recognisable semi complex (AMAT, ASML, ACLS,
AEHR, AEIS, AMKR, ADI, AAOI) with zero taxonomy input, and it removes the
researcher's priors from the edge map — which was the point of preferring it to
a hand-authored bipartite graph.

**Part 3 — then find the interaction between groups. THIS IS WHERE IT DIES**,
and the reason is structural rather than a data shortfall:

1. **Clustering is a lag-0 operation.** Groups are formed by contemporaneous
   similarity, so a clustering method is blind by construction to the sequential
   structure the interaction step needs. Finding excellent clusters guarantees
   nothing whatsoever about lead-lag — the two are orthogonal, and getting part 2
   right does not advance part 3 at all.
2. **The groups it finds are industries, and industry peers do not lead each
   other.** They respond to the same demand at the same time. Same-chain
   correlation is +0.242 and it sits at lag 0.
3. **Between chains there is nothing to propagate.** After the common factor is
   removed, different-chain mean correlation is **−0.005** — not weak, zero, at
   every lag tested. The chains are internally coherent and mutually
   independent.

So the measured structure is **two levels, not a chain**: one common factor that
moves everything (8–14% of variance), and a set of industry islands that each
move on their own. A 产业链 in the sense of a *sequence* — capex here, revenue
there, two quarters later — does not appear in fundamentals at any lag that
survives a split-half check.

The theory was right about the defect and right about the method. It was wrong
in assuming that groups, once found, would stand in a measurable order.

## There are no clusters — the partition was imposed, not found

`N_CLUSTERS = 8` and `KNN = 8` were both constants typed into the script. The
second is the worse error: the operator's "we can use the first 8 tickers to be
one group" was an *illustration of a concept*, and it was hardcoded as a
parameter with a comment crediting them for a specification they never gave.

Mean silhouette over the residual distance, average linkage, k = 2..15:

```
2:+0.100  3:+0.087  4:+0.079  5:+0.065  6:+0.067  7:+0.077  8:+0.071  9:+0.071
```

It peaks at k=2 and declines. **0.100 is not cluster structure** — below ~0.25
points are barely closer to their own group than to the next one. The universe
of growth residuals is a continuum; every reported cluster size is an artefact
of where the dendrogram was cut. **The clusters must not be rendered as groups.**

What survives is the PAIRWISE level. Best-peer correlation is high everywhere
(p10 0.50, p50 0.66, none below 0.30) but that number cannot validate a peer
set: it is the max over ~370 candidates and is selection-biased upward even
under noise. The measure that discriminates is **coherence** — mean correlation
*among* a ticker's peers, i.e. does the triangle close:

| | coherence | |
|---|--:|---|
| AMAT | 0.585 | ~p90, a real peer group |
| ANET | 0.292 | ~median |
| NVDA | 0.288 | ~median |
| VRT | 0.153 | ~p10 |
| MSFT | 0.134 | ~p10 |

Distribution: p10 0.18 · p25 0.26 · p50 0.36 · p75 0.52 · p90 0.75.

**An eyeball read of the peer lists scored 2 of 4 and inverted the confident
case.** Reading the ticker names, VRT's set (GD, ANET, HPE, TEL, ETN, MOD) was
annotated "coherent datacenter infra" and NVDA's (LLY, ACGL, ALL, AMD, AXON,
EFX) "noise". Measured, VRT is near the bottom decile and NVDA is at the median.
Recognisability is not coherence, and the annotation was published before the
metric existed to check it.

### The null, and what it does to the reading above

Each ticker's residual series rolled by its own random offset — destroying
cross-ticker alignment while preserving each series' own autocorrelation, so
surviving coherence is shared *timing* rather than shared shape.

| | p10 | p25 | p50 | p75 | p90 |
|---|--:|--:|--:|--:|--:|
| observed | 0.18 | 0.26 | **0.36** | 0.52 | 0.75 |
| null | 0.17 | 0.23 | **0.32** | 0.42 | 0.54 |

**The bottom half is indistinguishable from noise.** Only the upper tail
separates: 24.1% of tickers clear the null's p90 against 10% by chance, a 2.4x
excess confined to the top quarter.

That re-reads the table above. AMAT (0.585) is genuinely above the null's p90.
**VRT (0.153), MSFT (0.134), NVDA (0.288) and ANET (0.292) are all at or below
the NULL's median of 0.32** — the median of the observed distribution is itself
noise, so "sits at the median" was never a rehabilitation.

**The error chain is the lesson, and it ran in both directions:**

1. Peer lists were annotated by eyeball, from ticker recognisability. No basis.
2. Best-peer `r` came back uniformly high (p10 0.50), which was read as
   contradicting those labels. Wrong statistic — a max over ~370 candidates is
   selection-biased upward, so it cannot validate anything.
3. Coherence was built, NVDA landed "at the median", and the annotations were
   publicly retracted as wrong.
4. The null then showed the median *is* noise — so the original labels had been
   right about 4 of 5, and step 3 was an over-correction.

**A percentile inside the observed distribution carries no information until a
null says what that distribution would look like by chance.** Ranking something
"median" and treating that as "acceptable" assumes the population is mostly
real. Here it is mostly noise, and the retraction was worse than the guess.

### Where the 8 came from, and what k should be

`N_CLUSTERS = 8` and `KNN = 8` were both lifted from a number inside a
conversational example ("we can use the first 8 tickers to be one group"), which
illustrated the *concept* of multiple groups and proposed no parameter. It was
applied to two unrelated quantities — how many groups the universe splits into,
and how many peers each name has — and carried a comment crediting the operator,
which turned an arbitrary pick into an apparently sourced requirement. That
comment is the real damage: a parameter that looks justified never gets reviewed.

The evidence, sweeping k with the null recomputed at each k (coherence falls
with k mechanically, so only the excess over a same-k null is readable):

| k | obs p50 | null p50 | null p90 | share > null p90 |
|--:|--:|--:|--:|--:|
| 2 | 0.534 | 0.504 | 0.859 | 11.8% |
| 3 | 0.469 | 0.432 | 0.805 | 12.7% |
| 5 | 0.408 | 0.364 | 0.678 | 18.4% |
| 8 | 0.361 | 0.312 | 0.549 | 24.1% |
| 10 | 0.337 | 0.287 | 0.499 | 24.6% |
| 11 | 0.325 | 0.277 | 0.475 | **25.4%** |
| 13 | 0.311 | 0.260 | 0.445 | 24.9% |
| 16 | 0.294 | 0.241 | 0.393 | 24.6% |

**The curve plateaus from k≈8 and stays flat to 16.** So 8 was unjustified but
not consequential — it lands where the metric stops discriminating. k=11 is the
argmax at 25.4% against 24.1% for k=8, a 1.3pp gap on six null reps; taking that
as "the right k" would repeat the argmax-of-a-flat-noisy-curve error this same
study logged one round earlier. Read it as: **anything from 8 to 16 is
equivalent; below 6 the test loses power.**

The more useful result is what the column tops out at. **The excess never
exceeds ~25% at any k**, and at k=2-3 — the tightest and most defensible pairs —
it is 11.8% and 12.7% against 10% by chance. Whatever peer structure exists is a
diffuse neighbourhood effect requiring k≥8 to detect, not a tight-pair one, and
it covers a quarter of the universe at best.

## Three results

### 1. The common factor is small in fundamentals — and removing it works

| | leading eigenvalue share, raw | residual |
|---|--:|--:|
| revenue | 13.7% | 11.1% |
| capex | 8.1% | 5.2% |

A market factor typically carries 30–50% of *return* variance. In fundamental
growth it carries 8–14%. **The confound that dominated every price-based round
of this study is far weaker on this side of the data**, which is the case for
doing the work here.

The residualisation is clean rather than merely applied: mean correlation
between *unlinked* pairs goes to **−0.005**, i.e. exactly zero, while linked
pairs keep +0.242. A factor removal that zeroes the baseline without eating the
signal is correctly specified.

### 2. The chain effect is a SECTOR effect — this kills the headline

| revenue | mean r same-chain | mean r different-chain | delta | perm p |
|---|--:|--:|--:|--:|
| all pairs | 0.242 | −0.005 | **+0.247** | 0.0005 |
| **same-sector pairs only** | — | — | **+0.015** | **0.444** |

| capex | delta | perm p |
|---|--:|--:|
| all pairs | +0.065 | 0.0005 |
| **same-sector pairs only** | **+0.050** | **0.233** |

Restricted to pairs that already share a sector, chain membership adds nothing
on either metric. The +0.247 was real and it was **industry**: semis correlate
with semis. `watchlist_chain` is a good industry classification — which is
worth knowing, since it is what the layer rail and `/industry_graph` need — but
it is not measurably a *supply chain*.

**Power caveat, stated rather than buried.** The control keeps only 187 linked
/ 48 unlinked pairs (revenue) and 177 / 39 (capex); sector tags exist for 173
of 283 chain tickers. This is "no evidence that chain adds beyond sector", not
"evidence that it does not". The binding constraint is the ~40 unlinked
same-sector pairs.

### 3. No stable propagation between chains

Chain-mean residual growth, cross-correlated at lags −4…+4. Aggregating before
correlating is deliberate: Round 2 found per-ticker peak lags agreeing only
15/52 across windows, because the argmax of a weak correlation is the argmax of
noise. A chain mean is quieter, so its argmax has a chance of being a lag.

| | revenue | capex | chance |
|---|--:|--:|--:|
| peak at lag 0 | 9.5% | 12.4% | 11.1% |
| mean r at lag 0 | −0.005 | +0.006 | 0 |
| mean peak r | +0.171 | +0.202 | — |
| **split-half peak-lag agree, exact** | 17.1% | 9.7% | **11.1%** |
| **split-half peak-lag agree, ±1** | 30.5% | 29.1% | **33.3%** |

**Both metrics are at or below chance on the ±1 measure**, and capex is below
chance on both. `mean peak r` of +0.17/+0.20 is not a finding — it is the
maximum of nine noisy draws, upward-biased by construction, which is precisely
why the split-half test was built to adjudicate instead.

28 chains cleared the ≥4-member floor; 378 pairs; 351 had enough data in both
halves.

## Verdict

**The AI industry chain, as encoded in `watchlist_chain`, is an industry
grouping with no measurable propagation structure in fundamentals.** Names
inside a chain share a growth cycle because they share an industry, and no
chain's growth leads another's at any lag that survives a split-half check.

This confirms spec §8's ruling with evidence rather than assumption:

> Only propagation ("if L2 capex stops, what breaks and in what order")
> genuinely needs a graph, and **propagation needs edges we do not have**.

That was a judgment call when written. It is now a measurement. The node-link
graph stays cut, and `/industry_graph` stays a matrix.

## Why this supersedes Round 3's reasoning

`RETURNS-VERDICT.md` closed the ledger on a long/short that failed. Re-reading
the code, that test was narrower than its own verdict claimed: the signal was
`gamma * shock` where `shock` is **one scalar per month**, so it ranked
suppliers by `gamma` and merely *reversed* the sort in negative-shock months.
Its whole information content was the shock's sign; the magnitude was a monotone
scaling. It never measured a customer link, because a common shock cannot
generate a cross-section — it can only reorder one.

This round tests the underlying claim directly, on 79 quarters instead of 35
months, and reaches the same destination by a route that actually goes there.

## What is NOT retired

- **The clusters themselves.** Revenue clustering independently recovers a
  recognisable semi complex (AMAT, ASML, ACLS, AEHR, AEIS, AMKR, ADI, AAOI) with
  no taxonomy input. Capex clustering recovers nothing coherent — consistent
  with capex being lumpy and decision-driven while revenue is demand-driven.
- **The method.** Common-factor removal plus a domain null is reusable, and it
  is the first null in this study drawn from the data rather than a shuffle.
- **The question at a finer grain.** These are *chain* aggregates. A supplier
  with one dominant customer could still lead that customer, and nothing here
  tests it. That needs named customer relationships, which
  `project_fundamental_p4_concentration_dead` established do not exist in our
  sources.
