# Trade Insights — UW endpoint research

**Date:** 2026-05-13
**Status:** Research draft (pre-implementation)
**Companion docs:**
- Design: `docs/superpowers/specs/2026-05-13-trade-insights-tab-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-trade-insights-tab.md`
- UW API surface: `docs/uw-samples/unusual_whales_api.md`, `docs/uw-samples/unusual_whales_api_spec.yaml`

## 0. Purpose

The current UW integration calls 18 endpoints (see `src/uw_scan/api/endpoints.py`). The full UW surface contains roughly twice that. This document audits the gap, groups un-tapped endpoints into four tiers by expected research value, and verifies each tier against the academic + practitioner literature so we know *which signals are worth the implementation cost*.

**Scope of evidence rigor:** mixed — peer-reviewed where it exists, practitioner sources (SqueezeMetrics, Bloomberg, dealer notes) where academia lags. Citations are real, verified by name + journal + year + venue URL. Anything not verifiable is marked `(unverified)` rather than dropped silently.

**What this doc is *not*:** an implementation plan. It exists to make the next planning conversation (or PR) start from a defended evidence base, not a hunch. Concrete endpoint → model → repository → router work happens in a follow-up plan spec.

---

## 1. Tier ranking — quick read

| Tier | Why this tier | Endpoints | Implementation cost |
|---|---|---|---|
| **Tier 1** | Directly upgrades the Trade Insights v1 design; evidence for predictive value is strongest | per-strike flow, per-expiry flow, net-prem ticks, event calendars (earnings/FDA/econ), expiry-breakdown | Standard `sources/uw.py` fetcher + repo + scheduler row (per `src/uw_scan/CLAUDE.md` 6-step checklist) |
| **Tier 2** | New "Positioning Quality" row; cheap reads, large evidence base | insider, congress, institutional, ETF exposure, analyst ratings, short volume-and-ratio | Same checklist; daily cadence is fine |
| **Tier 3** | Context / base-rate panels for synthesis row | seasonality (monthly + year-month), market-tide, sector ETFs, stock info | Cheap; mostly small JSON blobs |
| **Tier 4** | Higher implementation cost (streaming / tick storage); evidence is real but marginal value for a research page is moderate | greek-flow intraday, WebSocket option_trades/off_lit_trades, darkpool/recent, hottest chains screener | New worker subsystem, tick storage. Recommend separate design doc |

The recommendation in §7 is: ship Tier 1 + the analyst/insider/short slice of Tier 2 before merging the Trade Insights branch; defer Tiers 3 and 4 to follow-on PRs.

---

## 2. Tier 1 — Direct upgrades for Trade Insights v1

### 2.A — Per-strike option flow (`/api/stock/{ticker}/flow-per-strike`)

