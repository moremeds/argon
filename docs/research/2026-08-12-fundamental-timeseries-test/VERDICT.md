# VERDICT — a name's own fundamental deterioration does NOT precede its own drawdown

*2026-08-12 · hand-written · numbers in `timeseries.json` / `results.md` · reproduce:*

```bash
uv run python scripts/research/fundamental_timeseries_test.py
```

250 tickers · 16,857 scored observations · statements read from
`uw_scan.fundamental_statement_obs`, prices from the local lake mirror.

## The headline

**Null, and powered.** Across every market-neutral test the within-ticker
composite carries no information about that ticker's own forward return or
forward drawdown. The purest reading is `change|ret_2q_dm`: **IC −0.0000,
t −0.00**. That is not a weak result, it is the absence of one.

This is the question the product actually rests on, and it now has an answer.

| | cross-sectional (2026-08-11) | time-series (this) |
|---|---|---|
| question | does the composite order 245 names against each other? | does a name's own composite time that name? |
| answer | **yes** — IC 0.039 leak-free, t 2.67 | **no** — IC ~0.00, market-neutral |
| needs a wide panel? | yes, and that was the binding constraint | **no** — works at any width, including 25 |

**The composite ranks names. It does not time one.** Those are different claims
and the same number supports only the first.

## Why the raw numbers look like a finding, and are not

Read the raw column alone and there is an apparently strong result:
`level|ret_2q` at **IC −0.0396, t −3.41**, surviving even Bonferroni. It says a
name looking fundamentally strong versus its own history is followed by *weaker*
returns.

De-market it — subtract the mean outcome across all names sharing the knowledge
quarter — and it collapses to **−0.0047, t −0.41**. An 88% reduction. The entire
raw effect is the common factor: fundamentals across the panel peak late in a
cycle, and the panel then underperforms. Nothing about it distinguishes one name
from another, which is the only thing a per-ticker card could act on.

**That surviving raw t-stat is also not trustworthy on its own terms.** Its unit
of observation is the ticker, and 250 tickers exposed to one shared macro path
are not 250 independent observations of it — they are 250 views of one series.
The de-marketed residuals are close to independent; the raw ones are not. This
test can say the raw effect is common-factor, and cannot size its significance.
Anyone wanting the market-timing claim must test it as a time series of quarters,
where n is ~80, not 250.

## Multiple comparisons, applied before reading

16 hypotheses (2 signals × 2 horizons × 4 outcomes) on one dataset. At α 0.05
that is ~0.8 false positives expected before any real effect exists, so the
correction is computed in the script and persisted in the artifact rather than
left to the reader.

| result | t | p | BH | Bonferroni |
|---|---:|---:|---|---|
| `level\|ret_2q` (raw) | −3.41 | 0.0006 | pass | pass |
| `change\|ret_2q` (raw) | −3.04 | 0.0023 | pass | pass |
| `level\|ret_1q` (raw) | −2.61 | 0.0091 | pass | — |
| `level\|dd_1q_dm` | +2.34 | 0.0191 | **—** | — |
| every other market-neutral test | ≤1.61 | ≥0.106 | — | — |

**Every survivor is raw. Every market-neutral test fails.** `level|dd_1q_dm` at
t 2.34 is the one that would have been reported as a finding without this
correction — it is exactly the ~1 false positive 16 tests are expected to
produce, its 2q counterpart is half its size (t 1.51), and it does not survive.

## This is a powered null, which is the part that makes it usable

Revision 1 of the cross-sectional verdict declared a null without asking what its
test could detect, and was wrong — its floor was |IC| 0.072 against real factors
of 0.02–0.05, so it had measured nothing. Not repeating that:

| market-neutral test | measured IC | detection floor |
|---|---:|---:|
| `level\|ret_1q_dm` | +0.0032 | 0.0180 |
| `change\|ret_1q_dm` | +0.0048 | 0.0187 |
| `level\|ret_2q_dm` | −0.0047 | 0.0229 |
| `change\|ret_2q_dm` | −0.0000 | 0.0222 |
| *(4 drawdown variants)* | +0.0093…+0.0258 | 0.0186…0.0232 |

All eight floors sit at **0.018–0.023**, comfortably under the **0.039** the same
composite produces cross-sectionally. If an effect of the size that demonstrably
exists across names also existed within a name, this test would have found it.
It is absent, not merely unproven.

## What this changes for the product

1. **The card must not claim that deteriorating fundamentals predict weakness in
   that name.** No trend arrow implying a price consequence, no "fundamentals
   rolling over → expect underperformance", no invalidation level derived from a
   subscore trajectory. The inference is measured absent at a horizon the card
   would speak to.
2. **Subscore trends stay — as description, not prediction.** "Gross margin has
   fallen four quarters running" is a true, citable, auditable fact about the
   business and belongs on the card. What may not follow is a price claim.
3. **The ranked screen is unaffected and remains the one validated surface.** Its
   evidence is cross-sectional and this test does not touch it.
4. **The narrative prompt needs a constraint.** A model handed falling subscores
   will reach for "and so the stock should underperform" unprompted, because that
   is the shape of the prose it was trained on. The stage-5 schema should forbid
   a price claim sourced from a subscore trend, and the deterministic auditor
   should fail one.
5. **This closes the cheapest open question on the board and cost no ingest.** It
   also removes an assumption I had been carrying implicitly through three
   revisions of the design without ever testing it.

## What this is NOT

1. **Not evidence fundamentals are useless.** It is evidence about one
   construction — an equal-weighted 7-feature composite, expanding within-ticker
   z-scores, 1–2 quarter horizons. A different weighting, a longer horizon, or a
   threshold effect (only *large* deteriorations matter) could all differ, and
   none were tested.
2. **Not a test of extremes.** Rank correlation asks whether the ordering holds
   across the whole range. A signal that only fires in the worst decile would be
   nearly invisible to it. That is the most promising follow-up and it is cheap.
3. **Not survivorship-free.** Same limitation as everything else built on these
   sources — and here the bias runs *against* the null: names that actually
   deteriorated into bankruptcy are the ones missing from the panel. The true
   effect could be stronger than measured, which is the one honest argument for
   the follow-up in (2).
4. **Not out-of-regime.** Same single quality-led window as the cross-sectional
   work.
5. **Prices are stale** — the local mirror's last bars run 2026-04-14 to
   2026-05-29, so the most recent quarters carry no forward window and drop out.

## What would change the verdict

- **A threshold/extremes test** — does the worst decile of within-ticker
  deterioration precede drawdown, even though the full ordering does not? Cheap,
  local, and the one place survivorship argues an effect could be hiding.
- **A longer horizon.** Fundamental deterioration playing out over 4–8 quarters
  rather than 1–2 is a coherent prior that this test did not cover.
- **Delisted names.** The bankruptcies are exactly the observations that would
  carry this signal, and they are structurally absent.
