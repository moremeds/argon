# Round 2 — the aggregate was averaging a leading group with a lagging one

*2026-08-13 · numbers in `capex_matched_growth{,_w20,_w28}.json` · reproduce:*

```bash
uv run python scripts/research/capex_matched_growth.py             # full history, 83q
uv run python scripts/research/capex_matched_growth.py --window=20 # isolates the window
uv run python scripts/research/capex_matched_growth.py --window=28 # robustness
```

Round 1 (`VERDICT.md`) reported a clean one-quarter lead on `ai_datacenter`
(acceleration L1 = 0.59) that a failing control refused to license. Round 2
changed two things about the method and both changed the answer.

## What changed

**Matched-sample growth replaces the balanced panel.** Aggregating *levels*
across tickers needs fixed membership or a ticker entering mid-series steps the
total for a non-economic reason. Aggregating *growth* does not: sum each quarter
only over tickers present in both `t` and `t−4`, and every quarter is measured
against its own matched base — the same-store-sales construction. Membership may
then change freely, so the 20-quarter ceiling disappears. **The store holds 83
quarters (2005 Q4 → 2026 Q2)** for AMAT, LRCX, KLAC, ASML, TSM, INTC and MU. The
window was never a data limit; it was the price of balancing.

**Lags are now two-sided.** Every earlier run tested `buyer[t]` against
`supplier[t+k]` for `k ≥ 0`, which assumes the direction it set out to measure.

## Finding 1 — half of the Round-1 peak was the aggregation, not the data

Same 20 quarters, same links, only the aggregation differs:

| | growth L1 | accel L0 | accel L1 |
|---|---:|---:|---:|
| balanced panel (Round 1) | 0.88 | +0.20 | **0.59** |
| matched growth (Round 2) | 0.56 | **−0.35** | **0.25** |

The acceleration peak more than halves and **L0 changes sign**. The balanced
panel kept only names present in all 20 quarters — a survivorship-selected set
of firms that existed and reported throughout the boom. That selection was
manufacturing signal. A result that flips sign under a defensible change of
aggregation is not a finding.

## Finding 2 — over full history the aggregate is nothing

`ai_datacenter` across all 83 quarters: growth L0 = 0.217 (t 1.95), L1 = 0.148;
acceleration L0 = 0.186, **L1 = 0.043**. The lead disappears. Split-half is weak
in both halves (accel L0: 0.304 first, 0.096 second).

## Finding 3 — the control passes, then expires

`semi_capex_cycle` over 83 quarters is textbook: growth L0 = 0.549 (t 5.76),
L1 = 0.567, decaying monotonically to L4 = 0.153; acceleration L0 = 0.284.
`semi_wfe_only` is the same or better (L0 = 0.581). **The Round-1 control failure
was entirely the 20-quarter window** — a semiconductor-capex control measured
inside a single AI boom has no downturn in it to detect and cannot fail
informatively.

But the split-half is brutal:

| | first half (≈2006–2015) | second half (≈2016–2026) |
|---|---:|---:|
| `semi_capex_cycle` growth L0 | **0.675** | **−0.050** |
| `semi_wfe_only` growth L0 | **0.702** | **−0.075** |

**The method demonstrably works in the period where it can be verified and
demonstrably stops working in the period where we want to use it.** That is
much sharper information than "the control failed", and it is bad news: the AI
claim lives entirely in the half where the control is dead.

A plausible reason remains untestable here — WFE demand shifted toward buyers
that are not US-listed (Samsung, SK Hynix, Kioxia, SMIC, CXMT, YMTC), so the
listed buyer leg stopped representing the demand. It stays a hypothesis and is
not used to license anything.

`utility_grid` — the control the Round-1 verdict asked for, both legs US-listed
(DUK/SO/D/AEP/EXC/ED spend, PWR/MTZ/EME/DY build), 83 quarters — **also fails**:
growth L0 = 0.189 then negative at every further lag, acceleration L1 = −0.30.

## Finding 4 — the dose-response failed because the purity assertion was wrong

Asserted pure-play (VRT, CRDO, ALAB, NVDA, ANET, SMCI) vs diluted (HPQ, DELL,
CSCO, ETN, MOD) over the same 20 quarters: pure growth L1 = **−0.29**, diluted
L1 = **+0.67**. Purity *reversed* the correlation instead of amplifying it.

