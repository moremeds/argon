# 03 — The Post-2022 Regime Break

This is the most consequential finding from the cross-validation work. The source article was synthesized from Andrew Ang's 2014 framework, which is grounded in data running through ~2012. **External analyses indicate that gold's tight negative correlation with real interest rates broke down in 2022 and has not returned.** The strength of that claim is large enough that any implementation must regime-gate the article's framework, even though the exact magnitude is **not yet internally replicated**.

---

## The data (external, not yet replicated)

**Rolling correlation between gold price and 10-year US real yield (DFII10), by sub-period — as reported externally:**

| Period | Gold ↔ 10Y real-yield correlation (external estimate) |
|---|---|
| 2005-2021 | ≈ **-0.84** |
| 2022-2023 | ≈ **-0.03** |
| 2024-present | ≈ **-0.07** |

Source: RBC Wealth Management 2024-2025 "Gold's regime change" analysis; corroborated by S&P Global, PIMCO, and World Gold Council 2025 reports.

**Caveats we must apply before treating this as a measurement rather than a clue:**

- The published statistic does not specify whether it is a price-level correlation or a return correlation.
- It does not specify whether the input is gold spot, LBMA fix, GLD, or futures.
- It does not specify whether the TIPS input is level or change.
- It does not specify frequency (daily / weekly / monthly) or window endpoint sensitivity.
- A level correlation through the 2005-2021 QE / disinflation / falling-real-yields macro environment can look spectacular without implying a stable trading relationship.
- A near-zero 2022-present correlation can be exaggerated by a short window with violent inflation and reserve-flow shocks.

The direction of the break is consistent with multiple independent industry sources and with the qualitative evidence (gold rallied while GLD/ETF holdings fell; CB buying stayed historically elevated; the marginal-buyer story changed after the 2022 reserve-freeze shock). The *magnitude* should not be quoted as our measured truth until we replicate it internally.

### Replication requirement (must happen before any production claim)

Before the dashboard or any spec ships the -0.84 / -0.07 numbers as headline statistics:

1. Compute Gold ↔ DFII10 correlation under **both** specifications: price level and log return, both directions.
2. Use rolling windows of **60d / 126d / 252d / 504d** and **expanding** windows.
3. Cross-validate across **gold spot, GLD, LBMA AM fix, and GC=F front-month** as gold inputs; **DFII10 level and DFII10 daily change** as real-yield inputs.
4. Run at least one **formal structural-break test** (Bai-Perron, Quandt-Andrews, or rolling Chow). The break date is a hypothesis to be tested, not assumed.
5. Compare against a **non-stationarity null**: is the pre-2022 period genuinely one stable regime, or one long non-stationary macro environment that happened to co-move?
6. Publish the resulting numbers in [02-empirical-claims-validation.md](./02-empirical-claims-validation.md) and update this file with our measurement.

Until that replication is complete, the dashboard should describe the gauge as **"correlation gauge"** rather than implying a peer-reviewed regime classification.

---

## What changed mechanically

The Feb 2022 freezing of approximately $300B of Russian foreign exchange reserves following the Ukraine invasion taught every non-aligned central bank that USD reserves carry sanction risk. Gold, by contrast, is non-confiscatable across sovereign jurisdictions.

The result, documented by the World Gold Council:

- **Central bank net purchases exceeded 1,000 tonnes** for three consecutive years (2022, 2023, 2024) — roughly double the 2010-2021 average of ~500 tonnes/yr
- **2025 came in at 863 tonnes** — slightly below the 1000+ pace but still historically elevated
- A WGC survey of ~60 central banks (Feb-Apr 2024): **95% expect global official gold reserves to rise** over the next 12 months (highest in 8 years of surveys); **43% plan to increase their own holdings** (record)
- Western institutional flows, historically tied to TIPS yield, **shrank as a share of marginal demand**

The composition of the marginal buyer flipped. Western institutional allocators became a smaller, sometimes net-selling share. EM central banks (China, India, Russia, Turkey, Poland, Singapore, Czechia, and others) became the dominant net-buyer cohort.

---

## My take on what the break means

**The framework is correct. The observable is wrong.**

The article's SDF reading says: gold is priced by its covariance with bad times; the stochastic discount factor M weighs bad-times returns highly; gold therefore earns a premium for paying off in bad states. That logic is intact post-2022. **What changed is whose M is doing the pricing.**

Pre-2022, the marginal buyer was a Western institutional allocator whose bad times correlate with real-rate declines (recession, equity drawdown, deflation scare). TIPS yield was the right observable for that pricing kernel.

Post-2022, the marginal buyer is an EM central bank whose bad times correlate with sanction risk and USD weaponization. **The SDF didn't disappear — it changed weights.** TIPS is the wrong observable for the new kernel; central bank purchase flows, GPR, and de-dollarization signals are the right ones.

This is not a "throw out the framework" finding. It is a "use a different proxy" finding.

---

## Why a reversal is unlikely in the near term (conditional on the break being real)

