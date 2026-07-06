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
