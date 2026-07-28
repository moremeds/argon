# Theta Harvester — weight sweep and control arm

**Date:** 2026-07-29
**Data:** `option_wizard` (mini), 145 sessions 2025-12-26 → 2026-07-27, 114 tickers,
16,134 candidates, 13,890 terminal (at-expiry) marks.
Terminal marks end 2026-07-09 because later entries have not expired yet.
**Sweep run:** `uw_scan.backtest_sweep_runs.run_id = 1`, strategy
`theta_harvester_weights`, 291 configs, 0 errors.

**Reproduce:**

```bash
# 1. replay candidates + markouts (writes to the DB under UW_SCAN_DB_*)
uv run python scripts/backfill/theta_harvester_backfill.py
# 2. sweep
uv run python scripts/research/theta_harvester_weight_sweep.py
```

---

## Verdict

**The score orders. It does not, on its own, make money.**

The cross-sectional IC is positive, sizeable relative to its dispersion, and
robust across the whole weight grid — the score genuinely ranks strangles
within a session. But the set it selects still has a roughly flat-to-negative
absolute return once months are equal-weighted. Treat it as a ranking signal
feeding a human decision, not a strategy.

Two secondary findings are more actionable than the headline:

1. **Short strangles held to expiry LOST money over this window.** The
   unconditional control returns −0.00801 of spot per trade (monthly
   equal-weighted) at Sharpe −1.67 over 13,890 trades. "Short vol pays" was
   *not* the null here — which makes the score's job avoiding losers rather
   than finding winners, and makes a positive markout a real result rather
   than a restatement of the regime.
2. **The dealer-support gate inverts the score.** Every config that makes it
   critical has a negative IC; every config that does not has a positive one.

---

## Named configs

| Config | Trades | IC | t | IC sessions | Monthly mean ret | Sharpe | Months | Holdout mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `unconditional` | 13,890 | — | — | 0 | −0.00801 | −1.67 | 8 | +0.00886 |
| `radon` | 347 | **−0.0520** | −1.79 | 34 | +0.01304 | 2.23 | 3 | +0.04105 |
| `default` | 2,636 | **+0.0751** | 6.35 | 130 | −0.00035 | −0.05 | 8 | +0.02929 |

`unconditional` has no IC by construction — the control arm has no score, so
there is no ordering hypothesis to test.

None of the three survives the walk-forward gate. With 8 months the gate is
close to decorative; it is reported rather than leaned on.

**radon's Sharpe of 2.23 is the trap this sweep was built to expose.** It is
the best Sharpe in the table and it sits on 3 months and 347 trades, selected
by a gate that truncates history to the GEX era. Its IC over the same rows is
*negative*: radon's shipped weights order candidates backwards. Reading the
Sharpe alone would have promoted an inverted signal.

The reweight is therefore vindicated on the primary metric — `default` moves
the IC from −0.052 to +0.075 — while conceding that the reweighted score's
selected set is still not profitable on its own.

## Robustness across the grid

288 grid configs plus the 3 named. Split by the one flag that matters:

| `dealer_gate_critical` | Configs | IC min | IC mean | IC max | Positive IC | Avg sessions |
|---|---:|---:|---:|---:|---:|---:|
| `false` | 145 | +0.0590 | +0.0714 | +0.0878 | **145 / 145** | 130 |
| `true` | 145 | −0.0896 | −0.0589 | −0.0405 | **0 / 145** | 34 |

The positive IC is not a knife-edge tuned into existence: it holds for every
single weighting tried, across a 3x range of `vol_edge` and every threshold.
That is the strongest thing in this document. A result that survives 145
perturbations of its own parameters is not a fit.

Top configs by IC (≥100 IC sessions, ≥500 trades):

