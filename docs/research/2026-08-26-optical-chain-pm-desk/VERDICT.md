# Optical-Communication chain — the PM view

**Date:** 2026-08-26 · **Universe:** 16 names, 5 layers · **Vendor calls:** 0 (warm store only)

**Reproduce:**

```bash
bash scripts/prod_pull.sh      # pull from the MINI (prod). The local dev DB lags months.
python3 scripts/build.py       # aggregate; prints every table in this document
python3 scripts/page_data.py   # assemble dataset.json
```

`dataset.json` is the full result set the page renders.

---

## What this replaced

The previous page led with a four-dimension composite score and a rotatable 3-D
taxonomy. Neither survives contact with a fundamental PM: the composite
correlates **+0.89 with its own growth input alone**, and no PM rotates a
taxonomy. Meanwhile the store held twenty years of quarterly income statements,
balance sheets and cash-flow statements that the page never touched.

This page shows the filings instead, organised as the seven questions a PM asks
in order.

## Findings

### 1. Demand is accelerating, not merely large

Combined capex of the five hyperscale buyers (AMZN, GOOGL, META, MSFT, ORCL):

| quarter | capex | YoY |
|---|---|---|
| 2024Q1 | $46.0b | +26% |
| 2025Q2 | $97.3b | +75% |
| 2026Q1 | $148.4b | +91% |
| 2026Q2 | **$181.5b** | **+87%** |

Nine consecutive quarters above +55%. **Validation:** calendar-2024 sums
reproduce Alphabet's reported $52.5b and Meta's reported $37.3b exactly.

### 2. The gradient runs upstream

Matched-sample revenue growth, 2026Q2: Components **+54%**, Modules **+51%**,
Systems +38% (ANET only). Every layer grows more slowly than the capex funding
it — the chain captures a shrinking share of a fast-growing pool.

### 3. Margin is expanding where margin was lowest

Revenue-weighted gross margin, six quarters:

| layer | 2025Q1 | 2026Q2 | change |
|---|---|---|---|
| Components | 33.7% | **40.6%** | +6.9pp |
| Modules | 27.0% | **32.4%** | +5.4pp |
| DSP / switch silicon | 66.1% | 65.8% | −0.3pp |
| Systems | 61.3% | 62.9% | +1.6pp |

The two commodity layers gained; the two already earning 60%+ did not. That is
the signature of **shortage**, not of mix — and it is the part of the cycle that
reverses first.

### 4. The flag: inventory is outrunning revenue

2026Q2, inventory YoY against revenue YoY, matched sample:

| layer | inventory | revenue | gap |
|---|---|---|---|
| Components | +74% | +54% | **+20pp** |
| DSP / switch silicon (2026Q1) | +88% | +47% | **+41pp** |
| Modules | +74% | +51% | **+23pp** |
| Systems | +23% | +38% | −15pp |

Four quarters ago every one of these was negative. **Stocking ahead of a ramp
and the first quarter of a build the end market will not take are
indistinguishable in this data.** Six of sixteen names carry the same divergence
individually.

### 5. It is fully marked

Own-history valuation yield percentile (low = expensive). **9 of the 12 names
with sufficient history sit at or below the 20th percentile**: GOOGL 0.00,
MSFT 0.00, NTAP 0.00, ANET 0.05, CIEN 0.05, COHR 0.10, AVGO 0.15, FN 0.20,
META 0.20. Only MRVL and ORCL (0.55) are mid-range.

### 6. The next eight days settle it

Six names report by 2026-09-08 — the whole DSP/switch layer (MRVL 08-27,
CRDO 09-01, AVGO 09-02) and two of three systems names (NTAP 09-02,
CIEN 09-03). These are exactly the layers blank in the 2026Q2 row.

## Data-integrity findings

**Vendor restatements are real and the read path must order by vintage.**
COHR 2026-06-30 capex was published as **$104,397,844,000** on 08-19 and
corrected to **$555,681,000** on 08-23 — a 188× error. Content-hash identity
preserved both as separate rows; any reader not taking the newest `obs_id` per
`(ticker, period, statement)` serves the corrected-away number. Prevalence is
low (7 of 480 cells carry two versions) and revenue never disagreed.

**The cash-flow statement does not reconcile everywhere.** Net income agrees
between the income statement and the cash-flow statement in **140 of 155**
quarters since 2024 (90.3%). COHR accounts for 5 of the 15 breaks, the worst
being 2026-06-30 ($240.5m against $595.0m). **No free-cash-flow figure appears
on the page** as a consequence.

**Local dev DB is unusable for this analysis.** Prod valuation anchors carry
`as_of 2026-08-21`; the local copy carried 2026-04-14/2026-05-15 — three to four
months stale, with `spot` prices to match. Every number here comes from the mini.

## Method notes

- **Fiscal→calendar mapping uses the quarter's MIDPOINT** (`period_end − 45d`),
  not its end date. AVGO's Feb–Apr quarter has its midpoint in mid-March and is
  calendar Q1; mapping on the end date pushes every off-calendar filer one
  quarter forward and manufactures a lead that is not in the data.
- **Growth is matched-sample** — a layer compares only names reporting in both
  the quarter and the year-ago quarter. Fixed composition drops the whole
  quarter when one member's calendar misses; a balanced panel selects on
  survivorship.
- **A layer margin is combined gross profit over combined revenue**, never the
  mean of member margins.
- Layer counts (`n`) travel with every aggregate, so a one-name "layer" is
  visible as one name.

## What this does not support

1. No forward information has been demonstrated at layer level. The gradient is
   an accounting fact about nine past quarters; no lead time is quoted.
2. Only 4 of 16 names disclose a segment we can attach a revenue share to, and
   one (CIEN, 1.5%) is its smallest segment while the same filing discloses an
   optical line near 70%. Chain position is semantic, never an exposure.
3. The composite score is deliberately absent (see "What this replaced").
4. `company_type` routing sends most of these names to `power_infra` /
   `ebitda_to_ev` — an artefact of the argon-chain sector vocabulary, not a
   claim that AAOI is a utility. The percentile is still own-history and valid;
   the label is wrong and is not shown.

## Provenance caveat (added at commit time, 2026-08-27)

`scripts/page_data.py` imports an `alldata.json` that was never committed and is
unreconstructable — it was the sole source of the published artifact's earnings
calendar, implied moves, and reaction history. Those inputs are being given a
durable, jobs-fed home by the fundamentals data spine
(`docs/superpowers/specs/2026-08-26-fundamentals-industry-desk-design.md` §5);
this dir is committed as-is for archaeological recoverability, not as a working
pipeline. `prod_pull.sh` + `build.py` + `dataset.json` remain reproducible.