Read as a test of the mechanism that is a falsification. The per-supplier table
says it is a falsification of my labelling. Sorted by correlation, the names that
actually track hyperscaler capex are the optical and connector complex — GLW
0.84, LITE 0.83, APH 0.77, FN, AAOI, CIEN — none of which I called pure. And the
names I called pure sit at the bottom because they **lead**, not because they are
uncorrelated.

## Finding 5 — what the aggregate was structurally unable to see

Two-sided per-supplier lag profiles, 52 suppliers, peak-lag distribution:

```
-4: 5   -2: 4   -1: 2   0: 2   +1: 9   +2: 7   +3: 8   +4: 15
```

Grouped by role in the buildout, median peak lag and median peak r:

| group | 20q window | 28q window |
|---|---|---|
| compute / memory (NVDA MU SMCI ALAB ARM AMD STX WDC SNDK) | **−1** @ +0.57 | **−1** @ +0.49 |
| optics / interconnect (GLW LITE APH AAOI CRDO FN CIEN TEL …) | **+2** @ +0.66 | **+2** @ +0.44 |
| servers / systems (DELL HPE HPQ CSCO NTAP PSTG VRT) | +1 @ +0.58 | −1 @ +0.24 |
| power / thermal / EPC (ETN NVT GEV ATKR AYI J DY MTZ …) | +3 @ +0.46 | −2 @ +0.16 |

NVDA peaks at **lag −4 with r = +0.72** — the single strongest relationship in
the table, and it points the *other way*: NVDA's revenue growth leads hyperscaler
capex growth by a year. MU peaks at −2 (+0.77).

**This is why every aggregate came out near zero.** Summing a group that leads by
1–4 quarters with a group that lags by 1–4 quarters averages a lead against a lag.
The aggregate was not measuring a weak relationship; it was measuring the mean of
two opposite ones.

The mechanism is ordinary once stated: chips are ordered, shipped and revenue-
recognised before the datacenter that houses them is built and capitalised, while
optics, switchgear and cooling are installed as the shells come up. External
reporting is consistent with the tail of this — optical transceivers and fiber
entered extended lead-time categories from mid-2025, high-voltage transformers,
switchgear and generators run 12–18+ months, and there is a ~150-day lag from
roof completion to operational.

## What survives, and what does not

**Survives:** compute/memory leads (−1) and optics/interconnect lags (+2). Both
group medians are identical across the 20q and 28q windows and both carry the
strongest correlations in the table.

**Does not survive:** the power/thermal/EPC and server stages. Their peak lags
flip sign between windows (+3 → −2, +1 → −1) and their peak r collapses
(0.46 → 0.16, 0.58 → 0.24). The argmax of a weak correlation is the argmax of
noise. The four-stage sequence is *not* established — only the two-stage one.

**Caveats that bound all of it:**

1. **Multiple testing is severe.** 52 suppliers × 9 lags = 468 correlations. The
   extremes of that many draws look impressive by construction.
2. **Per-ticker peak lag is unstable** — exact agreement between the 20q and 28q
   windows is 15/52, within-one 24/52, rank correlation 0.467. Only the *group*
   medians are stable, and aggregation smoothing is an alternative explanation
   for that which this probe does not rule out.
3. **Still no returns test.** Every number here relates fundamentals to
   fundamentals.
4. `t` is inflated throughout: quarterly YoY overlaps four quarters, so effective
   n is well below nominal n. Sort with it; do not test with it.

## Round 2b — the whole chain, software included

The ledger is a supply-chain claim, so it has to cover the chain. All 18 layers,
201 tickers, summarised by the **median r across each layer's names at each lag**
— not by the median of per-ticker argmax lags, because the argmax of a weak
correlation is the argmax of noise, which is how the power/EPC "stage" survived
into the section above before the window check killed it. This estimator lets a
layer with no relationship show a flat profile and a low peak.

It also closed a real coverage gap: `Semi-Logic/ASIC` (AVGO, MRVL) was in no
earlier run at all.

