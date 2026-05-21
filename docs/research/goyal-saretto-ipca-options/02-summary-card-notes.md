# 02 — User-provided summary card: translation and verification

The user provided a bilingual (CN/EN) summary card titled *"美股期权数十个'选股因子'是否真的存在'超额收益'?"* attributed to @leifuchen. This file translates the card and cross-checks each numeric claim against the published RFS paper.

> **Bottom line:** the card is broadly faithful, but **the Stock-price IPCA alpha on the chart (0.15%) is wrong — the paper's Table 3 says 0.09%.** All other top-5 numbers match. The four-step argument structure (raw → IPCA → RV−IV centrality → TC) is a clean and accurate distillation of the paper's argument flow.

## English translation of the card

### Headline & data

- **Title:** "Do dozens of US-equity-option 'stock-selection factors' really earn alpha?"
- **Subtitle:** OptionMetrics US single-name options · 1996.01–2022.12 · 46 cross-sectional features

### CORE callout box

> The 46 cross-sectional signals academia has identified over the past decade-plus all, at root, capture **variance risk premium (VRP, measured as RV−IV)** in different forms — other features pick it up indirectly via their correlation with RV−IV. **After transaction costs, the "alpha" of all these strategies disappears.**

### Chart: "Top 5 by raw return — raw monthly returns (green) are stunning, but after IPCA adjustment the 'alpha' (red) is near zero"

Method note on the card: "Sort all stocks by feature value into 10 deciles, long one decile and short another (the paper chose the profitable direction in each case — e.g. RV−IV: long high, short low; ATM IV: long low, short high). Explanation rate = 1 − IPCA-alpha / raw-return."

| Feature | Raw (card) | IPCA alpha (card) | "Explained" (card) |
|---|---:|---:|---:|
| RV−IV | 2.87% | 0.34% | 88% |
| ATM IV | 2.34% | 0.24% | 90% |
| IV skew (i.e. IV slope) | 2.15% | 0.34% | 84% |
| Stock price | 1.73% | **0.15%** ⚠ | **91%** ⚠ |
| Market cap | 1.59% | 0.11% | 93% |

### FOUR STEPS section

1. **"Raw returns look highly inefficient."** 46 long-short portfolios; 39 statistically significant monthly returns; top strategies have *t* > 10 (essentially impossible to be noise).
2. **"IPCA 3-factor model eats the raw alpha."** With 3-factor IPCA and no intercept, the 46 strategies' average alpha drops to 6bp. After MHT correction, only 2 strategies keep significant alphas.
3. **"The first factor is essentially RV−IV."** Setting RV−IV's factor loading (Γ_β) to zero makes 32 other strategies' alphas rebound — average rebound ≈ 1%/month. RV−IV indirectly drives most of the other features.
4. **"Add transaction costs and *all* the alpha disappears."** With ESPR/QSPR = 30%, 16 strategies still earn significant gross returns, but after IPCA risk adjustment, all 46 net alphas are negative.

### Footer

"Goyal, A., & Saretto, A. (2024). Can equity option returns be explained by a factor model? IPCA says yes. Working Paper · Study notes, personal research use only · 整理 @leifuchen"

---

## Verification against the published paper

### Top-5 chart numbers

Paper sources:
- Raw long-short returns: Table 1, p.1791 ("Return" column, percent per month, *t*-stats in parentheses)
- IPCA alphas: Table 3, p.1801 (percent per month, *t*-stats in parentheses)

| Feature | Card raw | Paper raw (Table 1) | Card IPCA α | Paper IPCA α (Table 3) | Verdict |
|---|---:|---:|---:|---:|---|
| RV−IV | 2.87 | 2.87 (24.51) | 0.34 | **0.34 (4.68)** | ✅ match |
| IV ATM | 2.34 | 2.34 (17.94) | 0.24 | **0.24 (4.58)** | ✅ match |
| IV slope | 2.15 | 2.15 (25.53) | 0.34 | **0.34 (4.58)** | ✅ match |
| Stock price | 1.73 | 1.73 (16.09) | **0.15** | **0.09 (0.65)** | ❌ card off |
| MarketCap | 1.59 | 1.59 (16.74) | 0.11 | **0.11 (1.00)** | ✅ match |

