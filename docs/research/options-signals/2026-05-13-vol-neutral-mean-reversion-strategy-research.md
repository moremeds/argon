# Research note: volatility-neutral and mean-reversion strategies from Volatility Tab v2

**Date:** 2026-05-13
**Context:** Follow-on strategy research for the historical Volatility Tab v2 design.

## Short answer

Yes. Volatility Tab v2 creates the right persisted inputs for research into:

- single-name volatility risk premium mean reversion;
- defined-risk short-premium and long-premium variants;
- delta-hedged or near-delta-neutral volatility trades;
- relative-value long-cheap-vol / short-rich-vol pairs;
- dispersion-style basket research, once scanner-level cross-stock ranking exists.

It does **not** create a production strategy by itself. The tab gives daily features and visual diagnostics. A trade module still needs option-chain selection, Greeks, bid/ask quotes, liquidity filters, earnings/event filters, margin/risk limits, and P&L simulation.

## Feature inputs that matter

From the Volatility Tab v2 spec and current deriver code, the useful persisted series are:

| Field | Table / panel | Strategy use |
|---|---|---|
| `vrp_daily.vrp` | VRP spread | Raw implied minus realized volatility gap. |
| `vrp_daily.vrp_z_20` | VRP spread | Mean-reversion trigger for rich/cheap volatility. |
| `stock_analytics_daily.iv_of_iv_20` | IV / IV-of-IV | Vol-of-vol stability and sizing filter. |
| `stock_analytics_daily.rvol_21` | RV / SPY corr | Realized volatility state. |
| `stock_analytics_daily.rvol_pctile` | Regime quadrant | Quiet vs active realized-vol filter. |
| `stock_analytics_daily.spy_corr_21` | Regime quadrant | Systemic vs idiosyncratic filter. |
| `divergence = iv_z - rv_z` | Divergence overlay | IV/RV dislocation trigger. |
| `iv_smile_snapshots` | Smile chart | Strike/expiry selection and skew sanity check. |
| `iv_term_snapshots` | Term structure | Calendar/event-risk filter. |

The key limitation: these are daily analytical features, not executable option prices. They are enough for signal research and approximate backtests, but full options P&L needs tradable contract history.

## Research anchors

### Volatility risk premium

Carr and Wu define variance risk premium as the spread between risk-neutral expected variance and realized variance, approximating the risk-neutral leg with option portfolios. The Volatility Tab v2 `iv - rv` field is a simpler IV/RV proxy, not a model-free variance swap replication, but it points in the same direction: option-implied volatility can be systematically high or low relative to subsequent realized volatility.

Bakshi and Kapadia connect volatility risk premium to delta-hedged option returns. Their result is directly relevant: if bought delta-hedged options tend to underperform when volatility risk premium is negative, then selling options can earn premium, but the compensation is for bearing volatility and jump risk.

Goyal and Saretto are the closest cross-sectional anchor for this project. They sort stocks on the difference between historical realized volatility and ATM implied volatility, then test straddles and delta-hedged calls/puts. That maps cleanly to `vrp_z_20`, `iv`, `rv`, smile snapshots, and future option-chain histories.

### Correlation and dispersion

Driessen, Maenhout, and Vilkov compare implied correlations from index and component options against realized correlations. That is the proper dispersion-trading framework. Volatility Tab v2 does not yet compute implied correlation, but `spy_corr_21` and the regime quadrant are a useful realized-correlation proxy for deciding whether a single name is behaving idiosyncratically or systemically.

### Mean reversion

Gatev, Goetzmann, and Rouwenhorst provide the classic equity pairs-trading template: find relative-value dislocations, enter when spreads diverge, exit on convergence, and model transaction costs. Avellaneda and Lee generalize this into market-neutral statistical arbitrage using PCA or ETF residuals as mean-reverting processes. For this repo, the same idea can be applied to volatility features: pair rich-vol names against cheap-vol names within sector, beta, or correlation buckets.

