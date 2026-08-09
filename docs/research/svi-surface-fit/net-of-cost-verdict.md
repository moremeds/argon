# SVI Residual — Net-of-Cost Verdict (defined-risk vertical) — 2026-08-08

Follow-on to [`residual-edge-test.md`](./residual-edge-test.md). That test measured the
residual's *reversion* and then asserted the trade died on commissions — using a
per-share vega against a per-contract commission, a **100× unit error**. This one builds
the actual position and prices it.

**Verdict: CONFIRMED DEAD — but for a completely different reason than the one on file.**

The residual does not die at the cost line. It dies before it: **the faithful
"fade-the-mispricing" vertical loses money gross, at zero assumed spread.** The one
variant that makes money makes it from **delta, not vol** — its volatility component is
negative even where theta is a tailwind.

Costs were never the binding constraint. The 100× error made the original conclusion
right by accident.

## What the two structures are

At origin *i* the signal reads **only** date *i*: fit raw-SVI, take the strike with the
largest |residual| ≥ threshold, fade it (rich → sell, cheap → buy). Enter at *i+1*, exit
at *i+1+h*. Risk is defined by a second leg further OTM — no naked shorts.

| variant | hedge strike | median width |
|---|---|---|
| `naive` | nearest listed strike further OTM — pure risk definition | 5.0 |
| `resid` | within 6%, the strike with the most favourable residual — capture both legs | 20.0 |

`resid` is the structure options-eye's `_find_balanced_partner` gropes toward (it pairs on
delta symmetry and ignores residual sign; this is the stronger version of that idea).

## Results — 43,261 trades, 3,831 smiles, 6 liquid names, 2025-12-26 → 2026-08-07

Zero assumed spread; commission only ($0.65 × 2 legs × 2 sides). Dollars per 1 spread.

| variant | thr | h | n | gross $ | net $ | **vol-only $** | directional $ | hit |
|---|---|---|---|---|---|---|---|---|
| naive | 1.0 | 1 | 3374 | +1.70 | −0.90 | **−7.20** | +8.90 | 0.444 |
| naive | 1.5 | 2 | 2581 | −11.60 | −14.20 | **−16.82** | +5.22 | 0.434 |
| naive | 2.0 | 5 | 1366 | −50.16 | −52.76 | **−40.16** | −10.00 | 0.411 |
| resid | 1.0 | 1 | 3307 | +38.68 | +36.08 | **−45.01** | +83.69 | 0.567 |
| resid | 1.0 | 5 | 3133 | +118.47 | +115.87 | **−2.93** | +121.40 | 0.551 |
| resid | 1.5 | 2 | 2556 | +41.31 | +38.71 | **−72.14** | +113.45 | 0.550 |

Full 18-config × 9-spread-level grid in `net_of_cost_sweep.csv`; all 43,261 trades in
`net_of_cost_trades.csv.gz` (gzipped — 8.8 MB raw; `gunzip -c` to read).

**`naive`: negative gross in 8 of 9 configs.** The ninth (+$1.70) is erased by
commission. There is no assumed spread — not even zero — at which it clears. Hit rate
sits at 0.41–0.45, i.e. below a coin flip.

**`resid`: profitable, and it is not the residual doing it.**

## Why `resid` is a mirage

`vol-only $` reprices both legs at exit IV but **entry forward**, stripping the
directional move. Aggregated over all 21,456 `resid` trades:

```
mean gross   = +52.49     <- looks like an edge
mean vol-only= -50.76     <- the thesis component LOSES
directional  = +103.25    <- all of it, and more, is delta
```

The mechanism is visible in the widths: `resid` selects spreads with median width **20.0
vs `naive`'s 5.0**. Pairing on residual extremity pushes the hedge leg far away, and a
wide vertical carries real delta. Over a mostly-rising 7-month window that delta paid.

**The theta objection, answered.** Vol-only includes time decay, so a long-premium book
could show negative vol-only through theta bleed alone. Restricting to **credit** spreads
only — where theta is a *tailwind* — `resid` vol-only is still **−$15.30** (n=13,056). The
convergence genuinely fails; it is not a decay artifact. For contrast, `naive` credit-only
vol-only is **+$60.06**, which is theta collection, not residual convergence — and `naive`
still loses overall once its debit half is included.

