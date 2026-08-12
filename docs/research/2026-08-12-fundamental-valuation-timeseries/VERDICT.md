# VERDICT — a name's own valuation DOES time that name, where its own quality does not

*2026-08-12 · hand-written · numbers in `valuation_timeseries.json` / `results.md` · reproduce:*

```bash
uv run python scripts/research/fundamental_valuation_timeseries.py
```

247 tickers · 17,005 observations · statements from `uw_scan.fundamental_statement_obs`,
prices from the local lake mirror.

## The headline

**Positive, and it survives the control that should have killed it.** Within one
name, across its own history, cheapness precedes strength — market-neutral, at
both horizons, on both return and drawdown.

| signal | 2q IC (dm) | t | holding reversal | t | hit rate |
|---|---:|---:|---:|---:|---:|
| `sales_to_ev` | **+0.0744** | **5.77** | **+0.0826** | **7.28** | 0.683 |
| `fcf_yield` | +0.0457 | 3.64 | +0.0514 | 4.18 | 0.603 |
| `ebitda_to_ev` | +0.0446 | 3.41 | +0.0566 | 4.80 | 0.606 |
| `book_to_price` | +0.0356 | 2.83 | +0.0551 | 4.95 | 0.555 |
| `earnings_yield` | +0.0329 | 2.56 | +0.0407 | 3.38 | 0.591 |
| `neg_past_ret` *(control)* | +0.0353 | 2.60 | — | — | 0.587 |

Every signal is a yield, so high = cheap and the anchor band's `buy_below` needs
a positive IC. All five deliver one.

## This is the question the anchor band asks, and it had no answer

§7 puts `buy_below / observe_low / observe_mid / observe_high / risk_above` on
the card. Read literally, `buy_below` asserts that when a name is cheap versus
its own norm, its own forward return is better. Nothing measured before this
tested that, and the two nearest results both pointed away from it:

- **Cross-sectionally, value is inverted here.** `book_to_price` IC −0.0365
  (t −2.32), `earnings_yield` −0.0194. Cheap names underperformed their peers.
- **Within-ticker, quality is null.** The composite carries nothing about a
  name's own forward return once de-marketed (−0.0047, t −0.41), and that test
  was powered.

Neither is this test. The first ranks names against each other; the second uses
quality, not price. Both were reasonable grounds to expect a null — and the null
did not arrive.

## Why the obvious explanation is not the explanation

Each signal is fundamental/price: a TTM numerator that moves once a quarter over
a denominator that moves every day. Most within-ticker variation in a
"valuation" z-score is therefore **price** variation — the stock falls, the
yield rises, the name reads cheap. If prices mean-revert at all, that
construction predicts forward returns mechanically with the fundamental
contributing nothing. Short-horizon reversal is among the best-documented
effects in equities, so this was the default explanation, not a remote risk.

`neg_past_ret` is that explanation as a signal: pure trailing 2q return, negated,
no fundamental input, pushed through the identical pipeline. It was expected to
absorb the result.

**It did not.** Reversal earns a real but smaller +0.0353, and holding it
constant makes every valuation signal **stronger, not weaker** — `sales_to_ev`
goes from +0.0744 to +0.0826, `book_to_price` from +0.0356 to +0.0551. Reversal
is mildly *suppressing* the valuation effect, not producing it.

One more discriminator, and the cleanest of them: **reversal does not predict
drawdown at all** (dd IC +0.0014, t 0.10) while every valuation signal does
(+0.0247 to +0.0522, t up to 4.29). Two signals that were the same thing wearing
different labels would not diverge on a second outcome.

## The asymmetry the card has to encode

| within one name, against its own history | IC (2q, de-marketed) | verdict |
|---|---:|---|
| fundamental **quality** (the composite) | −0.0047 (t −0.41) | absent, and powered |
| fundamental **valuation** (`sales_to_ev`) | +0.0744 (t 5.77) | present, survives control |

Same harness, same de-marketing, same 2q horizon, same universe. The harness
returns a null when handed the composite, which is what makes the positive here
worth reading — it is not a pipeline that manufactures findings.

**Product consequence, stated as a rule:**

- **Subscore trajectories stay descriptive.** No price consequence may be drawn
  from them. Unchanged by this result.
- **The anchor band may be prescriptive.** `buy_below` has measured support at
  the horizon the card speaks to, on the basis four of the five spec methods
  already use (§5.3 routes `chips_cyclical`, `software_growth` and
  `high_risk_growth` through EV/Sales — the strongest signal measured here — and
  `platform_scale` through an FCF multiple, the second).
- **The band is an own-history percentile, never a cross-sectional one.** The
  cross-sectional value inversion is still on the record. A `buy_below` computed
  by ranking this name against other names would point at the wrong half of the
  panel; computed against the name's own history it does not. Same word, two
  different quantities, opposite signs.

## Limits, standing

1. **Survivorship.** Prices resolve for 254 of 257 tickers *currently* in the
   store — names that got cheap and then died are absent by construction. This
   biases "cheap precedes strength" upward and no run of this script can fix it;
   it needs a delisted-name price source. Carried forward as the same limit the
   cross-sectional work already carries.
2. **t-stats are optimistic.** The unit is the ticker, and 247 tickers are not
   247 independent observations even after de-marketing. Read t 7.28 as "clearly
   non-zero", not literally.
3. **Uncosted.** No spread, no turnover. `fundamental_cost_turnover.py` measured
   those for the cross-sectional ranking; this signal has not been through it.
   An own-history multiple z-score rebalances on filings, so its turnover should
   be far lower than a cross-sectional rank — but "should be" is not a
   measurement.
4. **Not a strategy.** This licenses a *band on a card* — a defensible range with
   spot marked against it. It is not a backtested rule, has no sizing, and no
   position exists behind it.

## What this unblocks

The ANCHOR stage (`valuation_anchors`, spec §5.3) proceeds, and its five levels
may carry their prescriptive names. Build order follows the measured strength:
EV/Sales first, since it is both the strongest signal and the basis three of the
five company types route through.
