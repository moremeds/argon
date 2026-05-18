# Gold SDF Framework — Research

**Status:** Pre-spec research. Cross-validation of the SDF-based gold framework (viviennaBTC article + Andrew Ang Ch. 11) against primary sources. **Do not implement until reviewed.**

**Started:** 2026-05-16
**Working directory:** `docs/research/gold-sdf-framework/`

---

## What this is

A research foundation for a Gold endpoint / dashboard / cockpit in this repo. The work cross-validates:

1. The article's SDF framework and three-regime taxonomy
2. The five academic references it cites
3. viviennaBTC's 8-factor model from the X.com post
4. Whether the article's framework still operates in the post-2022 gold market

Each finding lives in a focused sub-document so the body of work can grow without any single file becoming unwieldy.

---

## Three findings worth pinning

1. **The article's references are real and correctly attributed.** Ang (2014), Cochrane (2005), Erb-Harvey (2013), Baur-Lucey (2010), and Ang et al. (2006) all exist; the SDF derivations follow textbook Cochrane. Detail: [01-references-and-citations.md](./01-references-and-citations.md).

2. **The article's empirical claims are directionally correct but quantitatively imprecise** (e.g., Ang's actual gold-CPI correlation is 0.01, not the 0.08 the article cites). Detail: [02-empirical-claims-validation.md](./02-empirical-claims-validation.md).

3. **The article omits a post-2022 regime change.** External estimates (RBC Wealth Mgmt, S&P, PIMCO, WGC) report Gold ↔ 10Y real-yield correlation falling from roughly -0.84 (2005-2021) to near zero (2022-present). The exact magnitude is **not yet internally replicated** — it could be exaggerated by window endpoints, level-vs-return choices, or pre-2022 non-stationarity. The directional finding is strong enough to require regime-gating; the specific statistic should be treated as a clue, not a measurement, until we replicate it ourselves. Detail and replication plan: [03-post-2022-regime-break.md](./03-post-2022-regime-break.md).

---

## The synthesized framework

The implementation does not adopt the article as-stated. It builds a model organized into **three lenses (signal families)**, with the article's framework living inside the cyclical lens and gated on regime applicability. The lenses are *complementary*, **not orthogonal** — they share variance (e.g., central-bank flow overlaps with GPR and DXY; valuation is endogenous to flow). Position-sizing logic must assume correlated signals until variance accounting proves otherwise. Conceptual model: [04-three-layer-architecture.md](./04-three-layer-architecture.md). Operationalization as a quant model: [04a-quant-model-spec.md](./04a-quant-model-spec.md). Review-response notes: [CHANGELOG.md](./CHANGELOG.md).

```
Lens 1 — Structural-flow signals           [APPARENTLY DOMINANT 2022-present]
  • Per-country central bank reserves
  • ETF holdings (GLD, IAU, GLDM, PHYS)
  • Exchange inventories (COMEX, LBMA, SGE)
  • Local-currency gold pricing (CNY, INR, TRY, JPY)
  • CFTC COT positioning (managed-money / commercials)
  • UW options stress (GLD/GDX skew, dealer gamma) — persist v1, model v2

Lens 2 — Cyclical signals                  [GATED by regime gauge]
  • Article's two-force model
  • viviennaBTC's 8 factors (F1, F4, F5, F6, F10, F11, F13, F14)
  • DFII10, T5YIFR, CPIAUCSL

Lens 3 — Valuation overlay                 [ALWAYS-ON tail-risk flag, never a sizing input]
  • Erb-Harvey real-price-of-gold percentile
```

The lenses share variance. Position sizing should not double-count the same macro shock under different lens names.

---

## Reading map

| If you want to know… | Read |
|---|---|
| What this research concludes overall | this README |
| Which references are real and what they actually say | [01-references-and-citations.md](./01-references-and-citations.md) |
| Whether the article's specific numbers check out | [02-empirical-claims-validation.md](./02-empirical-claims-validation.md) |
| Why the article's framework is currently broken and what to do | [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) |
| The synthesized three-layer model | [04-three-layer-architecture.md](./04-three-layer-architecture.md) |
| How to operationalize the architecture as a quant model | [04a-quant-model-spec.md](./04a-quant-model-spec.md) |
| Layer 1 in depth (CB reserves, ETF, inventory, FX) | [05-structural-flow-factors.md](./05-structural-flow-factors.md) |
| Layer 2: the article's macro/cyclical factors | [06-cyclical-factors.md](./06-cyclical-factors.md) |
| Layer 3: valuation / mean-reversion overlay | [07-valuation-overlay.md](./07-valuation-overlay.md) |
| Honest read of viviennaBTC's 8-factor model | [08-viviennabtc-factor-critique.md](./08-viviennabtc-factor-critique.md) |
| What data feeds we'd need and what they cost | [09-data-sources-catalog.md](./09-data-sources-catalog.md) |
| What's still unresolved | [10-open-research-questions.md](./10-open-research-questions.md) |
| Phase A1 sources that need re-wiring in v2 | [11-deferred-sources-phase-a1.md](./11-deferred-sources-phase-a1.md) |
| Current live data-quality gaps and closure sequence | [14-data-quality-remediation.md](./14-data-quality-remediation.md) |

---

## Cost summary

Roughly **$0 in new external data costs.** All required series are either free (FRED, GPR, exchange inventory reports, ETF disclosures, WGC CB statistics) or already paid for in this repo (massive.com OHLC, UW options). The cost is engineering time, not data subscriptions.

**Phase A1 ingestion caveat (2026-05-17):** five of the eight anonymous-CSV sources designed for v1 had moved or paywalled by implementation time. See [11-deferred-sources-phase-a1.md](./11-deferred-sources-phase-a1.md) for the v2 re-wire plan (most-likely fix: lean on official APIs like Socrata/IMF/SEC N-PORT rather than scraping issuer pages).

**Live data-quality caveat (2026-05-18 HKG):** the local warm store now has GLD daily holdings, the WGC monthly ETF corpus, a canonical WGC view, and current + 400-day CFTC gold COT history. Latest posture is pinned to the latest GLD market date and known-bad 2026-05-17 posture rows are invalidated but retained for audit. Lens 1 is still degraded because central-bank reserves and COMEX remain unresolved. Treat the cockpit as a research/audit surface until the remaining checklist in [14-data-quality-remediation.md](./14-data-quality-remediation.md) is closed.

---

## What this directory is NOT

- It is **not** the implementation spec. A spec lives in `docs/superpowers/specs/` once we agree on direction.
- It is **not** a backtest. No model has been fit to data; all claims here come from primary academic sources, industry research, and direct review of the article.
- It is **not** complete. Sections marked **open** in [10-open-research-questions.md](./10-open-research-questions.md) are unresolved.
