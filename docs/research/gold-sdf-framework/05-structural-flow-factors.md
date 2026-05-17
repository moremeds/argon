# 05 — Structural-Flow Factors (Layer 1)

The dominant layer of the framework since 2022. Captures the structural-buyer dynamic that the article's macro-only framework omits. Four factor classes, each with a different time signature and signal character.

---

## Why this layer exists

The post-2022 regime break (see [03-post-2022-regime-break.md](./03-post-2022-regime-break.md)) shifted the marginal gold buyer from Western institutional allocators (whose flows tracked real rates) to EM central banks and physical-demand markets (whose flows track entirely different variables). The article's framework has no signals for this new dominant buyer. This layer fills that gap with four factor classes:

1. **Per-country central bank reserves** — the engine of the structural bid
2. **ETF holdings** — the regime-identification signal (Western institutional flow)
3. **Exchange inventories** — physical demand and arbitrage detection
4. **Local-currency gold pricing** — regional retail and CB pressure detection

---

## 1. Per-country central bank reserves

### Why disaggregation matters

Aggregate "central bank purchases" hides the signal. Different countries buy gold for different reasons, and those reasons map to different states of the world. A spike in Chinese reserves is a different event from a spike in Polish reserves. The right operational frame is to classify buyers into behaviorally distinct buckets:

| Bucket | Examples | Behavior | What rising holdings signals |
|---|---|---|---|
| **Strategic accumulators** | China, India, Russia, Turkey | Multi-year programs; opaque reporting; large absolute amounts | Permanent de-dollarization; engine of post-2022 demand |
| **Tactical defenders** | Egypt, Kazakhstan, Azerbaijan | Buy on weakness; occasionally sell to defend currency | Currency-stress indicator (cross-references local-currency gold prices below) |
| **Reserve diversifiers** | Poland, Czechia, Singapore, Hungary | Smaller, policy-driven moves | Sentiment indicator for the "rest of the world" diversification trend |

### Data source

**World Gold Council "Monthly central bank gold statistics"**, sourced from IMF IFS. Free CSV from goldhub.com. ~1-month publication lag. Covers ~100 countries.

### Caveats

- **Russia** stopped reporting late 2022. Recent Russian gold holdings are estimated by industry; figures are uncertain by 100-200 tonnes.
- **China** reports irregularly and is widely believed to under-report. PBoC official figures suggest ~2,200 tonnes; industry estimates (using import/export data, jewelry/coin flows, mining production) suggest 3,000-5,000 tonnes. See [10-open-research-questions.md](./10-open-research-questions.md) Q7 for the handling decision.
- **Singapore** historically reports official holdings only; its broader sovereign wealth gold exposure (e.g., GIC, Temasek) is not in this series.

### Signal construction

For each country and bucket:
- 1-month reserve change (tonnes)
- 12-month rolling sum (tonnes)
- 12-month rolling sum vs same-month prior-year (delta)

Aggregate by bucket and globally. The 12-month rolling **strategic accumulator** sum is the cleanest single number for "is the structural bid still active."

**Threshold the post-2022-break article in [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) cites:** below ~600 tonnes/year aggregate would indicate the structural-buyer regime is fading.

---

## 2. ETF holdings

### Why this layer needs ETF data

Gold-backed ETF holdings are the cleanest daily-frequency proxy for Western institutional demand. They are the **regime-identification signal**: when ETF flow direction diverges from gold price direction, the marginal buyer is elsewhere.

The 2022-2024 data is the cleanest evidence on record of the regime change:
- GLD held ~1,280 tonnes at the 2020 peak
- GLD bled down to ~870 tonnes by mid-2024
- **Gold price hit all-time highs during the same period**

ETF holdings falling while gold rises = the buyer is not Western institutional. The combination of these two charts on one panel is the dashboard's lead visualization.

### The 2×2 regime classifier from ETF flow direction × gold price direction

| ETF holdings | Gold price | Reading |
|---|---|---|
| Inflowing | Rising | Old regime — Western institutional bid (pre-2022 pattern) |
| **Outflowing** | **Rising** | **Current regime — structural CB bid dominant** |
| Inflowing | Falling | Sentiment exhaustion |
| Outflowing | Falling | No-bid environment / liquidation |

### Data sources

| ETF | Sponsor | Format | URL |
|---|---|---|---|
| **GLD** (SPDR Gold Shares) | State Street | Daily CSV, tonnes + NAV + shares | spdrgoldshares.com/usa/historical-data |
| **IAU** (iShares Gold Trust) | BlackRock | Daily, on iShares IR page | ishares.com |
| **GLDM** (SPDR Gold MiniShares) | State Street | Daily, same SPDR site | spdrgoldshares.com |
| **PHYS** (Sprott Physical Gold) | Sprott | Daily, Sprott IR | sprott.com |
| **Global aggregate** | WGC | Weekly, all funds | gold.org/goldhub |

PHYS is interesting separately because it is **allocated physical** (specific bars in known vaults), unlike GLD which is unallocated. Premium/discount to NAV is a sentiment indicator distinct from holdings.

### Signal construction

Per ETF:
- Daily holdings (tonnes)
- 30-day net flow
- Year-to-date net flow

Cross-ETF aggregate:
- GLD + IAU + GLDM weekly net flow (Western-listed major gold ETFs)
- WGC weekly global aggregate (broader cohort)

The **30-day net flow vs gold price** on one chart is the regime gauge in visual form.

---

## 3. Exchange inventories

### Why inventory matters

Inventory data is one of the cleanest commodity signals that exists. Exchange vault levels reveal where physical metal is moving, which precedes price moves the macro factors don't predict. The Q1 2024 COMEX vault build (eligible inventory ~17M oz → ~28M oz in weeks) was driven by **LBMA bars being airfreighted to NY** ahead of feared US tariffs on gold imports. No macro factor predicted this. A registered-inventory gauge would have caught it.

