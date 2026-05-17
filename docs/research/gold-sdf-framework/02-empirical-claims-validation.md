# 02 — Empirical Claims Validation

Where the source article makes a falsifiable numerical claim, this file records the primary-source counter-evidence. Used to separate the article's robust claims from its imprecise or unverified claims before any of them get baked into the model.

---

## Summary table

| # | Article's claim | Primary-source finding | Verdict |
|---|---|---|---|
| 1 | Gold/CPI monthly correlation **~0.08** (1975-2012) | Ang reports **0.01** for 1986-2011 monthly; **0.23 annual** for 1875-2011 | **Directionally correct, quantitatively imprecise** |
| 2 | 10-year rolling correlation **~0.35** | Not directly verified; consistent with Erb-Harvey's long-horizon argument | **Plausible, unverified** |
| 3 | Gold-real-rate correlation: strong negative | Erb-Harvey: **-0.82** (level); LBMA: weekly R²=0.65 with **-$173/oz per 1pp TIPS** (2014-2018) | **Confirmed pre-2022** |
| 4 | 1971-1980: gold $35 → $850 (~20x) | $850 LBMA Afternoon Fix on **Jan 21, 1980**; $35 was 1971 fixed rate at Bretton Woods end | **Fully confirmed** |
| 5 | 2011 → 2020 nine-year sideways while CPI cumulative +17% | Gold peaked $1,900 Sept 2011, recovered to $2,070 Aug 2020; CPI cumulative ~17% verified | **Confirmed** |
| 6 | 2019-2020: TIPS +0.8% → -1.0%, gold $1,300 → $2,070 | DFII10 ~+0.7% late 2018 → -1.05% Aug 2020; gold ~$1,290 May 2019 → ATH $2,067 Aug 2020 | **Confirmed** |
| 7 | 2021-2022: CPI peak >9%, T5YIFR peak ~2.9%, didn't break 3.0% threshold | CPI peaked 9.1% June 2022; T5YIFR peaked ~2.67-2.93% April-May 2022 | **Confirmed** |
| 8 | 1973-1980 long-term inflation expectations broke 6% | T5YIFR series didn't exist before 2003; pre-2003 figures are modeled (Cleveland Fed / Hoey survey) | **Inferential, not market-observed** |
| 9 | T5YIFR thresholds 2.5% / 2.8% / 3.0% define anchored/transitional/unanchored | No academic source; Fed staff discuss anchoring qualitatively but pin no specific bp threshold | **Heuristic, not validated** |

---

## Detailed notes on each claim

### Claim 1: Gold-CPI monthly correlation 0.08

The article cites this as "1975-2012 monthly correlation, approximately 0.08." Ang's actual published number is **0.01** for 1986-2011 monthly returns (per CXO Advisory summary, which quotes Ang directly). The discrepancy could be a different window (1975-2012 includes the 1970s inflation period that dominates the correlation) or a different specification (Ang uses returns, the article may use prices).

**Implication for implementation:** When we surface gold-inflation correlation on the dashboard, compute it ourselves from FRED data with explicit window + specification choices. Do not republish the article's 0.08 figure as a quoted statistic.

### Claim 3: Gold-real-rate correlation, strong negative

Erb-Harvey's -0.82 (between gold *price level* and real rate level) is widely cited but is a **levels** correlation, not a returns correlation. LBMA's R²=0.65 was on **weekly returns** 2014-2018 with TIPS yield change and DXY change as regressors. Both are pre-2022.

Post-2022, RBC reports the correlation fell to -3% (2022-2023) and -7% (2024-present). See [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) for the deeper discussion.

**Implication:** Any claim of "gold is strongly negatively correlated with real rates" must specify (a) levels vs returns, (b) window, (c) frequency. Pre-2022 the relationship was tight; the article's framing without these qualifications is misleading in current conditions.

### Claim 4: 1971-1980 gold price trajectory

Fully verified. The 1971 figure refers to the August 1971 closure of the gold window (US dollar-gold convertibility suspension, ending Bretton Woods). The $850 peak was the LBMA Afternoon Fix on January 21, 1980. JM Bullion and several primary commodity-history sources corroborate.

**One caveat the article omits:** Gold's 1970s rise was not monotonic. It hit $193 in December 1974, then **dropped to $112.80 by August 1976** before resuming the climb. A two-year ~42% drawdown inside a major bull move is a discipline lesson the article skips over.

### Claim 5: 2011-2020 nine-year sideways

Verified. Gold's September 2011 high of $1,900 was not reclaimed until August 2020 ($2,070). During those nine years US CPI cumulative gain was approximately 17% (CPIAUCSL index ~226 in Sept 2011 → ~260 in Aug 2020).

**This is the article's strongest empirical claim** and the cleanest single piece of evidence against the popular "gold = inflation hedge" narrative. Worth surfacing prominently in the dashboard.

### Claim 8: 1970s inflation expectations broke 6%

The T5YIFR series did not exist before 2003 — TIPS were not issued in the US until 1997, and the 5y5y forward construction requires a developed TIPS curve. Pre-2003 inflation expectations come from:

- **Cleveland Fed model**: Reconstructed using a no-arbitrage term-structure model. Available back to 1980s.
- **Michigan Survey of Consumers**: Started 1978, 1-year-ahead expectations.
- **Hoey Survey of Professional Forecasters**: Late 1970s ad hoc surveys

The article's claim that 1970s long-term expectations "broke 6%" is most likely sourced from the Cleveland Fed reconstruction. This is a modeled estimate, not a market-observed series. The dashboard should not present pre-2003 T5YIFR-style data as if it's directly comparable to post-2003 market expectations.

### Claim 9: T5YIFR threshold values

No academic source pins 2.5% / 2.8% / 3.0% as anchoring/transitional/unanchored boundaries. Fed staff papers (e.g., Bernanke 2007 anchoring discussions, Powell 2018 speech on credibility) treat anchoring qualitatively. The 2% target gives a natural midpoint; values within ~50bp of target are conventionally described as "well-anchored." 2.8-3.0% as a hard threshold is the article's heuristic, not a literature finding.

**Implication:** Expose these thresholds as configurable parameters in the regime classifier rather than hard-coding them. Default to the article's values but allow override.

---

## Claims worth computing ourselves before publishing

These are the article's claims that require an internal validation pass before any dashboard surfaces them:

1. **Gold-CPI correlation over multiple windows**, specifying returns vs levels, monthly vs annual.
2. **10-year rolling Gold ↔ CPI correlation** time series. Article cites ~0.35 but never specifies methodology.
3. **Gold-TIPS correlation pre-2022 vs post-2022**, replicating the RBC finding with our own data.
4. **Per-regime historical mean return and volatility for gold**, after we define the three regimes with article-default thresholds.

These computations are not large — half a day's work with FRED CSVs in pandas — and they ensure the dashboard's headline statistics come from inside this codebase, not from the article's prose.
