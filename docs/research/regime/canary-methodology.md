# 5% Canary Methodology

Source of truth for the 5% Canary indicator's math, calibration, and design.

- **Code:** `src/uw_scan/cards/canary_scoring.py`
- **Scanner:** `src/uw_scan/scanners/canary.py`
- **API:** `src/uw_scan/api/routers/regime.py`
- **UI:** `web/components/regime/CanarySubTab.tsx`
- **Persistence:** `uw_scan.canary_snapshots` (migration 059)
- **Spec (full design):** `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md`

## 1. What the 5% Canary is

The 5% Canary scores **forward dip-buy favorability** on a 0–100 scale every
trading day. It is the forward-looking complement to CRI: CRI fires *during*
crashes (descriptive), 5% Canary scores *favorability for buying the dip*
after stress events resolve (anticipatory). The name is borrowed from
Thrasher (2023, NAAIM) whose canonical signals form the Price-Speed tier.

The composite is **not** a model — it is a structured weighted sum of five
literature-backed volatility-complex signals plus a state-machine flag, with
a hard cap that vetoes high scores during published bearish-warning regimes.

## 2. Component framework

| Tier | Max points | Signals |
|---|---:|---|
| Tactical Vol | 30 | VIX spike-and-reversion (15), VIX/VIX3M backwardation-normalize (15) |
| Structural Vol | 50 | VRP (21), COR1M peak-and-decay (17), VVIX/VIX recovery (12) |
| Price Speed | 20 | Thrasher Buy-The-Dip / Confirmed-Canary 4-state model |
| **Composite** | **100** | Tactical + Structural + Speed, then cap rule |

The 4-state speed model: `NEUTRAL` (8 pts), `BUY_THE_DIP_ACTIVE` (20 pts),
`CONFIRMED_CANARY_ACTIVE` (0 pts), `BOTH_ACTIVE_AMBIGUOUS` (8 pts).

Band map: 0–24 NONE, 25–49 WATCH, 50–74 BUY, 75–100 STRONG_BUY.

## 3. Calibration

Thresholds in `canary-calibration-v1.json` are computed by
`scripts/backtest_canary.py --calibrate` on the **train window
2007-01-01..2014-12-31**, using **positive-condition observations only**
(only days where the gate condition fires) so the empirical distribution
matches the runtime feature.

**Procedure:** floor = p25, ceiling = p90.

**v1 priors (pre-calibration):** the currently-committed
`canary-calibration-v1.json` carries the v0.1 priors below. These will be
overwritten by `--calibrate` against the warm store on first publish; the
priors are anchored on the relevant literature (Whaley 2000; Bollerslev/
Tauchen/Zhou 2009; Driessen/Maenhout/Vilkov 2009; Cboe VVIX whitepaper).

| Signal | Gate condition | Floor (v1 prior) | Ceiling (v1 prior) | Max points |
|---|---|---:|---:|---:|
| VIX spike revert | 10d VIX peak ≥ 30 | 0.05 | 0.30 | 15 |
| VIX/VIX3M back-normalize | 10d ratio peak ≥ 1.05 | 0.05 | 0.20 | 15 |
| VRP | always-on (rv_window=20) | 50.0 | 300.0 | 21 |
| COR1M decay | 60d COR1M peak ≥ 60 | 0.05 | 0.30 | 17 |
| VVIX/VIX recovery | 60d ratio min ≤ 4.0 | 3.5 | 5.0 | 12 |

Author overrides: empty for v1 — see `author_overrides` array in the JSON
for any future manual deltas (each override carries `reason` + `reviewer`).

## 4. The cap rule

The composite raw score is capped at **49 (WATCH ceiling)** when the speed
state is `CONFIRMED_CANARY_ACTIVE` or `BOTH_ACTIVE_AMBIGUOUS`, UNLESS a
cap-lift condition fires:

- `spx_above_sma200_2d` — two consecutive closes above the 200d SMA, OR
- (`vix_term_normalized` AND `higher_closing_low`) — VIX/VIX3M back below 1.0
  AND close-only higher low confirmed against the SMA-200 buffer.

`BOTH_ACTIVE_AMBIGUOUS` is harder than `CONFIRMED_CANARY_ACTIVE`: lift
conditions do NOT clear the cap when both event types are active in the
same 42-trading-day window. The intent is to publish WATCH (not BUY/
STRONG_BUY) when the two signals are simultaneously confirmed, since the
literature does not certify either reading in that state.

## 5. Validation

Two layers, both DB-backed (no CSV/MD output files committed — per
`docs/research/regime/CLAUDE.md`):

**(a) Warm-store backtest** — `scripts/backtest_canary.py --report` on the
test window 2020-01-01..present. Output lands in
`uw_scan.regime_backtest_runs` with `summary.is_winning_form=true`. The
`/regime/canary/validation` API endpoint reads this row and renders a
Markdown report from the structured summary.

**(b) OOS gate (CI-enforced)** —
`tests/integration/regime/test_canary_oos_gate.py`. Two gates:
- **Regression:** AUC must not drop more than 0.02 vs `LAST_KNOWN_AUC_*`.
- **Absolute acceptance (spec §8.6):** AUC > 0.55 on ≥ 2 of 3 labels AND
  AUC `up60d_10pct` > 0.58.

Plus event-level guards on the Buy-The-Dip and Confirmed-Canary populations
(median forward drawup/drawdown + block-bootstrap 95% CI low).

## 6. Honest finding (post-backtest)

*(To be written after the first full `--report` against the warm store
completes. Will mirror the CRI methodology's §8 honesty pattern: state
where the indicator works, where it doesn't, and the regime context in
which it was developed.)*

## 7. Literature anchors

1. **Whaley (2000)** — JPM, "The Investor Fear Gauge". Foundational VIX
   spike-and-reversion reading.
2. **Bollerslev, Tauchen, Zhou (2009)** — RFS, "Expected Stock Returns
   and Variance Risk Premia". Source of the VRP scoring framework.
3. **Driessen, Maenhout, Vilkov (2009)** — JoF, "The Price of
   Correlation Risk". Anchors the COR1M peak-and-decay framing.
4. **Cboe VVIX whitepaper** — Source of the VVIX/VIX recovery signal
   (compressed-regime detection).
5. **Macrosynergy (2023)** — VIX/VIX3M term-structure normalization
   anchor.
6. **Thrasher (2023, NAAIM)** — *The 5 Percent Canary*. Source of the
   Buy-The-Dip and Confirmed-Canary state machine that drives the Price
   Speed tier; the indicator's name borrows from this paper. Local PDF
   at `2023-thrasher-5pct-canary.pdf`.

## 8. Indicator lifecycle

| Event | Action |
|---|---|
| New 252d closing high in SPX | Anchor reset; clear canary/btd flags AND open Confirmed-Canary windows |
| 5% breach within 15 trading days of anchor | Emit `5pct_canary` + open Confirmed-Canary window (42 trading-day budget) |
| 5% breach >15 trading days after anchor + SMA50>SMA200 | Emit `buy_the_dip` |
| 2 consecutive closes below SMA-200 inside an open window | Emit `confirmed_canary` (consume window) |
| 42 trading days elapse since canary fire | Confirmed-Canary window expires unused |

The anchor invariant — **at most one primary event per 252d high anchor** —
prevents an episode from firing both `5pct_canary` (fast path) AND
`buy_the_dip` (slow path) against the same high.