Aggregated net option volume — especially when decomposed by strike and by whether trades are buyer- or seller-initiated to open a position — has documented predictive content for future stock returns. The mechanism is **informed-trader migration to options** (Easley–O'Hara–Srinivas): leverage and short-sale-evasion incentives push privately-informed traders into the option market, leaving a footprint in signed option volume. Effects are strongest for short-dated, near-the-money, and slightly-OTM strikes — exactly the resolution that aggregated daily call/put volume averages out.

**Evidence**
- Pan & Poteshman (2006), *RFS* 19(3): 871–908 — stocks in the lowest put/call buy-to-open quintile outperform the highest quintile by **~40 bps the next day and ~1% over the next week** on a risk-adjusted basis. Predictability sourced from non-public information, not mispricing. https://academic.oup.com/rfs/article-abstract/19/3/871/1646711
- Easley, O'Hara & Srinivas (1998), *JF* 53(2): 431–465 — signed option volume Granger-causes stock-price changes; theoretical + empirical case that informed traders prefer options. https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.194060
- Garleanu, Pedersen & Poteshman (2009), *RFS* 22(10): 4259–4299 — end-user demand pressure at specific strikes moves option prices proportional to the variance of the unhedgeable component, and spills across strikes via covariance. Implies per-strike flow is priced. https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158
- Cremers & Weinbaum (2010), *JFQA* 45(2): 335–367 — call–put implied-vol spread (a strike-pair construct) predicts ~50 bps/week of stock return; decays over the sample as the market arbs it. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/deviations-from-putcall-parity-and-stock-return-predictability/D9BA8F97580328AAFD7988B092FE5D50

**Failure modes**
- Pan–Poteshman uses ISE **buy-to-open** trades; raw OPRA/UW prints conflate opening/closing and hedging flow. Without sign attribution, the signal degrades.
- Largely a stock-specific information effect; index-level aggregation washes it out.
- Cremers–Weinbaum effect degrades post-2000s — strategy crowding. Short-sale-constrained / earnings-overhang names retain more signal.

**Application** — Per-strike net-premium heatmap split call vs put, hover links back to underlying trades. Highlight imbalances at near-the-money and slightly-OTM short-dated strikes. Persist daily snapshots so a 5–10-day rolling buy-to-open imbalance can be rendered — that is the actual Pan–Poteshman regressor.

---

### 2.B — Per-expiry option flow (`/api/stock/{ticker}/flow-per-expiry`)

Expiry-bucketed net flow is best understood as a **dealer-hedging horizon signal**. Garleanu–Pedersen–Poteshman demand pressure builds up where end-users concentrate; Barbon–Buraschi show this empirically at the gamma level. Short-dated expiries dominate gamma per dollar of premium, so flow into 0–14DTE has outsized influence on intraday hedging and pin behavior; flow into long-dated expiries affects vega/vanna/skew without same-day spot dynamics.

**Evidence**
- Garleanu, Pedersen & Poteshman (2009), *RFS* — empirically identifies dealer vs end-user positions; demand pressure shifts the IV surface and varies by maturity bucket. https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158
- Barbon & Buraschi (2021) SSRN WP, "Gamma Fragility" — dealer aggregate gamma imbalance predicts intraday momentum (negative gamma) and intraday reversal (positive gamma); effect amplified by underlying illiquidity. Equity panel 2010–2020. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454
- SqueezeMetrics (2017), "Gamma Exposure" white paper — formalizes dealer-gamma → realized-vol relationship and standard sign convention (positive GEX dampens vol, negative GEX amplifies). Practitioner. https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf
- Ni, Pearson & Poteshman (2005), *JFE* 78(1): 49–87 — expiry-week hedging measurably moves underlying prices ~16.5 bps on expiration Fridays. https://www.sciencedirect.com/science/article/abs/pii/S0304405X05000577

**Failure modes**
- Net premium ≠ net gamma. A large long-dated trade is gamma-trivial vs a small 0DTE trade. Weight by gamma or DTE before drawing dealer-hedging conclusions.
- Dealer-net-short-gamma is a *calibration*, not a guarantee — in single names with heavy retail call-selling (covered calls) dealers can be net long gamma.
- Practitioner "short is long" sign convention is contested for single names where retail dominates (versus SPX, which is institutional-heavy).

**Application** — Stacked bar by bucket (0–7D, 8–30D, 31–90D, 90D+), call/put split per bucket. Pair the 0–7D bucket with a same-day realized-vol micro-sparkline. Cross-link the long-dated bucket to the term-structure card in the Vol tab (where Garleanu–Pedersen–Poteshman demand effects show up).

---

### 2.C — Net premium ticks (`/api/stock/{ticker}/net-prem-ticks`)

Intraday signed flow predicts short-horizon returns; the literature is thinner and more practitioner-led than for daily flow. Two complementary mechanisms: (1) **price discovery** — Hasbrouck-style information shares show options contribute meaningfully to spot price discovery; (2) **dealer hedging** — Barbon–Buraschi's intraday-momentum mechanism implies signed ticks during negative-gamma regimes are causal (delta-hedge feedback), not just informational.

**Evidence**
- Hasbrouck (1995), *JF* 50(4): 1175–1199 — defines information shares; applied later to options, finds non-trivial option-market information share in price discovery. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1995.tb04054.x
- Easley, López de Prado & O'Hara (2012), *RFS* 25(5): 1457–1493 — VPIN tracks order-flow toxicity in real time; spikes precede liquidity-driven price moves (notably the 2010 flash crash). Methodology transfers directly to signed option ticks. https://www.quantresearch.org/VPIN.pdf
- Barbon & Buraschi (2021) — intraday-momentum *signed* by dealer gamma imbalance; daily-level study, intraday mechanism by construction.
- Holowczak/Hu/Wu-type "informed volatility trading" line — net demand for volatility (signed option flow) partly predicts future realized vol. `(unverified)` — practitioner-secondary citation.

**Failure modes**
- Trade-sign inference from OPRA without NBBO timestamps is noisy. Lee–Ready style classification misclassifies 10–20% of option prints; noise compounds at 1-minute resolution.
- Most informational content lives at the 10–60-minute or daily level. Per-minute signal-to-noise is low.
- Intraday momentum only manifests in negative-gamma + illiquid regimes. In positive-gamma regimes the same signed ticks are mean-reverting — *the same data demands the opposite interpretation*.

**Application** — Stream a 1-minute signed-premium series (call_buy + put_sell − call_sell − put_buy), overlay on the spot mini-chart. Render a cumulative-delta line; divergence between cumulative-delta and spot is the practitioner read for hidden accumulation. **Gate** the "this is signal, not noise" annotation on the dealer-gamma sign from §2.B. Same data, different regime → opposite interpretation.

---

### 2.D — Event calendars (`/api/earnings/{ticker}`, `/api/market/economic-calendar`, `/api/market/fda-calendar`)

The most settled literature of the five Tier-1 endpoints. Three robust effects: (1) **IV term-structure inversion + post-event crush** around scheduled events; (2) **predictable cross-sectional return drifts** (pre-FOMC drift, post-earnings drift); (3) **informed-options-trading leakage** ahead of FDA and M&A binaries.

**Evidence**
- Patell & Wolfson (1979), *J. Accounting & Economics* 1(2): 117–140 — Black-Scholes implied variances rise into earnings announcements and collapse after. Foundational. https://www.sciencedirect.com/science/article/abs/pii/016541017990003X
- Donders & Vorst (1996), *J. Banking & Finance* 20(9): 1447–1461 — IV peaks the day before scheduled news, drops sharply after; underlying realized move is significantly larger than non-event days. https://www.sciencedirect.com/science/article/abs/pii/S0378426696000118
- Dubinsky, Johannes, Kaeck & Seeger (2019), *RFS* 32(2): 646–687, "Option Pricing of Earnings Announcement Risks" — reduced-form model decomposes IV into EA jump variance and normal variance; implied EA jump is quantitatively large and forecasts realized EA volatility. https://academic.oup.com/rfs/article-abstract/32/2/646/5001193
- Lucca & Moench (2015), *JF* 70(1): 329–371 — large pre-FOMC excess returns on US equities in the 24 hours before scheduled FOMC announcements; accounts for a sizable fraction of annual equity return. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12196
- Bohmann & Patel (2022), *J. Business Finance & Accounting* 49(7–8): 1211–1236 — pre-FDA-announcement IV spreads and options activity are abnormally elevated and predict FDA-day stock returns. https://onlinelibrary.wiley.com/doi/10.1111/jbfa.12600

**Failure modes**
- Lucca–Moench drift has weakened post-2015. Treat as time-varying.
- Earnings-vol crush is well-known and arbed; naive short-straddle into earnings has negative expectancy on average (vol risk premium for the seller, but with negative skew).
- FDA predictability is concentrated in small biotechs with information leakage; weaker in large pharma.

**Application** — Day-count ribbon for upcoming earnings / FDA / FOMC / scheduled macro, with a small inset showing front-month vs second-month IV inversion magnitude (Dubinsky et al. observable). For biotech tickers, an "options-activity anomaly" badge comparing trailing 10-day volume against baseline (Bohmann–Patel). On FOMC days for index ETFs, render the 24-hour Lucca–Moench window as a backdrop on the spot chart.

---

### 2.E — Expiry breakdown / OI concentration (`/api/stock/{ticker}/expiry-breakdown`)

OI concentration at specific strikes near expiration creates **delta-hedging pull toward the strike** as gamma diverges into expiry. Empirically confirmed for both single-name equities (Ni–Pearson–Poteshman) and the S&P (Golez–Jackwerth). "Max-pain" is the practitioner heuristic; the academic mechanism is more precisely "market-maker delta rebalancing as time-to-expiry → 0, conditional on net dealer-long gamma at the dominant strike."

**Evidence**
- Ni, Pearson & Poteshman (2005), *JFE* 78(1): 49–87 — optionable stocks cluster at strike prices on expiration Fridays; expiration-day returns altered by ~16.5 bps on average, ~$9B in market-cap shift. Two mechanisms: dealer hedge rebalancing and (separately) firm proprietary manipulation. https://www.sciencedirect.com/science/article/abs/pii/S0304405X05000577
- Golez & Jackwerth (2012), *JFE* 106(3): 566–585, "Pinning in the S&P 500 futures" — S&P futures pin to the ATM strike on serial-option expiries (~$115M notional shift per expiry); anti-pinning before SPX index-option expiries due to cost-of-carry/early-exercise dynamics. *(Note: published in JFE, not JFM.)* https://www.sciencedirect.com/science/article/abs/pii/S0304405X12001365
- SqueezeMetrics GEX white paper — operationalizes a strike-level dealer-gamma profile that makes pinning visualizable in real time. Practitioner. https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf
- Max-pain heuristic itself — *no strong academic source found*, practitioner only. The closest formal treatment is Ni–Pearson–Poteshman's hedge-rebalancing mechanism, which is the rigorous reason max-pain sometimes works.

**Failure modes**
- Pinning is a same-day-of-expiry phenomenon. Days out from expiry, max-pain is a weak predictor.
- The Ni–Pearson–Poteshman effect requires dealers to be **net long** the dominant strike. In single names with heavy net-customer-long calls (retail meme/momentum tickers), dealers are net short gamma and the effect *inverts*.
- 0DTE proliferation post-2022 has dramatically changed the empirical picture for SPX/SPY; the pinning literature pre-dates 0DTE — treat magnitudes as floors, not point estimates.

**Application** — Front-expiry OI-by-strike bar chart with current spot overlaid; highlight max-OI strike and the gamma-flip level. Within the last 5 trading days of an expiry cycle, render a "pin probability" tile (proximity to max-gamma strike × OI concentration × time-decay weight). **Cross-link to dealer-gamma-sign from §2.B** — without the sign, pin direction is ambiguous.

---

## 3. Tier 2 — Positioning quality row

The unifying claim of Tier 2 is that **who is holding / trading / underwriting the ticker** changes the prior on future returns. The evidence base is older and more cross-sectional than Tier 1, but the data is cheap (daily cadence is fine) and the signals are largely independent of Tier 1's flow / vol reads — so adding them widens the picture without correlated noise.

### 3.A — Insider transactions (`/api/insider/{ticker}/ticker-flow`, `/api/insider/{ticker}`)

Aggregate insider **buying** weakly predicts positive returns; insider **selling** is largely uninformative because dominated by liquidity, 10b5-1 plans, and diversification. Signal strongest in small caps, cluster buys by multiple insiders, and "routine"-filtered trades — senior officers/directors breaking their own pattern.

**Evidence**
- Lakonishok & Lee (2001), *RFS* 14(1): 79–111 — 1975–1995 NYSE/AMEX/Nasdaq. Aggregate insiders are contrarian and predict cross-sectional returns, concentrated in smaller firms. Announcement-day reaction is small (drift, not jump). https://academic.oup.com/rfs/article-abstract/14/1/79/1587398
- Cohen, Malloy & Pomorski (2012), *JF* 67(3): 1009–1043 — splitting into "routine" vs "opportunistic," opportunistic buys earn ~82 bps/month abnormal; routine trades have no predictive content. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2012.01740.x
- Seyhun (1998), *Investment Intelligence from Insider Trading*, MIT Press — ~1M trades, 1975–1995. Insider buys ~7% abnormal return over 12 months; sells far weaker; effect strongest for top executives and directors. https://mitpress.mit.edu/9780262194112/investment-intelligence-from-insider-trading/

**Failure modes**
- Sells dominated by non-information motives — naive net-buy/sell aggregates underweight the buy signal.
- Effect concentrated in small caps; large-cap signal is weak and slow.
- 10b5-1 plans (since 2000) mechanically schedule sales — Cohen–Malloy–Pomorski's "routine" filter is essential.
- Post-Reg FD and faster EDGAR ingestion have compressed the drift window; alpha has decayed.

**Application** — 6/12-month rolling net dollar buys by *officers + directors only* (exclude 10% owners, exclude 10b5-1 dispositions). Flag cluster buys (≥3 insiders within 30 days) and breaks-of-pattern (first open-market buy in N quarters). Display each insider's prior PnL track record (opportunistic-vs-routine tag). Weight more for small/mid caps.

---

### 3.B — Congress trades (`/api/congress/recent-trades`)

Early literature (pre-STOCK Act, 1985–1998) found significant abnormal returns for Senate and House trades. Better-controlled later work *overturned* the Senate result for 2004–2008 and post-2012 samples. **Modern consensus: in aggregate Congress does not beat the market.** Signal is at best idiosyncratic to specific committee-aligned trades and event-driven episodes (e.g., the January 2020 COVID-briefing trades). Render as colour, not as a return-generating signal.

**Evidence**
- Ziobrowski, Cheng, Boyd & Ziobrowski (2004), *JFQA* 39(4): 661–676 — Senate 1993–1998. Senator-purchased portfolio beat market by ~85 bps/month; sales lagged by 12 bps/month. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/abnormal-returns-from-the-common-stock-investments-of-the-us-senate/A39406479940758D59E09FDCB8EE9BEC
- Ziobrowski et al. (2011), *Business and Politics* 13(1) — House 1985–2001. Mimicking portfolio beat market by ~55 bps/month (~6%/yr). https://www.researchgate.net/publication/227378283
- Eggers & Hainmueller (2013), "Capitol Losses," *J. of Politics* 75(2): 535–551 — 2004–2008. Average member would have done *better* in a passive index fund. Rebuts the Ziobrowski Senate result for that window. https://www.journals.uchicago.edu/doi/abs/10.1017/s0022381613000194
- Belmont, Sacerdote, Sehgal & Van Hoek (2020), NBER WP 26975 — 2012–March 2020 (post-STOCK Act). Senator buys *underperform* peers by 11–28 bps at 1–6 months; no committee-skill effect. Notable exception: stocks sold after the January 24, 2020 COVID briefing fell ~9% below market. https://www.nber.org/papers/w26975
- Karadas & Schlosky (2022), *J. Public Economics* — independent post-STOCK Act sample; also finds no average outperformance. https://www.sciencedirect.com/science/article/abs/pii/S0047272722000044

**Failure modes**
- Disclosure lag (up to 45 days under STOCK Act) destroys most short-horizon alpha.
- Mechanical "follow Pelosi" / aggregate-Congress portfolios mix informed with random trades.
- A handful of viral traders dominate retail attention but are unrepresentative.

**Application** — Transactions table with member, committee, dollar bracket, disclosure delay. Flag trades from members whose **committee jurisdiction overlaps the issuer's sector** (defense / health / banking) — the only sub-population with arguable information. Render as sentiment chip, never a ranking input.

---

### 3.C — Institutional ownership (`/api/institution/{ticker}/ownership`)

A multi-dimensional signal: (i) *level* of institutional ownership relates to size, liquidity, price-pressure risk; (ii) *changes* in ownership predict short-horizon returns via herding and information; (iii) *type* (transient vs dedicated, hedge fund vs mutual fund) matters more than aggregate %.

**Evidence**
- Gompers & Metrick (2001), *QJE* 116(1): 229–259 — large institutions doubled equity share 1980–1996, mechanically bidding up large caps; can explain ~50% of the disappearance of the small-firm premium. Demand-side shifts move prices. https://academic.oup.com/qje/article-abstract/116/1/229/1938986
- Sias (2004), *RFS* 17(1): 165–206 — institutional demand this quarter is strongly correlated with prior-quarter institutional demand. Herding is *information-driven*, not momentum-driven. https://academic.oup.com/rfs/article-abstract/17/1/165/1564376
- Chen, Jegadeesh & Wermers (2000), *JFQA* 35(3): 343–368 — mutual-fund *trades* (not holdings) predict returns: stocks managers buy outperform stocks they sell over the following months; widely held names show no edge. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/value-of-active-mutual-fund-management-an-examination-of-the-stockholdings-and-trades-of-fund-managers/F3001866CA3A7CC5C72F6F31A97029A2
- Bushee (2001), *Contemporary Accounting Research* 18(2): 207–246 — high "transient" institutional ownership is associated with overweighting near-term earnings and underweighting long-term value; classification by horizon predicts abnormal returns. https://onlinelibrary.wiley.com/doi/abs/10.1506/J4GU-BHWH-8HME-LE0X

**Failure modes**
- 13F has 45-day lag, reports only long equity + listed options. Misses shorts, swaps, foreign holdings, intra-quarter round-trips.
- Crowding risk: high hedge-fund concentration can flip from tailwind to forced-unwind in deleveraging (2007 quant crisis, March 2020).
- Type misclassification: index funds dominate "institutional" totals but carry zero information.

**Application** — Separate active vs passive ownership; track delta-active over 1–4 quarters. Flag concentration (top-10 holder share, hedge-fund crowdedness percentile). Tag Bushee-style transient vs dedicated mix to anticipate sensitivity to near-term earnings. Surface "new buyers / full exits" rather than raw % change.

---

### 3.D — ETF exposure (`/api/etfs/{ticker}/exposure`)

ETF ownership injects **non-fundamental volatility** into underlying stocks via the creation–redemption arbitrage channel. High ETF ownership predicts higher idiosyncratic volatility and worse short-horizon price efficiency. ETF flow imbalances themselves are a return-predicting signal: high-flow ETFs mean-revert.

**Evidence**
- Ben-David, Franzoni & Moussawi (2018), *JF* 73(6): 2471–2535 — stocks with higher ETF ownership show significantly higher daily and intraday volatility; prices depart from random walk; effect identified via Russell 1000/2000 reconstitution. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12727
- Brown, Davies & Ringgenberg (2021), *Review of Finance* 25(4): 937–972 — ETF flows reflect non-fundamental demand; long-low-flow / short-high-flow ETF portfolio earns 1.1–2.0%/month. Flow-driven mispricing reverses. https://academic.oup.com/rof/article/25/4/937/5919085
- Wurgler (2010), NBER WP 16376 — survey of index-linked investing distortions. Index additions earn ~9% on average; subsequent comovement with index rises, comovement with non-index drops. https://www.nber.org/papers/w16376
- Coles, Heath & Ringgenberg (2022), *JFE* 145(3): 665–683 — using Russell reconstitution, find passive ownership *reduces* information production (Google searches, EDGAR views, analyst coverage) but does not impair price informativeness in equilibrium; active investors adjust. https://www.sciencedirect.com/science/article/abs/pii/S0304405X22001143

**Failure modes**
- Volatility amplification is largest in small/mid caps and during stress; can be invisible in calm regimes.
- High ETF ownership is correlated with size, liquidity, and multi-index inclusion — easy to confound with style exposure.
- Brown–Davies–Ringgenberg mispricing reverts but timing is noisy; spreads are small per name.

**Application** — Top-5 ETFs holding the stock with weights and AUM-weighted ownership share. Surface "passive flow into the stock" = Σ(creation/redemption flow × weight) over 5/20 days, with z-score extremes flagged. Annotate index-inclusion events; flag high-ETF-ownership names as having amplified non-fundamental volatility risk.

---

### 3.E — Analyst ratings (`/api/screener/analysts`)

Recommendation **changes** (especially downgrades) carry real information at the daily horizon; **levels** (consensus ratings) are too sluggish and crowded to trade profitably net of costs. Analysts herd toward consensus, which dilutes signal in steady state but amplifies it on bold deviating revisions.

**Evidence**
- Womack (1996), *JF* 51(1): 137–167 — buy-recommendation drift +2.4% (modest, short-lived); sell-recommendation drift −9.1% over 6 months. Asymmetric and economically large for sells. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1996.tb05205.x
- Barber, Lehavy, McNichols & Trueman (2001), *JF* 56(2): 531–563 — long-top-consensus / short-bottom-consensus with daily rebalancing earns >4%/yr gross abnormal returns, but turnover is high enough that *net* returns are statistically zero. Costs eat the signal. https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00336
- Jegadeesh & Kim (2010), *RFS* 23(2): 901–937 — analysts herd toward consensus; recommendations that deviate from consensus carry more information and produce stronger market reactions. https://academic.oup.com/rfs/article-abstract/23/2/901/1607290

**Failure modes**
- Conflicts of interest: investment-banking relationships skew toward buys (Michaely & Womack 1999).
- Post-Reg FD (2000) compressed information-asymmetry edge.
- Consensus crowding: by the time most names reach the top quintile, the price has already moved.
- Transaction costs kill the level-based long–short strategy at retail scale.

**Application** — Surface *recommendation changes* (delta) more prominently than consensus level. Flag "bold revisions" where the new rating deviates materially from consensus (Jegadeesh–Kim). Display target-price implied-return distribution (median, dispersion) and changes thereto, not just the mean. Annotate the issuing analyst's historical hit-rate where available.

---

### 3.F — Short interest + daily short volume (`/api/shorts/{ticker}/interest-float/v2`, `/api/shorts/{ticker}/volume-and-ratio`)

Heavily shorted stocks **underperform** in the cross-section, but strength depends on *who* is selling and *what type* of short. Daily short volume (flow) is more informative than bi-monthly short interest (stock); institutional and news-day shorts are most informed. Value-weighted strategies show much weaker effects than equal-weighted — much of the alpha lives in hard-to-borrow small caps.

**Evidence**
- Boehmer, Jones & Zhang (2008), *JF* 63(2): 491–527 — heavily shorted NYSE stocks underperform lightly shorted by 1.16%/20 trading days (~15.6% annualized); institutional non-program shorts most informative (1.43%/month, ~19.6% annualized). https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01324.x
- Diether, Lee & Werner (2009), *RFS* 22(2): 575–607 — daily short-selling activity predicts short-horizon negative returns; consistent with short sellers trading on short-term overreaction. Reg-SHO daily data. https://academic.oup.com/rfs/article-abstract/22/2/575/1596032
- Asquith, Pathak & Ritter (2005), *JFE* 78(2): 243–276 — short-sale-constrained stocks (high short interest + low institutional ownership) underperform 215 bps/month equal-weighted, 39 bps/month value-weighted, 1988–2002. Effect concentrated in small caps. https://www.sciencedirect.com/science/article/abs/pii/S0304405X05001431
- Engelberg, Reed & Ringgenberg (2012), *JFE* 105(2): 260–278 — short-return predictability is 2× larger on news days, 4× larger on negative-news days. Shorts are skilled processors of *public* information, not necessarily privately informed. https://www.sciencedirect.com/science/article/abs/pii/S0304405X12000384

**Failure modes**
- **Squeeze regime** (hard-to-borrow + retail crowding + low float → GME 2021): the same constraints that produce mean alpha produce huge negative skew.
- Bi-monthly short-interest reporting (~5 BD delay) blunts the stock; daily short volume (Reg SHO) is the live version.
- Value-weighted effects are much smaller — strategy doesn't scale to large caps.
- Engelberg–Reed–Ringgenberg implies the signal works *around news*, not in flat tape.

**Application** — Show both stocks (short interest %, days-to-cover) and flow (daily short-volume ratio, 5-/20-day average). Display borrow cost / utilization (Asquith–Pathak–Ritter constraint proxy). Flag "informed-short conditions" = rising short volume *and* negative-tilt news flow. Surface squeeze-risk metrics (short %, float, retail-attention proxy) as a separate, opposite-signed warning chip.

---

## 4. Tier 3 — Context / base-rate panels

### 4.A — Stock seasonality (`/api/seasonality/{ticker}/monthly`, `/api/seasonality/{ticker}/year-month`)

Calendar-month seasonality in individual stock returns is real but the realizable edge is contested and decays with publication. **Best framed as descriptive base-rate context**, not a tradable signal.

**Evidence**
- Heston & Sadka (2008), *JFE* 87(2): 418–445 — stocks with high (low) returns in a given calendar month tend to repeat that pattern annually; effect independent of size, industry, earnings, dividends, fiscal year. https://ideas.repec.org/a/eee/jfinec/v87y2008i2p418-445.html
- Bouman & Jacobsen (2002), *AER* 92(5): 1618–1635 — "Halloween Indicator": Nov–Apr returns substantially exceed May–Oct in 36 of 37 country indices, 1970–1998. https://www.aeaweb.org/articles?id=10.1257/000282802762024683
- Keim (1983), *JFE* 12(1): 13–32 — roughly half of the historical size premium accrues in January, with most of January's premium in the first trading week. https://www.sciencedirect.com/science/article/abs/pii/0304405X83900259
- Sullivan, Timmermann & White (2001), *J. Econometrics* 105(1): 249–286 — once you adjust for the universe of rules searched, nominal calendar-effect p-values lose significance. https://www.sciencedirect.com/science/article/abs/pii/S030440760100077X
- Dichtl & Drobetz (2015), *Finance Research Letters* — out-of-sample bootstrap shows the Halloween effect has materially weakened post-publication in the US. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308626

**Caveats** — Multiple-testing problem (12 months × thousands of tickers). January/size effect decayed post-1980s. Sensitive to sample period and outliers.

**Application** — 12-row year-month grid with mean return, hit-rate, and a small-sample warning when n_years < 10. Treat as "what has happened," never as forecast. Hide when historical sample is < ~15 years.

### 4.B — Market sentiment / market tide (`/api/market/market-tide`)

Aggregate sentiment is one of the more empirically robust "context" signals: high sentiment compresses expected returns on speculative, hard-to-value names; low sentiment predicts the opposite. Useful as a **modifier** on a single-ticker view, not a standalone signal.

**Evidence**
- Baker & Wurgler (2006), *JF* 61(4): 1645–1680 — canonical sentiment index; when sentiment is high, subsequent returns are *low* for small, young, high-vol, unprofitable, non-dividend, extreme-growth, distressed stocks. https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2006.00885.x
- Baker & Wurgler (2007), *JEP* 21(2): 129–152 — review article formalizing the top-down sentiment framework. https://www.aeaweb.org/articles?id=10.1257/jep.21.2.129
- Da, Engelberg & Gao (2015), *RFS* 28(1): 1–32, "Sum of All FEARS" — Google-search-volume-based daily sentiment predicts short-term return reversals, temporary volatility spikes, equity-to-bond mutual fund flows. https://academic.oup.com/rfs/article-abstract/28/1/1/1682440
- Tetlock (2007), *JF* 62(3): 1139–1168 — media pessimism predicts downward price pressure followed by reversion; high trading volume at sentiment extremes. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2007.01232.x

**Caveats** — B&W index is monthly, slow-moving, components changed availability post-2006. FEARS effects are short-horizon (days). Sentiment indices look mechanically procyclical. Cross-sectional sensitivity concentrated in speculative names — for blue chips effect is small.

**Application** — Banner-level "market tide" line, plus one inline annotation tying it to the ticker's profile ("Sentiment elevated; this name is high-beta / non-dividend → headwind per Baker–Wurgler cross-section").

### 4.C — Sector ETF positioning (`/api/market/sector-etfs`)

Sector membership carries real predictive structure: industry returns are autocorrelated and information diffuses slowly across economically linked firms.

**Evidence**
- Moskowitz & Grinblatt (1999), *JF* 54(4): 1249–1290 — industry momentum (long top, short bottom industry portfolios) is strong; controlling for it materially reduces individual-stock momentum profits. https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146
- Cohen & Frazzini (2008), *JF* 63(4): 1977–2011 — customer-supplier links predict cross-asset returns; long-short strategy earns ~150 bps/month alpha. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01379.x
- State Street SPDR sector tools — practitioner reference for sector relative strength and flows. https://www.ssga.com/us/en/intermediary/resources/sector-tracker

**Caveats** — Industry momentum reverses at longer horizons; sector ETF flows confounded by index/factor-ETF rebalancing; GICS can mis-label conglomerates and platform companies.

**Application** — Parent sector ETF's 1M/3M relative performance vs SPY, plus the ticker's 1M/3M return vs its sector ETF. Optional supply-chain "linked names" list. Frame as "is the tide pushing the sector, and is this name leading or lagging within it."

### 4.D — Stock info / metadata (`/api/stock/{ticker}/info`)

Reference fields, no predictive content on their own. Used as control variables.

**Evidence**
- Banz (1981), *JFE* 9(1): 3–18 — small NYSE firms earned higher risk-adjusted returns; size effect concentrated in the smallest decile. https://www.sciencedirect.com/science/article/abs/pii/0304405X81900180
- Fama & French (1992), *JF* 47(2): 427–465 — size and book-to-market jointly absorb the explanatory power of beta, leverage, and E/P in the cross-section. https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04398.x

**Caveats** — Size premium has been weak-to-absent in US data since the early 1980s (AQR "Fact, Fiction, and the Size Effect"). "Has-options" is an eligibility flag, not a return predictor.

**Application** — Static header strip (sector, mkt-cap bucket, ADV, options-listed Y/N, next earnings date). Use the size bucket only to *contextualize* other signals — never as a standalone signal.

---

## 5. Tier 4 — Streaming / tick-store signals

### 5.A — Intraday greek flow (`/api/stock/{ticker}/greek-flow`)

Closest practitioner proxy for the **dealer-hedging channel** that academia has now formally identified: aggregate dealer gamma/vega imbalance reshapes intraday return autocorrelation and realized volatility through forced delta rebalancing. Worth a dedicated subsystem **only if** the page is built around dealer-positioning narratives (squeeze risk, pin risk, vol-crush trades); otherwise an end-of-day GEX snapshot captures ~80% of the signal.

**Evidence**
- Barbon & Buraschi (2021), "Gamma Fragility" — negative ex-ante dealer gamma plus low underlying liquidity predicts intraday momentum; positive gamma plus low liquidity predicts reversal. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454
- Ni, Pearson, Poteshman & White (2021), *RFS* 34(4): 1952–1986 — direct evidence that option-MM delta-hedging causes information in option order flow to be impounded into the stock; MM hedge rebalancing measurably affects stock-return volatility and tail-move probability. https://academic.oup.com/rfs/article-abstract/34/4/1952/5873587
- SqueezeMetrics (2017), "Gamma Exposure" + (2020) "Implied Order Book" — practitioner. https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf

**Implementation cost / failure modes** — Per-minute snapshots of full chain with NBBO mid + IV, derived delta/vega/gamma per contract, persisted as a wide tick table; storage ~tens of MB per ticker per day. Failure modes: (1) dealer-direction sign is *assumed* (calls = dealer short, puts = dealer long per SqueezeMetrics convention but not always true post-0DTE retail flow); (2) signal collapses in illiquid names where mids are stale; (3) earnings-week vega flow dominates and confounds the gamma read.

**Application** — Two stacked sparklines (cumulative delta-flow, cumulative vega-flow) over session, anchored to spot path. Annotate zero-gamma strike and largest |gamma| strike. Surface a regime tag (long-gamma damping vs short-gamma amplifying).

### 5.B — WebSocket option_trades / off_lit_trades

Live tape has clear price-discovery value over daily aggregates, but most of that value accrues to liquidity providers and millisecond-latency arbs, **not a research page reading at 1–5s cadence**. Worth streaming only if you intend to compute order-flow toxicity (VPIN), aggressor-side imbalance, or block detection in real time; otherwise minute-bar aggregates are sufficient.

**Evidence**
- Hasbrouck (1995), *JF* 50(4): 1175–1199 — defines information shares; shows price discovery is fragmented across venues and recoverable only from tick-level cointegrated quote/trade data. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1995.tb04054.x
- Easley, López de Prado & O'Hara (2012), *RFS* — VPIN as volume-bucketed real-time toxicity gauge; elevated VPIN preceded the 2010 Flash Crash. Requires signed tick volume — exactly what option_trades provides. https://www.quantresearch.org/VPIN.pdf
- Hendershott & Riordan (2013), *JFQA* — algorithmic quotes/trades contain incremental price-relevant information. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/algorithmic-trading-and-the-market-for-liquidity/C1A34D3767436529EA4F23DB1780273C

**Implementation cost / failure modes** — Persistent WebSocket client, reconnect/backfill logic, per-trade aggressor classification (we already have `aggressor_classification_semantics` memory documented), tick-store with bucketed VPIN. Failure modes: (1) WS gaps silently invalidate VPIN buckets; (2) sweeps and multi-leg fills get mis-attributed; (3) at 1–5s page cadence, you re-derive what minute bars would give — diminishing returns.

**Application** — Live tape strip (last ~50 prints, color-coded by aggressor) + rolling VPIN gauge + cumulative signed-premium curve for the session. Block prints (>$500k premium or off-lit) flagged inline.

### 5.C — Cross-ticker dark pool (`/api/darkpool/recent`)

Dark-pool prints carry *some* informational content, but the academic verdict is conditional: **small / non-block** dark prints can be informative; **large block** prints are generally uninformed liquidity-motivated trades. Marginal value of a cross-ticker feed for a single-ticker page is mostly contextual, not per-ticker alpha.

**Evidence**
- Zhu (2014), *RFS* 27(3): 747–789 — informed traders cluster on the heavy side, face higher non-execution risk in dark pools, self-select onto lit exchanges; uninformed flow migrates to dark. Adding a dark pool *can improve* lit price discovery. https://academic.oup.com/rfs/article-abstract/27/3/747/1580317
- Comerton-Forde & Putniņš (2015), *JFE* 118(1): 70–92 — dark trades are *less* informed than lit trades; low non-block dark trading is benign/beneficial; high levels harm informational efficiency. Block dark shows no price-discovery harm. https://www.sciencedirect.com/science/article/abs/pii/S0304405X15001191
- Buti, Rindi & Werner (2017), *JFE* 124(2): 244–265 — dark-pool fill rates rise with lit-book liquidity; dark venues most active when lit is deep. Implies regime-dependence. https://www.sciencedirect.com/science/article/abs/pii/S0304405X16300022
- Hatheway, Kwan & Zheng (2017), *JFQA* 52(6): 2399–2427 — confirms dark venues siphon uninformed flow and contribute less to price efficiency; segmentation is harmful except for genuine block executions. https://www.researchgate.net/publication/321257664

**Implementation cost / failure modes** — Continuous polling, per-ticker rollups, separate `dark_print` table with size/notional/venue. Failure modes: (1) FINRA ADF reporting can lag 10–600s; (2) most "dark" prints in a minute are passive retail crosses, not informed institutional flow; (3) block detection requires venue-aware size thresholds, not raw counts.

**Application** — Session-long timeline strip of dark prints with bubble size = notional, color by NBBO position (above/below/mid). A cross-ticker "context badge" showing where today's ticker ranks in dark-volume percentile across the watchlist.

### 5.D — Hottest chains screener (`/api/screener/option-contracts`)

Justified as a **discovery layer** — anomalous O/S and contract-level concentration predict underlying returns — but belongs on the watchlist landing or a dedicated screener, not on a single-ticker page. On single-ticker, render only as a contextual badge.

**Evidence**
- Roll, Schwartz & Subrahmanyam (2010), *JFE* 96(1): 1–17, "O/S: The Relative Trading Activity in Options and Stock" — O/S varies with delta, costs, institutional holdings, analyst dispersion; spikes around earnings; high O/S predicts lower post-announcement abnormal returns, suggesting options trading anticipates news. https://www.sciencedirect.com/science/article/abs/pii/S0304405X09002347
- Anand & Chakravarty (2007), *JFQA* 42(1): 167–187, "Stealth Trading in Options Markets" — informed traders fragment orders into *medium*-size trades on the dominant exchange; ~60% of options price discovery occurs on that venue; ATM calls carry the highest information share. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/stealth-trading-in-options-markets/CE65454300E9D73D098C64E19002697C
- UW writeup on the hottest-chains screener methodology — *could not verify* a public methodology doc; the endpoint's ranking should be treated as opaque, with inferred semantics documented in-repo.

**Implementation cost / failure modes** — Cron/poll the screener every 1–5 min, persist a ranked snapshot keyed by (ts, contract). Failure modes: (1) "hot" usually means *volume*, dominated by 0DTE retail noise — academic O/S signal is washed out without filtering by maturity and size; (2) snapshot rebases each poll, so trend extraction needs explicit persistence.

**Application** — On single-ticker: small "rank in today's hottest chains: N of M" badge linking to a watchlist-wide screener. On the screener landing: sortable table with O/S, OI delta, ATM-strike premium concentration, and a "stealth-size" flag for medium-trade-dominated contracts.

---

## 6. Cross-tier observations

A handful of patterns emerge when reading the four tiers together:

1. **Sign-dependence dominates.** Three of the strongest mechanisms — Pan–Poteshman (signed BTO vs raw volume), Barbon–Buraschi (dealer-gamma sign), Ni–Pearson–Poteshman (dealer net-long vs net-short the dominant strike) — *invert* with the wrong sign. Every endpoint we add should be sign-aware; raw aggregates are not just weaker, they can be *opposite-signed*. This argues for surfacing the dealer-gamma sign from §2.B prominently and *gating other Tier-1 interpretations on it*.

2. **Single-ticker vs cross-sectional.** Tiers 1–2 evidence is single-ticker friendly (per-name effects). Tiers 3–4 evidence is mostly cross-sectional (cross-section of stocks sorted by sentiment, short interest, dark-print ratio, etc.). The implication: Tier 3 belongs in headers/banners, Tier 4 dark/hot-chains belongs on the watchlist landing — neither is best served as a single-ticker focal panel.

3. **Decay matters more than magnitude.** Several Tier-2 effects (Cremers–Weinbaum, Womack drift, Halloween indicator) have measurably decayed post-publication. We should surface effects without claiming the magnitudes still hold — the Trade Insights tab is research-shaped (per its design doc), so framing them as "what the literature has historically found" rather than "what to expect today" is honest and protects against publication-decay overclaim.

4. **The "event check required" badge is the single highest-leverage Tier-1 addition.** The design already has the badge; the literature has the strongest, most settled effects (Patell–Wolfson, Dubinsky et al., Lucca–Moench, Bohmann–Patel). Wiring earnings + FDA + econ calendars is cheap and immediately makes that badge evidence-backed.

5. **Streaming buys real capability but at real cost.** Tier 4 is the only one that requires a new worker subsystem (tick storage, WS reconnect, per-tick aggressor classification). The evidence is real (Hasbrouck, VPIN, Barbon–Buraschi, Ni–Pearson–Poteshman–White) but skewed toward microsecond/millisecond capture, not a 1–5s research page. A separate design doc, not a casual addition.

---

## 7. Recommendation

For the in-progress Trade Insights tab branch (`feat/trade-insights-tab`):

**Ship in this PR (or its immediate follow-up):**
- Tier 1 in full — `flow_per_strike`, `flow_per_expiry`, `net_prem_ticks`, `expiry_breakdown`, and event calendars (`earnings/{ticker}` + econ + FDA).
- Tier 2: `analyst` ratings + `insider/ticker-flow` + `shorts/volume-and-ratio` (the three with the strongest literature and the lowest data weight per ticker).

**Defer to a follow-up PR (next sprint):**
- Tier 2 remainder: institutional ownership, ETF exposure, congress.
- Tier 3 in full (seasonality, market-tide, sector-ETFs, stock/info).

**Separate design doc required:**
- Tier 4 (intraday greek-flow, WebSocket option_trades / off_lit_trades, dark-recent, hottest-chains). New worker subsystem, tick storage, retention policy — too much to slot into a tab-feature PR.

A concrete implementation plan for the shipped slice should follow the 6-step new-endpoint checklist in `src/uw_scan/CLAUDE.md` (slug → model → fetcher → repository → report/scheduler → tests) and land at `docs/superpowers/plans/2026-05-XX-trade-insights-endpoints-tier1-2.md`.

---

## 8. Open questions

- **Sign attribution for `flow-per-strike` / `net-prem-ticks`** — does UW already aggregator-classify, or does the page need to compute signed flow from the raw print stream? Worth a 1-hour spike against the live API before scoping the fetcher.
- **0DTE handling for `expiry-breakdown`** — Ni–Pearson–Poteshman pre-dates 0DTE. Should the front-expiry view collapse all 0DTE strikes into a sub-row, or render them inline? Decision affects the pin-probability tile.
- **Decay-aware framing in copy** — should the Trade Insights synthesis annotate evidence with "effect last empirically confirmed in {year} sample"? Probably yes for Cremers–Weinbaum, Womack, Halloween; probably no for newer event-study results.
- **Cost/benefit of WebSocket vs minute-bar polling** for Tier 4 — punt until the Tier-1/2 work is done and we see whether intraday narratives demand sub-minute resolution.

---

## 9. References — index

All citations in this document are verified by title + author + year + journal/venue + URL. Search any of the following terms in §2–5 to find the in-context discussion.

Asquith Pathak Ritter 2005 · Baker Wurgler 2006/2007 · Banz 1981 · Barber Lehavy McNichols Trueman 2001 · Barbon Buraschi 2021 · Belmont Sacerdote 2020 · Ben-David Franzoni Moussawi 2018 · Boehmer Jones Zhang 2008 · Bohmann Patel 2022 · Bouman Jacobsen 2002 · Brown Davies Ringgenberg 2021 · Bushee 2001 · Buti Rindi Werner 2017 · Chen Jegadeesh Wermers 2000 · Cohen Frazzini 2008 · Cohen Malloy Pomorski 2012 · Coles Heath Ringgenberg 2022 · Comerton-Forde Putniņš 2015 · Cremers Weinbaum 2010 · Da Engelberg Gao 2015 · Dichtl Drobetz 2015 · Diether Lee Werner 2009 · Donders Vorst 1996 · Dubinsky Johannes Kaeck Seeger 2019 · Easley López-de-Prado O'Hara 2012 · Easley O'Hara Srinivas 1998 · Eggers Hainmueller 2013 · Engelberg Reed Ringgenberg 2012 · Fama French 1992 · Garleanu Pedersen Poteshman 2009 · Golez Jackwerth 2012 · Gompers Metrick 2001 · Hasbrouck 1995 · Hatheway Kwan Zheng 2017 · Hendershott Riordan 2013 · Heston Sadka 2008 · Jegadeesh Kim 2010 · Karadas Schlosky 2022 · Keim 1983 · Lakonishok Lee 2001 · Lucca Moench 2015 · Moskowitz Grinblatt 1999 · Ni Pearson Poteshman 2005 · Ni Pearson Poteshman White 2021 · Pan Poteshman 2006 · Patell Wolfson 1979 · Roll Schwartz Subrahmanyam 2010 · Seyhun 1998 · Sias 2004 · SqueezeMetrics 2017 · Sullivan Timmermann White 2001 · Tetlock 2007 · Womack 1996 · Wurgler 2010 · Zhu 2014 · Ziobrowski et al. 2004/2011.