| vol_edge | delta_neut | range | sat | thresh | IC | t | Monthly mean ret | Trades |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 25 | 25 | 10 | 20 | 50 | 0.0878 | 7.37 | **+0.00274** | 777 |
| 25 | 25 | 10 | 15 | 50 | 0.0837 | 7.14 | +0.00230 | 1,301 |
| 40 | 25 | 10 | 20 | 50 | 0.0818 | 6.86 | −0.00040 | 2,451 |
| 40 | 25 | 10 | 20 | 60 | 0.0818 | 6.86 | +0.00109 | 1,397 |
| 55 | 25 | 10 | 20 | 70 | 0.0793 | 6.45 | +0.00076 | 1,491 |

The best config is positive on absolute return (+0.274% of spot per trade over
777 trades). **This is the best of 288 and must be read as such** — with 8
months and one regime, the top of a 288-config grid is where selection bias
lives. It is recorded because the sweep must be reported in full, not because
it is a recommendation. 105 of 237 scored configs have a positive monthly mean.

## The dealer gate is harmful, not merely unsupported

The naive comparison is confounded: the `true` arm sees 34 sessions and the
`false` arm 130, because strike-level GEX only starts 2026-05. A matched-sample
re-run on the GEX-covered sessions only:

| Sample | Gate | IC | t | Sessions | Trades | Raw mean ret |
|---|---|---:|---:|---:|---:|---:|
| All sessions | OFF | +0.0751 | 6.35 | 130 | 2,636 | −0.01262 |
| All sessions | ON | −0.0537 | −1.63 | 34 | 107 | −0.01199 |
| GEX-covered | OFF | +0.0293 | 1.41 | 38 | 393 | +0.00537 |
| GEX-covered | ON | −0.0537 | −1.63 | 34 | 107 | −0.01199 |

The sign flip survives matching: on the same sessions the gate takes the IC
from +0.029 to −0.054. Both matched t-stats are under 2, so this is
directional evidence rather than proof — but nothing here argues for making
the gate critical, and the default (`dealer_gate_critical=False`) stands.

The matched rows also expose a regime split worth remembering: the GEX-covered
period (May onward) had a *positive* unconditional return (+0.00437) while the
full window is negative. The earlier months are where the losses live.

Note the two mean-return columns are not comparable: the sweep equal-weights
months, the matched table above is a raw trade mean. `default` reads −0.00035
monthly but −0.01262 raw, which says the losses concentrate in months with many
candidates. Monthly equal-weighting is the honest one — 60 candidates in a
month are ~60 views of one market, not 60 independent bets.

## What would change the verdict

- **More history.** 8 months, one broad regime. The IC's t-stat of 6.35 is
  computed over overlapping sessions (a 30-day hold spans ~21 of them), so it
  is a screen, not a p-value. A proper overlapping-window correction would cut
  it materially.
- **Costs.** Every mark is Black-Scholes from grid IV. A short strangle pays
  two bid-ask spreads at entry and, if managed, two more at exit. An IC of
  0.075 on a spot-normalised return of ~0.3% is inside plausible spread cost
  for the less liquid names in the universe.
- **Same-close entry.** Candidates are built from a session's closing surface
  and entered at that same close — a lookahead no live trade has.

## Constraints carried by every number above

- **Survivorship.** The universe is today's watchlist; argon stores no
  membership history. Names dropped mid-window are absent, which runs
  optimistic.
- **European settlement on American options.** Early assignment would have
  closed short legs sooner and usually worse, so terminal P&L is an optimistic
  bound on the loss.
- **Corporate-action guards.** 174 of 16,373 ticker-sessions (KLAC, KORU,
  CRWD) are dropped at entry where the back-adjusted OHLC scale disagrees with
  the as-traded strike scale, plus 9 terminal marks dropped for a split between
  entry and expiry. Both guards trim large fabricated losses, so both are
  mildly optimistic. See `load_spot` and `MAX_SETTLEMENT_MOVE`.
- **Not a strategy return.** No bid-ask, no slippage, no position sizing, no
  management rule. Model P&L on a fixed structure held to expiry.