| layer | n | best lag | median r | | layer | n | best lag | median r |
|---|--:|--:|--:|---|---|--:|--:|--:|
| upstream tools | 19 | +2 | +0.32 | | data platform | 8 | +4 | +0.10 |
| foundry | 6 | +3 | +0.36 | | ai-native sw | 6 | −4 | +0.11 |
| compute silicon | 26 | +3 | +0.41 | | devtools | 5 | +4 | **−0.11** |
| memory | 6 | +2 | +0.42 | | saas broad | 13 | +4 | +0.21 |
| **interconnect** | 15 | **+2** | **+0.56** | | security | 13 | +3 | **−0.07** |
| systems/OEM | 5 | +0 | +0.42 | | apps/consumer | 12 | +4 | +0.11 |
| facility | 24 | +4 | +0.43 | | it services | 7 | +3 | +0.32 |
| generation | 13 | +2 | +0.26 | | applied/robotics | 14 | +3 | +0.25 |
| colo/REIT | 4 | +4 | +0.46 | | | | | |

**Hardware median best-r +0.417 across 9 layers / 118 tickers; software +0.113
across 8 layers / 83 tickers. Gap +0.304.** The intuition that the software
connection is much weaker than the hardware one is correct by a factor of ~3.7.

**But the reason is not attenuation down the chain.** Every weak software layer
has the same profile shape: strongly negative at lag −4 and rising almost
monotonically to roughly zero at +4 — security −0.74 → −0.08, devtools −0.69 →
−0.11, data platform −0.67 → +0.10, IT services −0.56 → +0.29. Five of eight
software layers rise near-monotonically across the whole lag range. That is the
signature of **two series trending in opposite directions**: the 2022–23 SaaS
growth derating against accelerating capex. It is an artifact with a sign, not an
attenuated signal. Adding the 2020–21 SaaS boom back (the 28q window) neutralises
it — only 1 of 8 layers stays monotone.

**And the same window check damages the hardware side too.** Extending by eight
quarters: interconnect 0.56 → 0.18, compute silicon 0.41 → 0.19, facility +4
@ 0.43 → −0.32 at +2, and the hardware-vs-software gap collapses from **+0.304
to +0.085**. What looked like a buildout sequence is substantially "everything AI
hardware rose together between 2022 and 2026".

### The circularity that was nearly a finding

`Foundation-Model-Proxy` is **AMZN, GOOGL, META, MSFT, NVDA** — four of the five
*are* the buyer leg. Its apparent "−2 @ +0.45, the only software layer that leads
capex" was the buyers' revenue correlated against the buyers' own capex. It is
relabelled `9 CTRL buyers-self` and excluded from the comparison above (removing
it moves the software median 0.114 → 0.113).

As a control it earns its place, because it is consistent where nothing else is:
best lag **−2 (20q) and −3 (28q)**. Hyperscaler capex *follows* hyperscaler
revenue by two to three quarters, which is the right causal order — spend follows
demand. The consequence for this whole ledger is unwelcome: **reported capex is
doubly stale.** It lags the buyers' own business by 2–3 quarters, and then lags
again by the reporting delay. Anything built on it is reading a variable the
market saw twice already.

## Two things the external literature contributes

**The returns version of this is a documented anomaly.** Cohen & Frazzini,
*Economic Links and Predictable Returns* (Journal of Finance, 2008), find that
buying a supplier after a positive shock to its customer earns large predictable
returns, surviving the three-factor model, liquidity, own-firm momentum, industry
momentum and within-industry lead-lag. The mechanism is limited investor
attention to economically linked firms. Their shock variable is the **customer's
stock return**, not the customer's capex — and returns are forward-looking where
reported capex is backward-looking. That difference is a design instruction.

**The buyer leg carries a known negative return signal.** Titman, Wei & Xie
(2004) and Cooper, Gulen & Schill (2008) document that high abnormal capital
investment and high asset growth predict *lower* subsequent returns — one of the
most replicated cross-sectional effects there is. Any long/short built on this
ledger inherits that: the capex-ramping buyers are on the wrong side of the
asset-growth anomaly, which argues for long the lagging suppliers rather than
long the buyers.

## Sources

- [Cohen & Frazzini, Economic Links and Predictable Returns, JF 2008](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01379.x) ([working paper PDF](http://www.econ.yale.edu/~shiller/behfin/2006-04/cohen-frazzini.pdf))
- [Cooper, Gulen & Schill, Asset Growth and the Cross-Section of Stock Returns, JF 2008](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01370.x)
- [Accuris — AI data center electronic component supply, 2026](https://accuristech.com/blog/ai-data-center-electronic-component-supply/)
- [Epoch AI — build times for gigawatt-scale data centers](https://epoch.ai/data-insights/data-centers-buildout-speeds)