**The card's Stock-price α = 0.15% doesn't appear in Table 3.** The paper has 0.09%, which (a) is below the MHT threshold of 2.60 and not statistically significant, and (b) gives an "explained" share of 1 − 0.09/1.73 = **94.8%**, not 91%. Possible sources: (i) typo in the card; (ii) an earlier working-paper version; (iii) confusion with a different row (Option price alpha is −0.19 in Table 3 — not a match; Profit margin is 0.02 — not a match; no row equals exactly 0.15). I cannot reconstruct where 0.15 came from. The card is internally consistent (0.15 / 1.73 ≈ 91%) but does not match Table 3.

### "39 of 46 statistically significant" — claim 01

> "Table 1 shows that many characteristics are strong predictors of delta-hedged call returns. Of the 46 predictors, **39 have statistically significant average returns to long-short portfolios** (MHT adjustment versus conventional level does not change this number)." (p.1792)

✅ **Verbatim match.**

### "Average IPCA alpha ≈ 6bp, 2 of 46 survive MHT" — claim 02

> "Table 3 reports alphas and t-statistics. **The average alpha across the 46 trading strategies is about 6 basis points**, or equivalently about 7% of the average raw return. After controlling for MHT, 2 (5 at conventional levels) long-short portfolios still have a statistically significant IPCA alpha: IV slope and RV−IV." (p.1800)

✅ **Verbatim match.** The 2 survivors are RV−IV (*t*=4.68) and IV slope (*t*=4.58), with IV ATM (*t*=4.58) right at the threshold. Table 3 footnote confirms MHT cutoff *t* = 2.60.

### "RV−IV gamma to zero → 32 strategies alpha increases ~1%" — claim 03

> "Setting the covariance coefficients, Γ_β, related to RV−IV to zero greatly decreases the ability of the IPCA model to price any portfolio that is not related to RV−IV: **for example, 32 strategies see an increase in alpha and that increase is 1% on average.**" (p.1815, opening of the section after §6 Conclusion start on p.1814)

✅ **Verbatim match.** Note this is a structural claim about Γ_β (the static mapping from characteristics to betas), *not* about residualizing portfolio returns on RV−IV-return — those are different operations. The card's phrasing ("setting the first factor's loading for RV−IV to zero") is loose; "setting Γ_β coefficients on the RV−IV row to zero" is the precise version.

### "30% ESPR/QSPR, 16 strategies positive gross net, all IPCA-α negative net of TC" — claim 04

> "We adjust the option initial prices to account for transaction costs following the evidence presented by Muravyev and Pearson (2020). We consider a ratio of effective to quoted spread, ESPR/QSPR, equal to 30%. ... We find that even net of transaction cost **16 trading strategies still have significant returns**. For example, the net average monthly return to the RV−IV strategy is still 1.73% (*t*-statistic = 14.94)." (p.1792)

> "**Internet Appendix Figure IA1** shows that **net of transaction cost alphas from the IPCA model are negative for all strategies.**" (p.1801)

✅ **Verbatim match.** Note that the "alphas are negative for all" claim relies on the Internet Appendix (IA1), which we don't have locally yet.

---

## Drift watch — items to update if the card is re-used

- **Stock-price IPCA alpha: 0.09%, not 0.15%.** Explained share is 94.8%, not 91%.
- The paper is now *published in RFS 38(6) 1783–1821, 2025* — not a "working paper" any more. Cite the RFS version.
- The four-step framing collapses two distinct paper arguments — (a) IPCA explains alpha, and (b) RV−IV is the dominant characteristic — into "the first factor is RV−IV". Technically the first IPCA factor is *latent*, not directly RV−IV; what's correct is that the F1 column of Γ_β places its largest mass on RV−IV (Figure 2, panel 1), and the F1 *return* time series correlates strongly with the RV−IV managed-portfolio return (Figure 4, panel 1). The structural statement (Γ_β-zeroing experiment) is the cleanest single-sentence version of the claim.
