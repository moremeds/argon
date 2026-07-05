# SVI Residual — Edge Test (reversion + cost) — 2026-07-04

Follow-on to the feasibility gate (`README.md`). The fit is trustworthy on liquid names;
this asks the only question that matters: **is the fitted-vs-marked residual a tradable
edge?**

**Verdict: NO for a defined-risk taker. The residual is a statistically real,
mean-reverting signal — but the realizable edge is ~$0.18 per contract, smaller than a
single option commission.** It is a market-maker's edge (earn the spread), not ours.

## Three tests (the three I said an edge needs)

### 1. Residual-reversion (DB-only, 3,518 smiles, 262k contract-date pairs, liquid names)

The residual is **not noise** — it persists and mean-reverts:

| step (≈trading days) | residual autocorr | gross harvest, \|sig\|≥1vp |
|---|---|---|
| 1 (1d) | **0.560** | 0.72 vp |
| 2 (2d) | 0.423 | 0.94 |
| 3 (5d gap) | 0.335 | 1.07 |
| 5 (7d gap) | 0.233 | 1.19 |

Convergence is genuine and symmetric (h=1): a strike rich by +1.4vp decays to +0.76 next
day (~46%); >+2vp → +0.75 (~67%); the cheap side mirrors it. Autocorr 0.56 rules out pure
measurement noise (would be ≈0) and a random walk (would be ≈1) — it's a real dislocation
with a few-day half-life.

**But the harvest is unrealizable at the observed level.** You see the residual at the
close; you can only *act* later. Entering one observation-step late (signal at i, enter i+1,
exit i+2) collapses the harvest:

| entry | harvest (\|sig\|≥1) | hit-rate |
|---|---|---|
| contemporaneous (unrealizable) | 0.72 vp | — |
| **1-step-lagged (realistic)** | **0.217 vp** | 57.4% |

And it **does not scale** with signal size — bigger dislocations don't pay proportionally
more, because the largest residuals are increasingly mark-noise that doesn't survive to
entry:

| threshold | realized harvest | hit | share of pairs |
|---|---|---|---|
| \|sig\|≥1.0 | 0.217 vp | 57.4% | 11.6% |
| \|sig\|≥1.5 | 0.258 | 56.6% | 4.6% |
| \|sig\|≥2.0 | 0.275 | 55.2% | 1.2% |
| \|sig\|≥2.5 | 0.176 | 52.4% | 0.2% |
| \|sig\|≥3.0 | 0.381 (n=50) | 60% | 0.02% |

Plateaus ~0.22–0.28 vp. No juicy tail.

### 2. Cost hurdle (live IB via xenon, ATM 30d, as-of 2026-07-04 — **market closed, indicative; live likely tighter**)

| contract | bid/ask | \$ spread | vega (\$/vol pt) | **spread in vol pts** |
|---|---|---|---|---|
| SPY 20260731 C745 | 12.20 / 12.25 | 0.05 | 0.833 | **0.06** |
| QQQ 20260731 C715 | 20.13 / 20.40 | 0.27 | 0.800 | **0.34** |

The decider is **dollars, not vol points**. Realized edge 0.217 vp × SPY vega \$0.833 =
**\$0.18 per contract, gross**. IB options commission is **~\$0.15–0.65 per contract per
side** — the edge is smaller than *one* commission, before spread. A 0.2-vol-point
mispricing on a liquid option is worth pennies; per-contract taker costs are the same pennies.

- **SPY** — spread (0.06 vp) < edge (0.22 vp), the one tempting case — but killed by
  commissions (\$0.18 edge vs ≥\$0.30 round-trip commission) and by the no-naked-shorts rule:
  fading a rich strike is a naked short; the defined-risk version needs ≥2 legs, ≥2× cost.
- **QQQ / single names** — spread alone (≥0.34 vp) meets or exceeds the edge. Dead outright.

### 3. Mark-noise cross-check — **no banked data yet (canary self-heals)**

`iv_source_validation` has 1,026 rows but **every `abs_diff` is NULL**: the IB-vs-UW canary
recorded UW IV with no IB side for its whole life so far (2026-06-22→07-02), so there is no
historical IB-vs-UW disagreement series yet to characterize the mark floor. The cause is
**not** a missing key — verified on the mini, its argon `.env` holds `XENON_QUERY_API_KEY`
(URL defaults to `:8321`) and the canary's IB path returns a live quote when called there.
The pre-restart canary workers had frozen a stale, pre-key env at fork (the fork-freeze the
root CLAUDE.md warns about); the **Jul 4 worker restart** already picked up the key, so the
check should start populating from its next weekday run. Note on the *tail*: the largest
liquid "standoffs" in the feasibility overlay were MU — **not** a data error (checked: MU
trades ~\$975 in this period, IB `undPrice` \$973.3 and argon's WS feed \$975.6 both agree
with the grid's ~\$983; MU is simply a genuinely wild ~90–100% IV name). So the tail is real
high-vol residual, not corruption — but it still doesn't clear costs (the realized harvest
plateaus ~0.22–0.28 vp regardless of signal size). **Next:** let the restarted canary bank a
few days of IB-vs-UW diffs, then this cross-check runs on real data.

## Bottom line

Real signal, wrong side of the trade. The residual mean-reverts (autocorr 0.56, ~46–67%
next-day convergence on extremes) but the realizable, defined-risk, after-cost edge is
negative for a taker: ~\$0.18/contract gross vs per-contract commissions of the same order,
before spread and before the 2-leg defined-risk penalty. This is the "single-name surface
residual arb is a market-maker game" prior, now quantified — and it matches argon's own
track record (skew directional probe closed no-edge, PR #208; the edge was in *macro* VRP
selling, Sharpe ~1.65, not single-name surface geometry).

**Do not build the residual→signal layer.** Two things could change the answer, neither
cheap: (a) **intraday** surface capture (the tabled xenon option_chain_snapshotter) to
measure whether faster-than-1-day execution recovers enough of the 0.72→0.22 vp decay —
unmeasurable with daily EOD snapshots; (b) a **maker/market-making** posture that earns the
spread instead of paying it, which is a different business than argon's defined-risk taker book.

## Reproduce
- Reversion: `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python -m scripts.research.svi_residual_reversion_probe` → `reversion_metrics.csv`.
- Cost: live IB quote via `uw_scan.sources.xenon_query.fetch_ib_option_quote` (needs `XENON_QUERY_API_KEY`); numbers above frozen as-of 2026-07-04 (market closed).
