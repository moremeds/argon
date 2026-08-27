# The own-history valuation signal survives a split-consistent price basis — but four of five weaken, and two die

**Measured 2026-08-25** on `option_wizard_local`, 401 tickers loaded / 254 with
≥24 observations / 251 contributing an IC. Artifact: `rerun.json`.

Reproduce:

```bash
uv run python scripts/research/fundamental_valuation_split_basis_rerun.py
```

## What was wrong

`scripts/research/fundamental_valuation_timeseries.py` built market cap as
`RAW bronze close × common_stock_shares_outstanding`, and said why in its header:

> `adj_close` is retroactively split-adjusted while
> `common_stock_shares_outstanding` is as-reported, and multiplying the two mixes
> reference frames across every split.

**The premise is false.** The same repository already documents the correction in
`worker/jobs/fundamental_anchors.load_closes`: *"The provider restates historical
share counts onto today's post-split basis."* Re-measured here: TSLA runs
3,372M → 3,369M → 3,101M → 3,540M and BKNG 1,024M → 1,034M → 794M → 770M across
periods containing splits, with **no split-sized discontinuity anywhere**. An
as-reported series would jump by the split factor on the split date.

So the research paired a *restated* share count with an *unrestated* price, and
produced a market cap wrong by the split factor for every quarter before a split
— exactly the contamination the header believed it was avoiding. It survived
review because the reasoning is valid given the premise; only the premise was
never measured.

**Exposure is not marginal: 121 of 400 names (30.2%) had a split inside their own
statement window.**

## Method

Identical harness, identical universe, identical windows, **one** substitution:
the market-cap price becomes bronze `close` divided by the product of every split
ratio dated after it, from `uw_scan.corporate_actions`. Dividends are deliberately
*not* removed, matching production — a cash dividend genuinely lowers market cap
and nothing restates the share count for it.

The reconstruction is verified against production's own documented identity:
BKNG on 2026-04-02 returns **167.77** against a raw close of 4,194.31 and a 25.0
factor — the exact value `load_closes` documents.

Both bases run in one pass over one panel, so the comparison cannot drift on
universe, date range, or code version. Livewire's silver tier — production's
source for this basis — is **empty on this machine**, which is why the ledger was
used instead.

## Result — full panel (n=251), 2q de-marketed

| signal (expanding window) | old raw close | corrected split-only |
|---|---|---|
| **sales_to_ev** | +0.0706 (t 5.55) | **+0.0709 (t 5.55)** |
| fcf_yield | +0.0415 (t 3.34) | +0.0394 (t 3.13) |
| ebitda_to_ev | +0.0376 (t 2.87) | +0.0335 (t 2.57) |
| book_to_price | +0.0334 (t 2.68) | +0.0272 (t 2.14) |
| earnings_yield | +0.0263 (t 2.04) | +0.0217 (t 1.69) |
| control `neg_past_ret` | +0.0347 (t 2.59) | +0.0347 (t 2.59) |

## The sharp test — split-exposed names only (n=121)

An aggregate over 251 names can absorb a real distortion affecting 30% of them,
so the headline is only evidence if it holds among the names actually exposed.

| signal (expanding window) | old raw close | corrected split-only | |
|---|---|---|---|
| **sales_to_ev** | +0.0637 (t 2.92) | **+0.0651 (t 3.00)** | unmoved |
| ebitda_to_ev | +0.0734 (t 3.15) | +0.0631 (t 2.76) | weakens |
| fcf_yield | +0.0575 (t 2.92) | +0.0482 (t 2.32) | weakens |
| earnings_yield | +0.0554 (t 2.54) | **+0.0404 (t 1.90)** | **loses significance** |
| book_to_price | +0.0505 (t 2.43) | **+0.0352 (t 1.67)** | **loses significance** |

**The contamination was real, material, and directional** — it inflated four of
five signals among exposed names, and two of them do not survive correction.

## Reversal control

Every signal is `fundamental / price` with a numerator that moves quarterly and a
denominator that moves daily, so most within-ticker variation is *price*
variation and short-horizon reversal is the default explanation. Partial IC
holding pure trailing return constant, corrected basis, full panel:

| signal | partial IC |
|---|---|
| **sales_to_ev** | **+0.0772 (t 6.74)** |
| fcf_yield | +0.0449 (t 3.62) |
| ebitda_to_ev | +0.0436 (t 3.64) |
| book_to_price | +0.0457 (t 3.97) |
| earnings_yield | +0.0287 (t 2.40) |

`sales_to_ev` is **stronger** with reversal held constant, not weaker. It is not
a repackaged reversal signal.

## What this settles

1. **The `sales_to_ev` finding is not a split artifact.** A prior reading of the
   2026-08-21 contamination verdict raised the possibility that the split error
   manufactured the sign — pre-split market cap understated → looks cheap →
   post-split run-up → positive IC. Measured: it does not. The IC is identical on
   both bases, on the full panel and on the exposed cohort.
2. **All three shipped valuation methods survive.** `sales_to_ev`
   (chips_cyclical / software_growth / high_risk_growth, and the pooled default),
   `ebitda_to_ev` (power_infra), and `fcf_yield` (platform_scale) all keep their
   sign and significance on the corrected basis.
3. **`book_to_price` and `earnings_yield` should not be routed to.** They lose
   significance among exposed names once corrected. Neither is currently a
   `TYPE_YIELD` method, and this says keep it that way.

## What this does NOT establish

- **No mechanism is claimed for why `sales_to_ev` is immune while `ebitda_to_ev`
  is not.** Both are EV-denominated, so "EV dilutes the error" does not explain
  the difference. The asymmetry is measured and unexplained.
- **This licenses a WITHIN-NAME direction, not a cross-name ordering.**
  Cross-sectionally, value measured INVERTED in this same universe
  (`book_to_price` IC −0.0365, t −2.32). `/scanner/value` must keep listing and
  must never gain a sort over `spot_percentile` or band depth.
- **It licenses an ORDERING, not the price LEVEL.** A Spearman IC says cheap
  precedes strong within a name; it does not validate inverting a percentile into
  a `buy_below` price. The band's levels remain descriptive.
- **The panel is survivor-biased.** 254 of 401 names cleared the observation
  floor and the universe is active-only; delisted names are absent. That is the
  MX.A gate, untouched here.
- **One horizon, one de-marketing scheme.** 2q, cross-sectional-mean removal by
  knowledge quarter. Same convention as the sibling verdicts, deliberately.