### Textbook / practitioner references

Hull is the baseline reference for option Greeks, trading strategies, volatility smiles/surfaces, and estimating volatilities/correlations. Sinclair is the more practical volatility-trading reference for realized vs implied volatility, hedging, position sizing, and variance-premium trading.

## Trade research ideas

### 1. Defined-risk VRP short-premium mean reversion

**Thesis:** when IV is rich relative to RV and the realized regime is quiet, sell defined-risk premium and expect VRP to compress.

**Entry:**

- `vrp_z_20 >= +1.5` or `+2.0`;
- `divergence >= +1.0`, meaning IV is high versus its own history while RV is not confirming;
- `rvol_pctile < 50`;
- `spy_corr_21` below the ticker's trailing median, preferably `GOLDILOCKS`;
- `iv_of_iv_20` not in its top quartile, unless sizing is reduced.

**Structures:**

- iron condor around expected range;
- short iron butterfly when price is pinned near strong GEX/max-pain structure;
- covered call or cash-secured put variant when directional inventory is allowed;
- avoid naked short straddles/strangles under the project's no-naked-shorts rule.

**Exit:**

- `vrp_z_20 <= +0.5`;
- 50% to 70% of max premium captured;
- `rvol_pctile` jumps above 70;
- `iv_of_iv_20` spikes;
- term structure flips into event backwardation.

**Main risk:** the strategy is short gamma, short vega, and short jump risk. It should be blocked around earnings, FDA, macro, merger, or known binary events unless the trade is explicitly event-designed.

### 2. Cheap-vol long-premium mean reversion

**Thesis:** when IV is cheap relative to RV and realized volatility is rising, buy convexity or long vega.

**Entry:**

- `vrp_z_20 <= -1.5` or `-2.0`;
- `divergence <= -1.0`;
- `rvol_pctile >= 50` or rising quickly;
- `iv_of_iv_20` rising from a low base;
- smile and term structure do not show obvious one-day data distortion.

**Structures:**

- debit straddle or strangle at 20 to 45 DTE;
- long call/put spread if directional flow and market-structure panels agree;
- long calendar if front vol is cheap and back vol is stable;
- backspread when skew makes wings relatively cheap.

**Exit:**

- `vrp_z_20 >= -0.5`;
- IV expands enough to pay for the trade;
- realized-vol regime fails to persist;
- time stop at 30% to 50% of DTE consumed.

**Main risk:** cheap options can stay cheap, and realized movement may not arrive before theta decay dominates.

### 3. Delta-neutral gamma scalp candidate

**Thesis:** when IV is cheap but realized volatility is already active, buy gamma and delta-hedge. This is closer to a volatility-neutral trade than a directional option bet.

**Entry:**

- `vrp_z_20 < -1.0`;
- `rvol_pctile > 60`;
- `iv_of_iv_20` stable or rising gradually;
- no event cliff where IV crush is the dominant risk;
- liquid ATM contracts with tight spreads.

**Structure:**

- long ATM straddle or strangle;
- rebalance delta daily or when absolute delta breach exceeds a threshold;
- size by dollar gamma or max premium at risk.

**Backtest requirement:** this cannot be evaluated honestly from daily IV/RV features alone. It needs option Greeks, contract prices, re-hedge rules, stock slippage, and funding assumptions.

### 4. Relative-value volatility pair

**Thesis:** buy cheap volatility and sell rich volatility across similar names, hedged to dollar vega and approximate beta/correlation exposure.

**Entry:**

- choose same sector/theme names;
- long leg: `vrp_z_20 <= -1.0`;
- short leg: `vrp_z_20 >= +1.0`;
- both legs have comparable DTE, liquidity, and no mismatched binary events;
- `spy_corr_21` and realized beta are similar enough to reduce market-regime mismatch.

**Structures:**

- long straddle vs short defined-risk iron fly;
- long debit spread vs short credit spread if directional bias exists;
- vega-neutral straddle pair once naked short constraints are handled through defined-risk wrappers.