## Real spread anchor (built, though the verdict no longer needs it)

`option_surface_grid_daily` carries no bid/ask and UW 403s per-strike history, so the
historical spread is **unrecoverable**. Measured instead from the one place argon banks
real quotes — `vrp_macro_entry_quote`, `source='xenon_ib'`, live IB NBBO:

| n=7,646 SPX quotes, 36 dates, 2026-06-25→08-07 | p25 | **p50** | p75 | p90 |
|---|---|---|---|---|
| all legs | 0.059 | **0.072** | 0.098 | 0.142 |
| near-money (`short_*`) | 0.055 | **0.066** | 0.086 | — |
| wings (`wing_*`) | 0.064 | **0.080** | 0.118 | — |

`spread_vp = 100 × (ask − bid) / vega` (vega stored per-share per-1.00-vol, so the
contract multiplier cancels — this is directly comparable to the sweep's axis). The
0.06 vp SPY figure in the original test sits on the near-money median, confirming its
vol-point work was sound; only its dollar paragraph was wrong.

## Limits

- **Sharpe is not load-bearing here.** 154 dates ≈ 9 monthly buckets → SE ≈ √(12/9) ≈
  **1.15**. No individual Sharpe in the sweep is significant. The verdict rests on mean
  dollars over 21k+ trades per variant, which needs no monthly bucketing.
- **Prices are UW marks, and the mark-noise floor is still unmeasured.**
  `iv_source_validation` holds 6,520 rows with `uw_iv` 100% populated and **`ib_iv` 0%**
  across 2026-06-22 → 08-07 — the IB canary has never once written its side, contrary to
  the prediction in `residual-edge-test.md` that the 2026-07-04 worker restart would fix
  it. Root cause undiagnosed. Note this cuts *toward* the verdict: mark noise inflates
  apparent convergence, and the trade still does not pay.
- **One regime.** 2025-12-26 → 2026-08-07 only. `resid`'s directional P&L is a bet on
  that window's drift and would flip in a selloff.
- **Spread anchor is SPX**, the panel is SPY/QQQ/NVDA/AAPL/TSLA/MU. Irrelevant to this
  verdict (`naive` fails at zero spread) but it does mean the break-even columns for
  `resid` are not calibrated to the panel. Re-measure during RTH if that ever matters.
- Trades are one-per-(ticker, expiry, date, config) — the single best strike — so
  same-smile strikes are not double-counted. Signal→entry gap is p50 1 / p90 3 calendar
  days (weekends), max 4; no silently stretched horizons.

## Bottom line

Two independent structures, 43k trades, and the residual pays in neither. The
mean-reversion measured in 2026-07 is real (autocorr 0.56) and still untradable — a
market-maker's edge, as originally concluded. What changes is *why*: not "commissions
exceed a \$0.18 edge" (that figure was 100× wrong), but that a two-legged defined-risk
version of the trade has no gross edge to begin with, and the pairing scheme that appears
to rescue it is selling delta exposure in disguise.

**Do not build the residual→signal layer.** The 2026-07 recommendation stands; this
supersedes its reasoning. Nothing here bears on the *other* open idea — RND shape-distance
(Wasserstein) as a VRP kill-switch — which is a different signal on the same surface.

## Reproduce

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
UW_SCAN_ALLOW_DB_MISMATCH=1 \
uv run python -m scripts.research.svi_residual_net_of_cost      # -> net_of_cost_{trades,sweep}.csv
uv run python -m scripts.research.svi_residual_spread_anchor    # -> spread_anchor_{quotes,summary}.csv
uv run pytest tests/unit/scripts/test_svi_net_of_cost_smoke.py  # money-path checks
```

Zero UW/IB calls — banked tables only. `CONTRACT_MULTIPLIER = 100` is a named constant in
the probe and pinned by test, so the original unit error cannot recur silently.
