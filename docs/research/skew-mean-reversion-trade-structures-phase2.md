# Skew Mean-Reversion → Trade Structures (Phase 2)

**Date:** 2026-06-15
**Status:** Phase-2 design notes — deferred. Captures the trade-idea discussion built on
the V1 Tier-1 markout (`docs/research/skew-first-principles-markout-2026-06.md`). Not yet
implemented; this is the operational target for turning the RR mean-reversion finding
into surfaced, defined-risk structures.

## The core reframe

The markout measured reversion of the **skew shape** (the 25Δ risk-reversal
`RR = IV(put) − IV(call)`), NOT the stock price. So these are **relative-value bets on
the two wings**, not directional stock bets. `Put 贵 ≠ 看跌`: when put-skew is rich you
do not short the stock — you bet the put wing cheapens *relative to* the call wing. Keep
delta small (or hedge it) so the position trades vol-shape, not direction.

## Empirical anchor (V1 markout, single ~13-month in-sample window)

| Bucket | mean ΔRR over T+20 | reversion read |
|---|---:|---|
| single-name **CHEAP** | **+0.051** (n=1472) | cheap put-skew re-richens hard — cleanest, biggest |
| sector-ETF **CHEAP** | +0.033 (n=62) | re-richens (clean) |
| single-name **RICH** | −0.003 (n=4352) | rich put-skew flattens — weak |
| sector-ETF **RICH** | −0.005 (n=164) | flattens — weak |
| **index** (SPX/QQQ/…) | ~+0.001 | does NOT revert — structural hedging demand; SKIP |

Direction of reversion is the textbook signature (RICH→down, CHEAP→up). Magnitude and
conviction are strongly asymmetric: **the CHEAP→re-richen leg is the tradeable one.**

## Structure 1 (recommended) — CHEAP put-skew → long put debit-spread

Buy the cheap wing inside a defined-risk vertical (long-options, defined risk by
construction — no naked short):

```
 Long put debit-spread on a CHEAP-skew name (e.g. QCOM: z=-0.46, 11th pct, STRUCTURAL)
   BUY   ~25Δ put        ← the cheap wing the signal says is underpriced
   SELL  ~10-15Δ put     ← caps cost; the tail is even cheaper-skew, you give up little
   ~28-45 DTE (matches the T+20 reversion horizon); exit before earnings

 Payoff (max loss = net debit):
   profit ▲
         │            ┌────────  if put-skew re-richens, the 25Δ leg's
         │           /            IV/vega gains even with spot flat
        0│──────────/──────────────►  spot
         │      ___/
   -debit│_____/      max loss = net debit (no naked tail)
```

Why this one: largest + cleanest reversion, defined risk by construction, and it doubles
as cheap downside protection. Re-richening pays via vega even if spot is flat; a spot
fall adds delta.

Current real CHEAP/STRUCTURAL candidates (2026-06-11 snapshot): QCOM, RKLB, OKLO, PFE.
Avoid CHEAP+PANIC (e.g. TXN) — panic can keep skew cheap longer.

## Structure 2 (lower conviction) — RICH put-skew → finance the expensive wing

RICH put-skew reverts down but weakly. Express short-the-rich-tail, never naked:

- **No stock:** put debit-spread net-short the rich far-OTM tail (buy nearer put, sell
  the rich tail) — harvest tail richness, long put caps risk.
- **Hold the stock:** collar / put-spread-collar — the short call is covered. Classic
  "finance rich skew" (spec §3 idea #2). Valid only *with* the underlying.

Caveat: RICH skew often = genuine fear (PANIC, ρ<0, e.g. BE). Don't fade a real crash;
size small.

## Structure 3 — pure-skew vertical (delta-hedged)

To isolate skew from direction, put on the wing vertical and hedge the residual delta
with a small share offset → a near-pure skew-normalization position. Phase-2 nicety;
needs Greek management the V1 tab does not yet provide.

## Playbook (target Skew-tab workflow for Phase 2)

1. Posture → `CHEAP` (best) or `RICH`; **single-name or sector-ETF only** (skip index).
2. Drive → prefer `STRUCTURAL`. `PANIC` = real fear (may keep richening); `CHASE` =
   momentum (directional markout showed CHASE buckets *continue*, not revert).
3. CHEAP → long put-spread (buy cheap wing). RICH → short-tail put-spread, or collar if
   held.
4. ~28-45 DTE, exit before earnings, defined-risk always.

## What Phase 2 needs to build

- A **"Mean-Reversion Trade" panel** on the Skew tab that, for a CHEAP/RICH non-index
  name, proposes the concrete defined-risk vertical (strikes by target delta, suggested
  DTE) — deterministic, no naked legs.
- **Skew-markout on the RR itself** as a tradeable trigger (V1 treats ΔRR as
  descriptive only): forward-validate that the CHEAP→re-richen edge survives out-of-sample
  and net of spread cost / bid-ask, with the per-window gate.
- **Delta-hedge sizing** helper for the pure-skew variant (Structure 3).
- Earnings/DTE guardrails wired into the proposal (swing-HOLD ≠ swing-EXPIRY; no
  hold-through-earnings).

## Caveats (carry into Phase 2)

- In-sample, one window; skew effects decay (Cremers-Weinbaum). Tilt, ~2-4 week horizon.
- Skew reverting ≠ the stock moves your way — size as a vol/RV position.
- The big CHEAP number is partly high-vol names where *call*-skew went extreme
  (e.g. ALAB rr=−0.22) — reverts hard but volatile; size down.
- Never naked — every short wing sits inside a spread or is covered by stock.
