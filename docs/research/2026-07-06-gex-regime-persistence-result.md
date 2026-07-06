# GEX regime-persistence — validation RESULT

**Date:** 2026-07-07 · **Status:** NEGATIVE-ish / UNDERPOWERED — do NOT build yet
**Candidate:** #3 from the 2026-07-06 sweep (`2026-07-06-candidate-gex-regime-persistence.md`)
**Basis:** [COMPUTED] on banked `gex_snapshots` (mini `option_wizard`) + real `daily_ohlc` closes. Confidence MED.

## TL;DR

The **magnitude** half of the hypothesis (dealer short-gamma → bigger next-day
move) shows up in SPY **in the right direction but is not significant at n=31**,
and is **confounded by vol-clustering**. The **trend-vs-reversal** half is
**flatly refuted** (reversal rate identical across regimes). No directional
edge (correct — there shouldn't be one). **Verdict: don't invest build time in
the forward-accruing positioning candidates (#2 charm/vanna) on the strength of
this. Keep banking the daily regime label and re-test at n≈90 (~early Sept
2026).**

## What was tested

- **Label** (per session t): last `gex_snapshots` row stamped on the same
  calendar day as `data_date` (drops overnight/pre-market bleed that freezes
  `spot`). `net_gex < 0` → **short-gamma**, else **long-gamma**.
- **Forward outcome**: close-to-close from real `daily_ohlc` (source
  `massive.com`), not the intraday gex `spot`. |fwd ret|, next-day intraday
  range%, signed fwd ret, and a reversal flag (`sign(fwd_ret) != sign(ret_t)`).
- **Flip velocity**: |Δ flip-strike / close| in the day before a regime sign
  flip vs baseline.
- Window: SPY 2026-05-18 → 07-02, **n_usable=31** (20 short / 11 long). TLT
  same window, n_usable=12 — **structurally void** (only 1 short-gamma day
  in-window; ignore its "CI excludes 0", it's a single point).

## SPY numbers (the only bucket with power)

| metric | short-gamma (n=20) | long-gamma (n=11) | read |
|---|---|---|---|
| mean \|fwd ret\| | **0.820%** | 0.503% | Δ +0.317%, **boot95 CI [−0.046%, +0.699%]** (kisses 0), MW p=0.41 |
| median \|fwd ret\| | 0.603% | 0.552% | ~flat |
| mean fwd intraday range% | **1.394%** | 0.733% | ~2× — the largest/cleanest gap, same direction |
| reversal rate | 0.53 | 0.55 | **identical — trend/pin hypothesis dead** |
| mean signed fwd ret | +0.059% | −0.021% | ~0 both (no directional edge — as expected) |

Flip velocity: |migration| pre-regime-flip 0.54% (n=5) vs baseline 0.32% (n=25)
— directionally suggestive but n=5, noise.

## Why this isn't tradable

1. **Underpowered.** n=31 → the |fwd ret| bootstrap CI includes zero and
   Mann-Whitney p=0.41. The range% gap is bigger but n is the same.
2. **Vol-clustering confound (the killer).** The short-gamma sessions cluster
   in the high-vol fortnights (Jun 3–12, Jun 22–Jul 1 — see
   `*.SPY.sessions.csv`). `net_gex < 0` is partly just co-labeling "we are in a
   high-vol regime," and vol autocorrelates day-to-day. So "short-gamma → bigger
   next-day move" may carry little info beyond "vol clusters." A real test must
   **vol-normalize** the forward move (divide by trailing RV, or condition on
   VIX level) — not built here at n=31; it's the #1 control to add if this graduates.
3. **The reversal-character claim is refuted outright**, not merely
   underpowered — regimes are ~coin-flip on continuation either way.

## Decision

- **Do NOT** start the #2 charm/vanna forward-accrual build on the basis of this
  positioning-alpha thesis yet — the cheapest same-class test came back weak +
  confounded.
- **Keep** the daily regime label banking (it already does, via `gex_scan`).
- **Re-test trigger:** re-run at **n≈90 SPY sessions (~2026-09-01)** with a
  **vol-normalized** forward move + VIX-conditioning. Same pattern as the parked
  darkpool-lead-lag decision (wait for fresh data, don't re-slice these 31 days).

## Reproduce

```bash
# on the mini (has option_wizard with the banked history):
ssh macmini '/opt/homebrew/bin/uv run --project /Users/moremeds/projects/argon \
  python /Users/moremeds/projects/argon/scripts/research/gex_regime_persistence.py \
  --dsn "dbname=option_wizard" --tickers SPY,TLT --out-prefix /tmp/gex_regime'
```

Full traces: `2026-07-06-gex-regime-persistence.{SPY,TLT}.sessions.csv`,
`.summary.json`. Script: `scripts/research/gex_regime_persistence.py` (seed 20260706).
