# RETURNS VERDICT — capex fails; the buyer's stock return is where the signal was

*2026-08-13 · numbers in `returns_test.json` · reproduce:*

```bash
uv run python scripts/research/capex_returns_test.py
```

The pre-registered test, decided before it ran: **if the walk-forward long/short
fails the harness's OOS gate, the capex demand ledger closes.** It failed.

## The result

Equal-weight top-quintile minus bottom-quintile, market-residualised on both
legs, sorted on each supplier's trailing 18-month sensitivity to the buyer
basket times a shock, held one month. 234 suppliers, 35 tradable months
(2021-09→2026-08 less the estimation window).

| portfolio | n | Sharpe | mean/m | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| **A — buyer return shock** | 35 | **−0.79** | −1.54% | −77% | 0.40 |
| **B — capex surprise shock** | 35 | **−0.73** | −1.44% | −66% | 0.51 |
| CTRL — sensitivity only, no shock | 35 | +0.19 | +0.38% | −33% | 0.46 |
| CTRL — shuffled owners | 35 | +0.22 | +0.23% | −21% | 0.49 |

**Both real signals lose, and both lose to both null controls.** A signal that
cannot beat its own shuffled version has not earned anything. Every row fails
the quarter gate — including the nulls — which means at n=35 the gate is not
discriminating between these candidates and the Sharpe comparison against the
controls is what carries the verdict.

## The diagnostic, and what it does and does not establish

A −0.79 Sharpe is a strong number pointing the wrong way, which usually means
something structural rather than noise. Monthly short-term reversal is among the
most robust effects in the cross-section, and "moved with an outperforming
basket" is precisely the sort it contaminates. Inserting one gap month between
signal and holding period separates the two:

| | skip 0 *(pre-registered)* | skip 1 *(post-hoc)* |
|---|--:|--:|
| A — buyer return shock | −0.79 | **+0.49** (hit 0.65) |
| B — capex surprise shock | −0.73 | −0.45 |

**A flips sign; B does not.** That is a real discrimination between the two
shocks and it matches what was predicted before the test ran: the buyer's stock
return is forward-looking and had a chance, capex is twice-stale and did not.

**It does not establish a signal.** `skip=1` was chosen after seeing `skip=0`
fail — one step of specification search, on 34 months, still failing the gate.
What it establishes is the *failure mode*: the pre-registered result is
consistent with reversal sitting on top of a weak positive effect, not with
"there is no relationship". Those need different follow-ups, which is the only
reason the diagnostic was run.

## Verdict

**The capex demand ledger closes.** Buyer capex growth does not predict supplier
returns at any horizon tested, in the specified form or the post-hoc one. That
is now measured rather than argued, and it is consistent with the mechanism
found in `ROUND2-matched-growth.md`: hyperscaler capex *follows* hyperscaler
revenue by 2–3 quarters, so by publication it is a variable the market has
already seen twice.

**The question does not close with it.** What survives is narrower and better
specified than what was started with: *the buyer basket's residual stock return,
at a one-month gap, sorted by trailing link sensitivity.* That is Cohen &
Frazzini's variable rather than ours, and their result is the reason it is worth
one more look rather than none.

## What this sample cannot decide

`daily_ohlc` holds ~5 years because massive caps history at that on our tier, so
the sample begins 2021-08 and **sits entirely inside the AI capex boom**. It
contains no downturn in the variable whose downturn would be the test. Deeper
history is expected once the mini is back online, and the script keys off
whatever `daily_ohlc` holds — re-running against a longer table needs no code
change.

So this retires the current evidence, not the question. The specific re-run worth
doing when history deepens:

1. Signal A at a one-month gap, **pre-registered this time**, over a window that
   includes 2018–2021.
2. Nulls kept in place — the shuffled-owner control is what made this round
   interpretable, since a +0.19 sensitivity-only Sharpe would have looked like a
   result without it.

## Method notes worth keeping

- **Residualised on both legs** with a trailing market beta. Without it the sort
  becomes a bet on market beta and rediscovers beta — the failure that ended the
  dark-pool lead-lag study.
- **Capex lagged uniformly to `period_end + 90 days`**, not to
  `filing_published_at`, which is present on only 51% of rows; using it where
  available would hand half the sample a timing advantage the other half lacks.
  90 days clears the p95 filing lag of 59.
- **Capex growth z-scored against its own expanding history.** Raw capex growth
  was positive in almost every quarter here, so a raw signal is a permanent tilt
  wearing a timing signal's clothes.
- **The buyer basket is one basket**, so a common shock gives every supplier the
  same number. Cohen & Frazzini get their cross-section from suppliers having
  *different* customers; here it has to come from each supplier's own estimated
  sensitivity, which is a materially weaker instrument and a live suspect for
  why the effect is thin.