The trigger event — the Feb 2022 reserve freeze — was a one-way bell that cannot be unrung. Even if the Russia-Ukraine conflict resolves tomorrow, every non-aligned central bank now has a permanent revealed risk in USD reserves. China, India, Turkey, Saudi Arabia, Kazakhstan, and the rest of the diversifying-EM cohort are running multi-year programs that are not contingent on a single conflict.

**The structural buyer is here for years, not quarters.** A genuine reversal would require:

1. Central bank purchases falling to pre-2022 levels (<500t/yr)
2. Geopolitical de-escalation across multiple fronts
3. USD reserve-confidence rebuilding (currently no path visible)
4. Western institutional flows resuming (GLD/IAU holdings recovering)

We are seeing **partial deceleration** (the 2022-2024 1000+t pace fell to 863t in 2025 per WGC's FY2025 figures) but none of the structural conditions for genuine reversal. The prudent operating assumption is that the break is durable — though this is a working hypothesis, not a measured fact. The dashboard should remain capable of detecting reactivation rather than encoding the assumption permanently.

---

## The hidden risk: Erb-Harvey hasn't gone away

Erb-Harvey's "real price of gold mean reverts" finding is one of the most robust empirical results in the gold literature. The CPI-deflated gold price is currently at or near all-time highs. Their finding implies: at elevated real prices, subsequent real gold returns are below average.

The only thing keeping that mean reversion from biting right now is the structural bid from central bank buying. **If central bank buying decelerates further AND real prices stay elevated AND Western institutional flows don't snap back, gold could see a sharp correction with no immediate cyclical catalyst.**

This is the asymmetric risk worth surfacing on the dashboard. The dashboard's job is not to predict the direction; it is to make the tension legible.

See [07-valuation-overlay.md](./07-valuation-overlay.md) for the operational implementation of this overlay.

---

## What we monitor to detect reactivation

The pre-2022 framework would reactivate when **both** of the following conditions hold:

1. **Central bank net purchases below ~600 tonnes/year** (rolling 12-month). This is the empirical threshold where structural-buyer dominance becomes ambiguous. Tracked via WGC monthly data.
2. **Western ETF holdings recovering above their 2020 highs.** GLD held ~1,280t at the 2020 peak. Currently ~870t (mid-2024 trough). Above ~1,100t and rising would signal Western institutional return.

Until both conditions hold, the dashboard should treat the article's framework as suspended and base recommendations on Layer 1 (structural flow) rather than Layer 2 (cyclical).

A **single-trigger** version: if the 252-day rolling Gold ↔ DFII10 correlation returns to the `[-0.9, -0.5]` band and stays there for 60+ trading days, partially reactivate the article's framework with reduced weighting.

---

## Why the article missed it

The article's empirical case studies (1973-1980, 2011-2020, 2019-2020, 2021-2022) all sit inside the pre-2022 regime where the -84% correlation held. The 2021-2022 case is the closest the article comes to acknowledging the issue — it correctly notes that gold under-performed CPI during that window — but it attributes the underperformance to "real rate rising" without acknowledging that the response function itself was about to break.

The article also reads as a synthesis of Andrew Ang's 2014 framework, which is grounded in 2012-era data. The Russian reserve freeze is two years past Ang's data window. The article inherits Ang's blind spot.

---

## Implications for the implementation

**These belong in the spec:**

1. A **correlation gauge** as a top-level signal: rolling Gold ↔ DFII10 correlation across multiple windows (60d / 126d / 252d / 504d). Default display 252d. Color-coded *operative / partial / suspended* once thresholds are calibrated empirically.
2. The article's cyclical *posture* **gated on this gauge**. The cyclical-lens posture is informative only when the gauge is in the operative or partial band.
3. The article's tail-hedge B *posture* **kept active**, but with copy that acknowledges Baur-Lucey's 15-trading-day duration finding — and split conceptually into "strategic allocation context" and "event hedge context" (see [04-three-layer-architecture.md](./04-three-layer-architecture.md)).
4. **Lens 1 (structural flow) elevated as primary** posture description under suspended-gauge conditions. See [05-structural-flow-factors.md](./05-structural-flow-factors.md).
5. The dashboard's lead chart shows **GLD holdings overlaid on gold price 2020-present** — the cleanest single visualization of the apparent regime change.
6. **Internal replication of the correlation collapse**, with results published in [02-empirical-claims-validation.md](./02-empirical-claims-validation.md), before any production copy quotes the -0.84 / -0.07 numbers.

**These should not be in the spec (v1):**

1. Pooled-history regressions across the apparent 2022 break. They risk mixing two pricing-kernel regimes.
2. Numerical "position recommendations" while the gauge is suspended. Use *posture* language ("structural bid intact," "cyclical regime would be unanchored if framework operative") rather than sizing recommendations.
3. Confidence statements implying the article's framework is "the gold model." It is, at most, "the gold model for the previous regime, pending replication."
4. Quoting the RBC -0.84 / -0.07 figures as our measured statistics. Until replicated, attribute them to external analysis only.
