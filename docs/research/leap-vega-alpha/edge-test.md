# LEAP Vega-Alpha — Stage 2 (P&L decomposition) — 2026-07-06

Follow-on to the Stage-1 convergence gate (`README.md`), which showed a real cross-sectional
relationship (high-HV names' held-LEAP IV rises relative to peers) and flagged the one
question that decides tradability: **is that a vega edge, or is it delta/skew migration?**

**Verdict: NO tradable vega edge for a defined-risk taker.** The gross P&L on the flagged
"cheap LEAP" entries is **82–88% delta** — a leveraged long-equity bet on high-realized-vol
names during a rising market, *not* forward-vol mispricing. Isolate the vega (delta-hedge)
and net the theta bleed, and the real edge is **0.6–0.7 vol points — below even a 1 vp
round-trip spread**, and far below the realistic 2–5 vp for ATM LEAPs. radon's thesis, as a
*vega* trade, fails the cost test here.

## The decomposition (`pnl_metrics.csv`, 173 flagged entries, gap ≥ 0.10, single-name)

At each entry with `HV − ATM_IV ≥ 0.10`, buy the ~420-DTE ATM LEAP, hold `h` grid-rows, and
split the per-share P&L on the held contract:
`pnl = vega·ΔIV·100 (vega) + delta·ΔS (delta) + theta·days (theta)`.

| horizon | n | gross harvest ΔIV | delta share of gross | $/sh vega / delta / theta | **delta-hedged NET (vega+theta)** | win% |
|---|---|---|---|---|---|---|
| 20d | 98 | 3.18 vp | **82%** | 5.87 / 51.38 / −5.11 | **$0.76/sh = 0.60 vp** | 67% |
| 40d | 75 | 5.74 vp | **88%** | 11.02 / 150.10 / −9.39 | **$1.63/sh = 0.70 vp** | 83% |

Two things kill it:

1. **The apparent edge is direction, not vol.** Delta is 82–88% of gross P&L. The flagged
   entries select high-realized-vol single names (NVDA, MU, TSLA, AMD…), which simply *rose*
   over the hold in a rising-vol/rising-price regime. A long LEAP is ~0.5 delta, so it made
   money on the move. That is beta/momentum leverage, not the "market underprices forward
   vol" mechanism radon claims. Delete the delta (hedge it) and the thesis has to stand on
   the vega, which it doesn't.
2. **Theta eats the vega.** The raw vega repricing is real (ΔIV +3.2/+5.7 vp) but a long LEAP
   pays ~−3.8/−7.0 vp of theta over the same hold. Net delta-hedged vega+theta = **0.60/0.70
   vp**. A realistic ATM-LEAP round-trip spread is **1 vp (mega-cap) to 2–5 vp (off the top
   names)** — you cross it on entry *and* exit, plus the stock spread to delta-hedge. The
   net edge is under the tightest plausible spread. Cost sensitivity on the *gross* harvest
   (before theta): clears 1 vp 65% / 2 vp 58% / 5 vp only 42% (net −0.71 vp) — and the
   net-of-theta picture is strictly worse.

## Units (calibrated empirically, Task 5 Step 1 — not trusted from the CLAUDE.md note)
- LEAP-row greek fill: **100%** (2,944,437 / 2,944,437 — no NULLs).
- `call_vega ≈ 1.35` on a 1.2-yr ATM $308 AAPL option ⇒ **per-1%-vol** (per-1.0-vol would be
  ~134). So `pnl_vega = vega · ΔIV_decimal · 100`. The CLAUDE.md "vega ×100" note is wrong
  for this table.
- `call_theta ≈ −0.05` ⇒ **per-DAY** (per-year would be ~−18). So `pnl_theta = theta · days`.
- The headline verdict (harvest vp vs spread vp) is **vega-unit-independent** — the units
  only matter for splitting vega vs delta, which is the whole point here.

## Why this is the expected answer
It matches argon's track record: single-name *surface geometry* has repeatedly shown no
taker edge (skew directional probe closed, PR #208; SVI residual, PR #219). The gross number
looking huge before decomposition is the same trap each time — here $52–152/share of "edge"
that is 85% a directional bet. The one validated edge in this stack remains *macro* VRP
short-vol (SPX bull-put, Sharpe ~1.65), not single-name vol timing.

## Addendum — is the *delta* an edge? (momentum, not alpha; no clean sweet spot)

The delta P&L was 82–88% of gross and won 67–83% of the time, so the obvious next question is:
forget vega — is buying the LEAP a good *directional* entry? Test: FM cross-sectional IC of
the entry gap vs **forward spot return** (within-date ranking is market-neutral by
construction, so a positive IC is directional alpha, not beta). Trace: `gap_observations.csv`
(`fwd_ret` col), `convergence_metrics.csv` (`de_ic_ret`, `de_excess_ret`).

| horizon | IC(gap vs fwd return) | leave-one-out IC range | corr(gap, HV20) |
|---|---|---|---|
| 20d | **0.346** | 0.28–0.43 (robust) | 0.67 |
| 40d | **0.381** | 0.30–0.51 (robust) | 0.72 |

The relationship is real and survives dropping any single ticker — high-gap names beat their
same-date peers. **But it is cross-sectional momentum, not a tradable LEAP sweet spot:**

1. **It's momentum.** `corr(gap, HV20) ≈ 0.7`: the gap is wide *because realized vol is high*
   — these are names that just moved a lot, and in a bull tape they kept rising. That's the
   momentum factor (already parked in this stack: Barroso–Santa-Clara risk-managed momentum;
   dark-pool lead-lag = mostly beta), not surface mispricing.
2. **The extreme "sweet spot" is 2 names.** The market-excess forward return by gap threshold
   looks spectacular (20d: +15.6%→+31.1% across thr 0.10→0.25; 40d: +41%→+55%), but at
   gap≥0.20 the flagged set is only **AMD + SNDK**, and **SNDK alone (+65%/+84%)** drives it.
   Not a rule — one Sandisk run.
3. **One regime.** Prices *and* vol rose all sample. Momentum inverts in corrections, and a
   LEAP is leveraged → the reversal is a blowup.
4. **The signals conflict.** Momentum points at high-realized-vol names, which carry **high IV
   (expensive)**. The cheap-vol LEAP entry and the momentum LEAP entry are opposite trades.

**Sector test (the decider): the signal is entirely semiconductors.** Split the single-name
FM IC(gap vs fwd_return) by sector:

| horizon | ALL (10) | SEMIS-only (5) | NON-SEMIS (5) | mean fwd_ret semis / non |
|---|---|---|---|---|
| 20d | 0.346 | 0.450 | **0.031** | +20.0% / +0.9% |
| 40d | 0.381 | 0.651 | **−0.028** | +47.1% / +2.8% |

Outside semis (AAPL, TSLA, META, GOOGL, GS) the gap predicts **nothing** (IC ≈ 0), and
non-semis high-gap names returned +0.9%/+2.8% — market beta, zero excess. The whole "delta
edge" is the **semis/AI rally of H1 2026** (AMD, SNDK, NVDA, MU, SMH, SOXX). The earlier
leave-one-*ticker*-out robustness was a mirage: dropping one semi leaves four others; drop the
whole *sector* and it vanishes.

**Delta verdict: NO strategy.** It is not momentum-the-factor — it is one sector's single
realized uptrend over one regime, wearing a cross-sectional-signal costume. "Buy the gap" =
"be long semis in early 2026," a backtest of hindsight. No tradable LEAP entry rule, gap-based
or otherwise, survives this data.

## Load-bearing caveats
- **Single regime** (2025-12-26 → 2026-07-02): prices *and* vol rose. That inflates both the
  delta P&L (up-market) and the raw vega harvest (up-vol). A falling-vol regime would likely
  make even the 0.6–0.7 vp net edge negative.
- **6 months** can't test hold-to-expiry harvest; this is a 20/40-day proxy only.
- If you *wanted* to chase this: the delta-hedged, gamma-scalp version (harvest realized vol
  via daily rehedge, not vega repricing) is a different trade and would need intraday data —
  the tabled xenon option-chain snapshotter. Not this book.

## Reproduce
`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python -m scripts.research.leap_pnl_probe`
(reads `gap_observations.csv` from Stage 1; **zero** UW/IB calls). Trace: `pnl_metrics.csv`
(per-entry vega/delta/theta/gross/harvest_vp, 173 rows).