### Four exchanges considered

| Exchange | What it tracks | Frequency | Source | Inclusion |
|---|---|---|---|---|
| **COMEX (CME)** | NY futures vault: eligible + registered | Daily | CME free daily reports | ✅ v1 |
| **LBMA** | London OTC vaults (loco London) | Monthly | LBMA free vault report | ✅ v1 |
| **SGE (Shanghai Gold Exchange)** | Chinese physical OTC delivery + inventory | Daily, Chinese-language | SGE Chinese-language website | v2 (scraping cost) |
| **SHFE (Shanghai Futures Exchange)** | Chinese futures positioning | Daily | SHFE site | Skip — speculative, not physical |
| **ICE** | Not dominant for gold | — | — | Skip |

**Decision:** v1 covers COMEX + LBMA. SGE is deferred to v2 because it requires Chinese-language scraping for marginal incremental signal beyond what per-country CB reserves and XAU/CNY already capture.

### Four-quadrant inventory regime

| COMEX registered | LBMA vault | Reading |
|---|---|---|
| Falling | Falling | Strong physical demand globally — bullish |
| **Falling** | **Rising** | **Geographic repositioning** (NY pulling from London) — happened Q1 2024 |
| Rising | Falling | NY-specific buying (often arbitrage) |
| Rising | Rising | Supply easing / weak physical demand — bearish |

The cross-exchange flow indicator (LBMA-to-COMEX repositioning) is a distinctive signal that none of the macro models capture.

### Signal construction

- COMEX: daily registered ounces, eligible ounces, total stocks
- LBMA: monthly loco London ounces (with timing-lag annotation)
- Derived: weekly LBMA-COMEX delta (proxy for repositioning)

---

## 4. Local-currency gold pricing

### Why this isn't redundant with DXY

The first instinct is that XAU/local-currency just inverts to DXY and adds nothing. This is broadly true for major-currency pairs (EUR, GBP, CHF) — they comove tightly with DXY against gold. But for non-DXY-basket emerging currencies, local-currency gold reveals regional demand that USD-quoted gold conceals.

| Pair | Signal value | Why |
|---|---|---|
| **XAU/EUR** | Low | Redundant with DXY/DTWEXBGS |
| **XAU/JPY** | High | BoJ's policy creates a unique "negative real yield in JPY" environment; XAU/JPY captures this without going through TIPS |
| **XAU/CNY** | High | Chinese retail demand pressure shows up here before USD-gold; Shanghai-London premium expresses Chinese mainland tightness |
| **XAU/INR** | High | India is a structural physical buyer; wedding-season demand pulses appear in XAU/INR first |
| **XAU/TRY** | High | Turkish lira instability translates directly into retail gold demand; TRY weakness *creates* buying |

### One thesis to correct

The original thesis behind including these pairs was "countries sell gold to defend their own currency." Empirically, this is mostly historical. The Central Bank Gold Agreement (1999-2019) capped European CB gold sales; post-CBGA, Eurosystem CBs are net flat-to-buyers. The few recent examples of CBs selling gold to defend currency (e.g., certain CEE central banks during 2008) used BIS gold swaps for short-term USD liquidity, not outright sales.

**The more useful angle** is that local-currency gold prices reveal **regional buying pressure**: where in the world is gold-in-local-terms expensive enough to drive physical demand, retail flows, or central bank tactical buying. The four pairs above capture this for the largest regional gold-demand markets.

### Data source

Compute from FRED FX series crossed with COMEX gold settlement (or LBMA fix):
- DEXCHUS (CNY/USD)
- DEXINUS (INR/USD)
- DEXJPUS (JPY/USD)
- DEXTRUS — not in FRED; use BIS or compute from TCMB-published rates

Local-currency gold price = (USD gold price) / (USD per local-currency unit).

### Signal construction

Per pair:
- Local-currency spot
- Year-over-year change
- Distance from 52-week high
- Premium vs USD-gold pricing (informational)

---

## How the four factor classes interact

The four factor classes are not independent. Some configurations have well-known interactions:

- **CB strategic accumulator buying + GLD outflows simultaneously** = the post-2022 archetype regime. Surface this combo prominently.
- **CB tactical defender buying + XAU/local-currency spiking** = currency stress (e.g., Turkey 2018, Egypt 2022). Both factor classes confirm the same story.
- **COMEX-LBMA repositioning + GLD inflows** = institutional buying with physical confirmation. Pre-2022 archetype regime.
- **CB buying decelerating + GLD outflows continuing + valuation overlay (Layer 3) flagging high real prices** = the Erb-Harvey mean-reversion risk window. The asymmetric drawdown setup.

The dashboard's "structural posture" line should describe which of these regimes the current factor configuration matches.

---

## Implementation cost estimate

| Component | New ingestor needed? | Data cost | Engineering days |
|---|---|---|---|
| WGC monthly CB reserves | Yes (CSV download) | $0 | 1-2 |
| GLD/IAU/GLDM/PHYS daily holdings | Yes (4 ingestors, mostly similar pattern) | $0 | 2-3 |
| COMEX vault stocks (daily) | Yes (CME report scraper or JSON API) | $0 | 1-2 |
| LBMA vault (monthly) | Yes (CSV download) | $0 | 0.5-1 |
| Local-currency FX (CNY, INR, JPY) | Extend FRED client | $0 | 0.5 |
| Local-currency FX (TRY) | Additional source (BIS or TCMB) | $0 | 1 |
| **Total Layer 1 v1** | | **$0** | **~6-10 days** |

SGE physical deferred to v2 adds ~3-5 days for Chinese-language scraping.
