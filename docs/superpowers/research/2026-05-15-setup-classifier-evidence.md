# Setup Classifier Evidence Note

Date: 2026-05-15

## Summary

The old `C-BULL` / `C-BEAR` classifier used option-flow direction and then gated that direction with IV rank:

- bull required `iv_rank >= 70`
- bear required `iv_rank <= 30`

That IV-rank direction gate is not well supported by the research reviewed. The stronger evidence supports using signed option demand as the directional input, while treating IV rank as volatility/structure context.

## Evidence

| Signal | Evidence read | Implementation implication |
|---|---|---|
| Buyer-initiated option flow | Pan and Poteshman find option volume initiated by buyers to open positions contains information about future stock returns; low put-call option-volume signals outperform high put-call signals over next-day and next-week horizons. | Keep signed option flow as the primary direction input. |
| Options as informed-trading venue | Easley, O'Hara, and Srinivas model and test conditions where informed traders choose the options market. | It is reasonable to screen for unusual directional option demand, but still treat it as a hypothesis. |
| Call-vs-put expensiveness | Cremers and Weinbaum find deviations from put-call parity contain information about future stock returns; relatively expensive calls outperform relatively expensive puts. | Direction should come from call/put demand or relative option richness, not from overall IV rank. |
| Net buying pressure and IV | Bollen and Whaley find net buying pressure affects implied-volatility surfaces; for single-stock options, call demand is especially important for stock option IV changes. | IV response is useful context, but it should not be a hard directional veto. |
| VRP | Bollerslev, Tauchen, and Zhou support variance-risk-premium return predictability at aggregate horizons, with important measurement constraints. | VRP is useful as a confluence/volatility feature, not a standalone bull/bear label. |
| GEX / dealer hedging | Ni, Pearson, Poteshman, and White support a non-informational dealer-hedging channel affecting return volatility and large-move probability. | GEX belongs in confluence/regime context; simple thresholds need local validation. |

## Formula Update

Direction remains signed option premium:

```text
net_premium = net_call_premium - net_put_premium
direction = bull if net_premium >= 0 else bear
```

For single-stock reports, the equivalent is:

```text
net_premium = bull_premium - bear_premium
direction = bull if net_premium >= 0 else bear
```

The classifier now requires material and clean flow:

```text
abs(net_premium) >= 5,000,000
flow_imbalance = abs(net_premium) / total_directional_premium
flow_imbalance >= 20%
```

IV rank is retained as confirmation text or warning context, but it no longer blocks a setup. This is intentional: IV rank describes whether the option surface is rich or cheap relative to history, which should guide structure selection, not decide directional sign.

## Current Limits

The features are evidence-backed, but the exact production thresholds are still hypotheses:

- `$5M` absolute premium
- `20%` flow imbalance
- `GEX/OI > 0.01`
- `abs(VRP) > 0.05`
- `relative_volume > 1.5`
- `abs(flow polarization) > $50M`

These should be validated against persisted scan snapshots with forward 1d / 5d / 20d returns, max adverse excursion, realized volatility change, IV/RV spread change, and candidate option P/L where legs are available.

## References

- Pan, J. and Poteshman, A. M. (2004), "The Information in Option Volume for Future Stock Prices", NBER Working Paper 10925: https://www.nber.org/system/files/working_papers/w10925/w10925.pdf
- Easley, D., O'Hara, M., and Srinivas, P. S. (1998), "Option Volume and Stock Prices: Evidence on Where Informed Traders Trade", Journal of Finance: https://doi.org/10.1111/0022-1082.194060
- Cremers, M. and Weinbaum, D. (2010), "Deviations from Put-Call Parity and Stock Return Predictability", JFQA: https://doi.org/10.1017/S002210901000013X
- Bollen, N. P. B. and Whaley, R. E. (2004), "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?", Journal of Finance: https://www.whaley.info/_files/ugd/1362e1_81f94ba850fb4ec4aea173770b355408.pdf
- Bollerslev, T., Tauchen, G., and Zhou, H. (2009), "Expected Stock Returns and Variance Risk Premia", Review of Financial Studies: https://academic.oup.com/rfs/article-pdf/22/11/4463/24429122/hhp008.pdf
- Ni, S. X., Pearson, N. D., Poteshman, A. M., and White, J. S. (2021), "Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?", Review of Financial Studies: https://academic.oup.com/rfs/article-pdf/34/4/1952/36683417/hhaa082.pdf