**Exit:**

- spread between the two `vrp_z_20` values converges by 50%;
- one leg hits event-risk stop;
- realized correlation regime changes sharply.

**Main risk:** the two names can diverge for good fundamental reasons. The backtest needs sector, earnings, and idiosyncratic-news controls.

### 5. Dispersion-lite research basket

**Thesis:** sell broad market or ETF volatility and buy selected single-name volatility when realized correlations are low and idiosyncratic movement is likely. Classical dispersion needs implied correlation; this repo currently only has realized stock-SPY correlation.

**Candidate filter:**

- universe names with low `spy_corr_21`;
- high `rvol_pctile` but not systemic panic;
- single-name IV not already too rich;
- avoid names with structurally illiquid options.

**Implementation path:**

- start as scanner research, not single-stock tab logic;
- add SPY/QQQ/IWM option IV and realized correlation baskets;
- estimate implied correlation from index variance and component variances;
- backtest long single-name gamma / short ETF gamma with dollar-vega neutrality.

**Main risk:** without implied correlation, this is only a realized-correlation screen. It can identify candidates, but not price the dispersion edge.

### 6. IV-of-IV compression filter

**Thesis:** high IV relative to RV is more attractive for short premium when vol-of-vol is falling or stable. High and rising `iv_of_iv_20` means the option market is unstable, so a rich VRP signal may be a warning rather than an edge.

**Use:**

- allow normal short-premium sizing only when `iv_of_iv_20` is below its trailing 60-day median or falling for 3 to 5 sessions;
- halve size when `iv_of_iv_20` is high but declining;
- block new short-gamma entries when `iv_of_iv_20` is high and rising.

**Backtest:** compare VRP short-premium results with and without the IV-of-IV filter. This is likely one of the cleanest first experiments because it uses only persisted series plus option spread assumptions.

## Backtesting roadmap

### Phase A: feature-only signal validation

Goal: prove the persisted features have predictive value before modeling options.

Tests:

- Does high `vrp_z_20` predict lower future IV, lower future VRP, or lower realized variance over 5/10/20 sessions?
- Does low `vrp_z_20` predict higher future IV, higher realized movement, or profitable long-vol windows?
- Does `divergence` add signal beyond raw `vrp_z_20`?
- Does `iv_of_iv_20` improve drawdown or hit rate by filtering bad short-vol entries?
- Do `GOLDILOCKS`, `STOCK_PICKER`, `FRAGILE_CALM`, and `SYSTEMIC_PANIC` regimes produce different forward distributions?

Metrics:

- forward change in IV, RV, and VRP;
- hit rate by quantile;
- average forward realized move vs implied move;
- conditional drawdown during signal windows;
- information coefficient by horizon.

This phase needs only the Volatility Tab v2 tables and avoids option-pricing assumptions.

### Phase B: synthetic option backtest

Goal: estimate whether signal direction survives after option-like payoff, decay, and spread costs.

Required data:

- `iv_smile_snapshots`;
- `iv_term_snapshots`;
- underlying close history;
- rates/dividend assumptions;
- model pricing, initially Black-Scholes for simplicity;
- conservative bid/ask and slippage model.

Candidate strategies:

- 30-DTE short iron condor on high `vrp_z_20`;
- 30-DTE long straddle on low `vrp_z_20`;
- 20 to 45-DTE calendar on term-structure dislocation;
- vega-neutral long-cheap / short-rich pair.

Controls:

- enter at next close/open after signal timestamp;
- use only data known as of that timestamp;
- include wide spreads for illiquid names;
- block trades across earnings until earnings history is persisted;
- include early assignment and dividend risk as exclusions for short ITM options.

This phase is useful for ranking ideas, but should not be treated as tradable proof.

### Phase C: contract-level historical backtest

Goal: model actual tradeable P&L.

Required additions:

- daily option contract bid/ask/mid/open interest/volume;
- per-contract Greeks or deterministic Greek reconstruction;
- earnings and corporate-action history;
- borrow/dividend data for short-stock hedges;
- margin model for defined-risk and hedged positions.

P&L mechanics:

- mark options at bid/ask-aware prices;
- rebalance delta according to explicit rule;
- charge stock commissions/slippage and option fees;
- cap size by open interest, volume, bid/ask width, and portfolio risk;
- compute assignment/exercise handling for American options.

Metrics:

- CAGR, Sharpe, Sortino, Calmar;
- max drawdown and max one-day loss;
- expected shortfall;
- skew and kurtosis of returns;
- win rate, payoff ratio, average holding period;
- margin return and premium capture;
- exposure time series for delta, gamma, vega, theta, and correlation.

### Phase D: walk-forward scanner portfolio

Goal: test whether the feature works as a portfolio selection engine.

Design:

- train thresholds on rolling windows, never full-sample;
- rank tickers by signal strength and liquidity;
- allocate by risk budget, not equal ticker count;
- cap sector/theme concentration;
- compare against naive baselines: always-short condor, IV-rank-only, random same-liquidity trades.

Key question: does `vrp_z_20 + divergence + regime + iv_of_iv_20` outperform simpler IV-rank or IV-minus-RV rules after costs?

## Practical guardrails

- Use defined-risk short-premium structures by default.
- Treat high `vrp_z_20` as compensation for risk, not free edge.
- Block or separately label earnings and known binary events.
- Liquidity filter before signal strength: spread width, open interest, volume, and strike availability.
- Size short gamma by expected loss under a gap scenario, not by premium collected.
- Track IV crush separately from realized movement; long-vol trades can be directionally right and still lose.
- Do not use same-day close data to enter same-day close trades unless the data timestamp proves it was available.
- Require out-of-sample and walk-forward validation before moving into Trade Plan generation.

## Recommended next documents

1. `docs/superpowers/specs/vol-strategy-backtest-design.md` - exact data model, signal definitions, strategy classes, and P&L engine boundaries.
2. `docs/superpowers/plans/vol-strategy-backtest-implementation.md` - phased implementation plan: feature-only validation first, synthetic options second, contract-level P&L third.
3. `docs/research/options-signals/option-liquidity-and-event-filtering.md` - liquidity gates, earnings filters, and short-option safety rules.

## Sources

- Peter Carr and Liuren Wu, "Variance Risk Premiums," Review of Financial Studies, 2009. https://doi.org/10.1093/rfs/hhn038
- Gurdip Bakshi and Nikunj Kapadia, "Delta-Hedged Gains and the Negative Market Volatility Risk Premium," Review of Financial Studies, 2003. https://doi.org/10.1093/rfs/hhg002
- Amit Goyal and Alessio Saretto, "Cross-section of option returns and volatility," Journal of Financial Economics, 2009. https://doi.org/10.1016/j.jfineco.2009.01.001
- Joost Driessen, Pascal Maenhout, and Grigory Vilkov, "Option-Implied Correlations and the Price of Correlation Risk," SSRN. https://ssrn.com/abstract=2166829
- Evan Gatev, William Goetzmann, and K. Geert Rouwenhorst, "Pairs Trading: Performance of a Relative Value Arbitrage Rule," NBER Working Paper 7032, 1999; Review of Financial Studies, 2006. https://doi.org/10.3386/w7032
- Marco Avellaneda and Jeong-Hyun Lee, "Statistical arbitrage in the US equities market," Quantitative Finance, 2010. https://doi.org/10.1080/14697680903124632
- Tim Bollerslev, George Tauchen, and Hao Zhou, "Expected Stock Returns and Variance Risk Premia," Review of Financial Studies, 2009. https://doi.org/10.1093/rfs/hhp008
- John C. Hull, *Options, Futures, and Other Derivatives*, 11th edition, Pearson, 2022.
- Euan Sinclair, *Volatility Trading*, 2nd edition, Wiley, 2013.
