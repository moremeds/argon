# VCG calm gate — operator note

> **Hand-written. Do not regenerate.** The four sibling docs dated 2026-07-29
> are emitted by scripts and their prose is computed from the run — edit the
> script, not the doc. *This* file is the plain-language summary of what those
> four mean in practice, written to be readable cold months later by someone
> who no longer remembers the derivation. Numbers here are quoted from the
> generated docs; if they ever disagree, **the generated docs win**.

**Status as of 2026-07-29: NOT deployed, NOT wired into any path, no real
money.** This note describes what the evidence supports, not something that is
running.

---

## 1. The trade

Sell a **bull put spread on SPX** — collect cash today for betting the S&P
won't fall much over the next ~20 sessions.

- SPX flat, up, or mildly down → keep the premium
- SPX falls hard → you lose, but the loss is **capped** by the long wing you
  bought below (defined risk, no naked short — this is a hard house rule)

It is selling insurance. Most months you pocket the premium; occasionally you
pay a claim. The entire problem is **not writing policies right before the
hurricane**.

## 2. The gate — two tests before entering

| Test | What it asks |
|---|---|
| `vrp_z >= 0` | **Am I being paid above the going rate?** Is implied vol richer than recently realised vol? |
| `\|vcg_z\| < 0.75` | **Is the market internally consistent?** Do the vol complex and the credit market agree, or is one screaming while the other shrugs? |

Both pass → entry permitted. Either fails → skip today, look again tomorrow.

The second test is the new one. VCG measures *divergence* between the vol
complex (VIX/VVIX) and credit (HYG). When two independent instruments disagree,
something is wrong even before you can name it — and that is not the day to
sell insurance.

## 3. What it's worth, in money

The generated docs report everything in units of **one max-loss**, which reads
as a percentage and is not one. `ann ROR 1.31` means *1.31× a single spread's
max loss per year*, not 131% of capital. Getting this wrong is a sizing error.

Concretely — size so **one spread's max loss = $1,000**, then over 14 years of
walk-forward out-of-sample (SPX, 0.25Δ short, 20-day hold):

| arm | trades | makes per year | worst drawdown |
|---|---:|---:|---:|
| `always` (no gate) | 163 | ~$960 | ~$3,760 |
| `gate0` (VRP only) | 135 | ~$1,110 | ~$3,850 |
| **`calm` (VRP + VCG)** | 126 | **~$1,310** | **~$1,050** |
| `vix_low` (VRP + cheap VIX filter) | 76 | ~$830 | ~$1,120 |

Two things to take from this:

**The drawdown collapse is the real prize.** `gate0` → `calm` cuts worst
peak-to-trough from ~$3,850 to ~$1,050, roughly 3.7×. Drawdown is what caps
size, so the same risk appetite funds a much larger position — and Sharpe is
size-invariant, so you keep the return quality while earning more dollars. This
is a **drawdown-control overlay**, not a return engine.

**~9 trades a year.** One every six weeks. This is a checklist you run daily
and act on rarely.

## 4. Why Sharpe alone would have misled you

`vix_low` scored Sharpe 1.18 against `calm`'s 1.35 — close enough to conclude
"just use VIX, it's simpler." That conclusion is wrong.

Sharpe measures **smoothness, not earnings**, and there is a trivial way to
look smooth: **do less**. `vix_low` took 76 trades where `calm` took 126, and
had the *same* worst outcome. It was not safer, it was more **absent** —
delivering ~$830/yr against ~$1,310/yr for identical downside.

A surgeon who declines every borderline case has excellent outcome statistics
and helps fewer people. Always read the **trade count and annual ROR** beside
the Sharpe; that pairing is what exposes an abstention strategy.

## 5. Daily use

1. Open `/regime/vcg`. **Is today's bar inside the shaded band?** (that band is
   `|z| < 0.75`, added for exactly this glance)
2. Check `vrp_z >= 0`
3. Both yes → entry permitted. Either no → do nothing today
4. If entering: **hold ~20 days**

## 6. What this is NOT

- **Not a direction call.** Tested twice, dead both times (max |t| vs rest =
  1.10 across 30 cells). `RISK_OFF` does **not** mean "sell equities" — it is
  positioning vocabulary describing coincident vol/credit stress.
- **Not a trigger — it is permission.** It never says "trade now". It says
  "today is not disqualified".
- **Not valid at a 30-day hold.** At 0.25Δ/30d the result **inverts**: the gate
  makes things worse (1.07 vs 1.39). Unexplained. Working hypothesis is that
  the calm reading decays over a longer hold relative to VCG's own 63-session
  normalisation window — **untested guess, do not treat as established.**
- **Not a VIX proxy.** ρ with the VIX level is −0.030. `vcg` is already an OLS
  residual of credit on the vol complex, so it is near-orthogonal to VIX by
  construction. Regressing VIX out changes the answer by 0.01 Sharpe.

## 7. Why it is not deployed

1. **The 30-day inversion is unexplained.** A rule that flips on a plausible
   parameter is a rule you do not fully understand.
2. **Backtest prices options with flat vol, no skew**, which understates
   put-spread credit — and the gate changes *when* you enter, therefore *what
   pricing you face*. Unmodelled, could cut either way. This is the one that
   could kill it outright.
3. **126 OOS trades over 14 years is a thin sample**, and the Sharpe difference
   has not been significance-tested.

## 8. Next steps, in order

1. **Diagnose the 30-day inversion** — sweep hold length 10/15/20/25/30 against
   the threshold. If Sharpe degrades monotonically with hold length, the gate
   has a documented *domain* rather than a defect, which makes it stronger.
   Cheapest and most decisive.
2. **Re-price with real skew** from `option_surface_grid_daily` instead of flat
   vol.
3. **Shadow it on the existing paper path** (`vrp_paper_open` /
   `vrp_paper_mark`, already nightly). Zero risk, and it accrues the live
   record the Stage-2 goal ladder asks for before anything gets sized.

## 9. Where the evidence lives

| Doc | Question it answers |
|---|---|
| `2026-07-29-vcg-spx-forward-returns.md` | Does VCG predict SPX direction? (**no**) Forward vol? (**yes**) |
| `2026-07-29-vrp-vcg-calm-gate.md` | Does the calm core help the VRP book, in-sample? (promising, unproven) |
| `2026-07-29-vrp-vcg-calm-gate-walkforward.md` | Does it survive OOS with the threshold re-fit per window? (**3/4 yes, 1 reversal**) |
| `2026-07-29-vcg-vs-vix-walkforward.md` | Is it just a VIX filter? (**no** — ρ = −0.030) |

Reproduce (read-only against the mac mini; each script also records its own
command):

```bash
PGPASSWORD=… UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
UW_SCAN_DB_USER=argon_app UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_API_KEY=x \
uv run python scripts/research/vrp_vcg_calm_gate_walkforward.py

PGPASSWORD=… UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
UW_SCAN_DB_USER=argon_app UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_API_KEY=x \
uv run python scripts/research/vrp_vcg_vs_vix_walkforward.py
```
