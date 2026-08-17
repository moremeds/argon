# VERDICT — the AI link looks like a one-quarter lead, and the control says don't believe it yet

> **SUPERSEDED the same day by [`ROUND2-matched-growth.md`](ROUND2-matched-growth.md).**
> Kept as the record of what the balanced-panel method measured, because the
> comparison between the two is itself the result. Three claims below did not
> survive:
>
> 1. **The L1 acceleration peak of 0.59 is half method artifact.** Matched-sample
>    growth over the *same 20 quarters* gives 0.25, and L0 flips from +0.20 to
>    −0.35. The balanced panel's all-quarters-present requirement selected on
>    survivorship and manufactured signal.
> 2. **"Longer history" was available all along** — 83 quarters, not 20. The
>    ceiling came from balancing, not from the data. With it, the semi control
>    *passes* (growth L0 0.549, t 5.76) over 2005–2026 but is dead in its second
>    half (−0.050), i.e. exactly where the AI claim lives.
> 3. **The circular limitation has a way around it after all.** Isolating
>    datacenter revenue is not the only route: a dose-response across asserted
>    purity needs no segment data. It was run, and it exposed the labelling — the
>    names called "pure" are the ones that **lead** capex rather than lag it, and
>    the aggregate had been averaging leaders against laggards the whole time.

*2026-08-13 · numbers in `capex_lead_lag.json` · reproduce:*

```bash
uv run python scripts/research/capex_demand_ledger.py
```

Balanced panels inside a trailing 20-quarter window; Pearson correlation of
buyer-capex growth against supplier-revenue growth at lags 0–4 quarters.
`acceleration` is the change in YoY growth — the version that removes the shared
sector trend both legs sit inside.

## The headline

| link | growth L0 | L1 | L2 | L3 | L4 | accel L0 | **L1** | L2 | L3 | L4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ai_datacenter** | 0.82 | **0.88** | 0.81 | 0.76 | 0.76 | 0.20 | **0.59** | 0.09 | −0.12 | −0.28 |
| datacenter_power | 0.35 | 0.67 | **0.78** | 0.78 | 0.62 | 0.53 | 0.53 | 0.14 | 0.40 | −0.26 |
| **semi_capex_cycle** *(control)* | 0.23 | 0.16 | −0.03 | −0.06 | −0.17 | −0.14 | 0.19 | −0.25 | −0.17 | −0.03 |
| **semi_wfe_only** *(control v2)* | 0.23 | 0.15 | −0.07 | −0.10 | −0.20 | −0.10 | 0.18 | −0.25 | −0.17 | −0.05 |

n runs 16 at lag 0 down to 11–12 at lag 4.

**`ai_datacenter` has the shape of a genuine one-quarter lead.** Acceleration
peaks sharply at L1 (0.59) and collapses either side of it (0.20, 0.09, −0.12,
−0.28). That single-peak shape is what a real lead looks like; a trend artifact
produces a flat or monotonically rising profile instead.

**Memory changed this result and its omission was a real error.** Before
`Memory/Storage` was added to the supplier leg, growth correlation rose
monotonically to L4 = 0.94 — the classic signature of two trending series, which
would have been over-read as a four-quarter lead. With memory included the
profile peaks at L1 and decays. Memory belongs on **both** sides of this ledger:
memory fabs are among the largest wafer-fab-equipment buyers, and HBM/SSD ships
into the same datacenters.

## The control fails, and that governs the verdict

`semi_capex_cycle` — foundry and memory capex driving wafer-fab-equipment revenue
— is a decades-documented relationship. The method does not reproduce it. Growth
correlation is 0.23 at lag 0 and goes **negative** from lag 2; acceleration is
indistinguishable from noise at every lag.

The control existed precisely so this could not be rationalised away, so it is
not being rationalised away. **The method is not validated, and `ai_datacenter`
has therefore not earned belief regardless of how clean its profile looks.**

One hypothesis was testable and was tested: `Semi-Cap/EDA` lumps EDA software
(CDNS, SNPS), IP licensing (ARM) and assembly/test (AMKR) — none of whose revenue
models track a fab's capex — beside the actual toolmakers. Removing all four
(`semi_wfe_only`) moved nothing: 0.2349 / 0.148 / −0.0683 against 0.2267 / 0.1591
/ −0.0343. **Contamination was not the explanation.**

The remaining hypothesis is **not testable with this universe**: WFE demand is
dominated by buyers that are not US-listed and therefore absent from every source
we have — Samsung, SK Hynix, Kioxia, SMIC, CXMT, YMTC. Our buyer leg is TSM,
INTC, MU and a few others. If a large majority of the demand is invisible, the
correlation is diluted by construction. That is a plausible reason the control
fails, but it stays a hypothesis: nothing here demonstrates it, and it must not
be used to license belief in the AI result.

The asymmetry that makes it plausible is worth stating: hyperscaler capex is
dominated by US-listed names (MSFT, AMZN, GOOGL, META, ORCL), so `ai_datacenter`'s
buyer leg is close to complete, where the semi control's is not.

## The circular limitation

The supplier leg uses **total revenue**, not datacenter revenue. `Computer/GPU`
carries HPQ and DELL consumer PCs; `Networking/Optical` carries CSCO enterprise;
`Memory/Storage` carries STX and WDC consumer drives. So the supplier leg is
diluted with business that has nothing to do with the buildout, which is visible
in the ratio band: 0.97–2.84 across 20 quarters for the 33-name supplier set,
against **0.469–0.571** for the single-name NVDA version in `RESULTS.md`.

Isolating the datacenter portion of supplier revenue is exactly what segment
disaggregation would provide — and segment shares are computable for only 77 of
257 names, with every relevant mega-cap in the failing set
(`2026-08-13-fundamental-segment-computability-wide/`). **The fix for this
ledger's weakest leg is the thing that already failed.** That circularity is the
most important structural finding here.

## Status

**Promising, not established. Do not build a feature on this.** What would move
it:

1. A control that the universe can actually support — the semi cycle cannot be
   one while most of its buyers are unlisted.
2. Longer history. 20 quarters is ~1.5 WFE cycles and n = 11–16 at the lags that
   matter; correlations at that n are weak evidence whichever way they point.
3. A way to isolate datacenter revenue in the supplier leg that does not depend
   on the segment data that failed.

## Not measured here

Whether any of this predicts **returns**. Every number above relates fundamentals
to fundamentals. The step from "capex leads revenue" to "this is tradable" is
untested, and inherits the lake's 653-symbol price coverage when it is attempted.
