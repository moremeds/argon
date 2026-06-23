# MASTER REPORT — Macro Short-Vol Capital-Utilisation Study (2026-06-23)

> **Self-contained.** All data is embedded inline (not only in sibling CSVs) so this
> document survives on its own. Every number is `[COMPUTED]` from the reconciled ledger
> (engine Δ Sharpe = 0.000). Nothing here is synthetic or hand-estimated.

---

## 0. Provenance & how to reproduce

| | |
|---|---|
| **Strategy** | Deployed macro short-vol winner (`WINNER` in `src/uw_scan/reports/vrp_macro_signal.py`) |
| **Engine (capital-blind)** | `backtest_laddered(loaded, settings, WINNER, min_date=…)` — the validated ROR backtest (Sharpe ≈1.65) |
| **New layer (dollar account)** | `src/uw_scan/reports/vrp_capital_account.py` — `simulate_account` + `account_metrics` |
| **Sweep runner** | `scripts/research/vrp_capital_sweep.py` |
| **Production data** | mac mini `option_wizard` @ `100.66.147.98`, `uw_scan.vol_index_daily` **through 2026-06-18 (SPX) / 2026-06-19 (VIX)** |
| **Local data** | `option_wizard_local` @ 127.0.0.1 (through 2026-05-21) + equity lake `~/market-warehouse/data-lake` (SPY/QQQ/IWM, through 2026-05-15) |
| **Branch** | `feat/vrp-backtest-r2` |
| **Sibling artifacts** | `capital-sweep-results.csv` (3-name 28-config), `base-case-mini-sweep-2026-06-23.csv` (mini SPX/SPY), `macro-capital-utilisation-verdict.md`, `macro-capital-utilisation-findings.ipynb` |

**Reproduce (3-name $50k sweep, local):**
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
uv run python scripts/research/vrp_capital_sweep.py
```
**Reproduce (base case on the mini, freshest data):** point the same script's loaders at
`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_DB_USER=argon_app`
(password from the main repo `.env.local`; mini host+`option_wizard` is the only combo the
three-tier tripwire allows). Reads are SELECT-only on `vol_index_daily`.

---

## 1. METHODOLOGY

### 1.1 The base case (`WINNER`) — entry / exit rules

```
MacroSignalConfig(
    structure   = 'bull_put_spread',   # defined-risk: sell 0.25Δ put, buy 0.125Δ wing
    short_delta = 0.25,                 # short put delta (OTM magnitude)
    wing_frac   = 0.5,                  # wing_delta = short_delta * wing_frac = 0.125
    hold_days   = 30,                   # 30 TRADING days (~43 calendar, ~40-45 DTE)
    cadence     = 5,                    # weekly entry (every 5 trading days)
    sizing      = 'ramp+',             # size = clamp(vrp_z / ramp_full_z, 0, 1)
    ramp_full_z = 0.5,                  # 0 size at z<=0, full size at z>=0.5
)
```

| Element | Rule |
|---|---|
| **Underlying** | An index (SPX/SPY/QQQ/IWM). Index → no corp actions, no earnings |
| **IV** | Vol-index proxy / 100 (SPX,SPY→VIX; QQQ→VXN; IWM→RVX) |
| **RV** | Realized vol of trailing 20d log-returns, annualised (×√252) |
| **VRP** | IV − RV; **vrp_z** = z-score of VRP over the trailing **252** observations |
| **Entry cadence** | Weekly — a candidate every 5 trading days |
| **Entry gate (ramp+)** | Trade only when **vrp_z > 0** (vol richer than its norm). Position size scales **0→1 linearly as vrp_z goes 0→0.5**; full size above. vrp_z ≤ 0 ⇒ no trade |
| **Strikes** | Flat-vol Black–Scholes invert delta→strike: short put at 0.25Δ, long put (wing) at 0.125Δ |
| **Exit** | Held to expiry at +30 trading days; settled at intrinsic. **No profit-take, no stop** — the long wing is the defined-risk floor |
| **Risk per spread** | max_loss = (put_width − credit) × 100; this is the margin/capital-at-risk per contract |

### 1.2 Two measurement bases (do not conflate)

**(A) Capital-blind return-on-risk (ROR)** — `backtest_laddered`. The canonical "1.65"
basis. A constant-risk *slot* account: each month's book return = size-weighted Σ of the
rung RORs exiting that month, ÷ `max_slots` (=round(hold/cadence)=round(30/5)=6). Every
slot is always funded; **no dollar cap, no idle cash, no integer-contract rounding**. ROR
is scale-invariant (P&L per $1 of max-loss risk), so it measures the *signal's* quality
independent of account size. Monthly-ROR Sharpe is annualised ×√12.

**(B) $50k dollar account** — `simulate_account` (new). Models a real **$50,000 cash
account**:
- Candidate weekly entries across the chosen names share ONE buying-power line.
- Same-date entries rotate priority by date ordinal (no name systematically first).
- Each entry sizes **base** = `floor(w · base_risk_pct · 50000 / margin_per_contract)`
  where `w` = ramp+ weight; optional **overlay** = `floor(overlay_mult · base_risk_pct ·
  50000 / margin)` extra contracts when `vrp_z ≥ rich_threshold` **and base ≥ 1**.
- Capital cap: `actual = min(desired, floor(available / margin))`. Shortfalls logged; a
  rung wanting ≥1 but affording 0 is a **skip**.
- Margin = max_loss × 100 × contracts, held over `[entry, exit)`; freed at expiry.
- Monthly excess P&L (as a fraction of $50k) → metrics. Idle cash earns **rf = 4%**, so
  reported P&L is **excess**; **gross = excess + rf**.

### 1.3 Metrics defined

- **Sharpe** = mean(monthly) / pstdev(monthly) × √12 on the zero-filled contiguous month span.
- **Arithmetic annualised** `ann_return_*` = mean(monthly) × 12 (constant non-compounding
  base). **Geometric** `cagr_*` = (1 + total)^(1/years) − 1. These DIVERGE strongly under
  high variance; the **CAGR is the deployable number**, the arithmetic is a per-month-risk rate.
- **maxDD** = min peak-to-trough of the cumulative **dollar** P&L curve, ÷ $50k. A reading
  past −100% means a loss exceeding starting capital in dollar terms, drawn from a higher
  banked-equity peak.
- **util_mean / util_peak** = mean / max of daily deployed-margin ÷ $50k.
- **skip_rate** = fully-skipped rungs ÷ desired rungs. **fill_rate** = contracts filled ÷
  contracts desired (captures partial fills).
- **win_rate / breach_rate** = fraction of rungs with net P&L > 0 / with the short strike breached.

### 1.4 Correctness — the reconciliation proof

The dollar ledger must not silently diverge from the validated engine. Run SPX-only,
**uncapped** (capital $1e9, base_risk_pct 0.05 → ~30% peak, 0 skips), base-only: the ledger
monthly series is a **constant multiple** (`base_risk_pct × max_slots`) of the engine's
`÷max_slots` series — both P&L and costs scale linearly in contracts, contract count =
`w·budget/margin`, and the constant cancels in mean/stdev. **Sharpe is scale-invariant ⇒
identical up to integer-floor noise.** Verified: **ledger 1.834 = engine 1.834, Δ 0.000**,
0 skips, util_peak 0.300 (`tests/integration/reports/test_vrp_capital_account_db.py`).

### 1.5 Data sources & known data issues

- **vol_index_daily** (VIX 1990→, VXN/RVX 2009-09→, SPX 1975→) — local mirror of the R2
  vol-complex lake. **No Yahoo, ever.**
- **Equity lake** SPY/QQQ/IWM daily closes. **SPY quirk:** SPY's parquet carries ~73%
  null-`trade_date` rows (an alternate-schema partition mixed in); the loader now skips them
  (`d is not None` guard in `_lake_spot`), leaving the clean **8,379-bar daily series
  (1993–2026)**. Validated against known closes: SPY $92.96 on 2009-01-02, $239.85 on
  2020-03-16 (COVID low), $739.17 on 2026-05-15. QQQ/IWM have 0 null dates.
- **Pricing:** flat-vol Black–Scholes (skew ignored). For put spreads this is **conservative**
  — real put-skew credit ≥ modeled, so reported returns are a floor. No real-fill NBBO.

---

## 2. RESULTS

### 2.1 Base case headline — capital-blind, on freshest mini data (through 2026-06-18)

| Window | Sharpe | annROR | maxDD | Calmar | rungs |
|---|---|---|---|---|---|
| **Full 2006-01-03 → 2026-06-18 (incl. 2008)** | **1.652** | 0.530 | −0.796 | 0.67 | 522 |
| 2009-01 → 2026-06-18 (excl. 2008) | 1.834 | 0.566 | −0.590 | 0.96 | 480 |

**1.652 is THE base-case Sharpe** (full history). 1.834 is the post-2008 slice (2008's −80%
tail drags the full-history number down).

### 2.2 Single-name decomposition — capital-blind ROR, 2009+ (why a 3-name blend dilutes)

| Name | IV proxy | Sharpe | annROR | maxDD |
|---|---|---|---|---|
| **SPX** | VIX | **1.834** | 0.566 | −0.59 |
| **SPY** | VIX | **1.460** | 0.450 | −0.81 |
| **QQQ** | VXN | **1.007** | 0.354 | −0.75 |
| **IWM** | RVX | **0.438** | 0.176 | **−1.28** |

SPX→SPY substitution alone costs ~0.37 Sharpe. **IWM is the dilution killer** (0.438 Sharpe,
−128% maxDD; Russell-2000 small-caps have fatter left tails the short-vol spread gets run over by).

### 2.3 $50k SPX direct (cash-settled, European, §1256 — fully tradeable). Mini data.

One SPX spread ≈ **$15,689 margin = 31% of $50k** at SPX 7,446. Min base_risk_pct to fund 1
contract today ≈ **0.31**.

| base_risk_pct | Sharpe | CAGR gross | ann gross | util mean | util peak | skip% | fill% | win% | breach% | rungs | entries/yr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 1.43 | 0.142 | 0.431 | 0.31 | 1.00 | 0.4% | 98% | 91% | 11% | 279 | 17.9 |
| **0.32** | **1.98** | 0.166 | 0.735 | 0.49 | 1.00 | 14% | 78% | 93% | 9% | 325 | 18.9 |
| 0.50 | 1.87 | 0.177 | 0.904 | 0.61 | 1.00 | 31% | 55% | 93% | 9% | 296 | 17.1 |

⚠ Below base_risk_pct ≈ 0.31, SPX silently can't trade recent (high-index) years; the 1.98
peak is partly a capital-cap quality-filter artifact (binding funds only the richest weeks)
— fragile/in-sample. Robust SPX read = **base_risk_pct 0.20, Sharpe 1.43, 0 skips.**

### 2.4 $50k SPY direct (same signal, 1/10th lump → granular). Mini data.

One SPY spread ≈ **$1,701 = 3.4% of $50k**.

| base_risk_pct | Sharpe | CAGR gross | ann gross | util mean | util peak | skip% | fill% | win% | breach% | rungs | entries/yr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 1.43 | 0.111 | 0.284 | 0.24 | 0.59 | 0% | 100% | 90% | 12% | 463 | 26.7 |
| **0.20** | **1.56** | 0.147 | 0.548 | 0.49 | 1.00 | 0% | 96% | 90% | 12% | 478 | 27.6 |
| 0.35 | 1.63 | 0.164 | 0.730 | 0.64 | 1.00 | 16% | 71% | 91% | 12% | 410 | 23.7 |
| 0.50 | 1.62 | 0.171 | 0.814 | 0.70 | 1.00 | 26% | 54% | 91% | 11% | 360 | 20.8 |

SPY funds every gate-open week (no silent gaps), Sharpe 1.43–1.63. **The pragmatic $50k vehicle.**

### 2.5 $50k 3-name book (SPY+QQQ+IWM) — full 28-config sweep. Local data, 2009-01-05 → 2026-05-14 (17.33y).

Columns: base_risk_pct | overlay_mult | rich_threshold | ann_gross | cagr_gross | sharpe | maxDD% | util_mean | util_peak | skip% | fill% | rungs.

**Base-only baselines (overlay disabled):**

| brp | ovl | rich | annGro | cagrGro | sharpe | maxDD% | utilM | utilPk | skip% | fill% | rungs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.03 | — | — | 0.152 | 0.082 | 0.86 | −0.40 | 0.17 | 0.50 | 0.00 | 1.00 | 1110 |
| 0.05 | — | — | 0.262 | 0.107 | 0.95 | −0.71 | 0.31 | 0.87 | 0.00 | 1.00 | 1227 |
| 0.08 | — | — | 0.425 | 0.132 | 1.07 | −0.86 | 0.50 | 1.00 | 0.03 | 0.93 | 1237 |
| 0.10 | — | — | 0.474 | 0.139 | 1.06 | −0.84 | 0.57 | 1.00 | 0.08 | 0.84 | 1182 |

**Base + overlay grid (sorted by geometric CAGR gross, desc):**

| brp | ovl | rich | annGro | cagrGro | sharpe | maxDD% | utilM | utilPk | skip% | fill% | rungs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 2.0 | 0.5 | 0.605 | 0.153 | 1.05 | −1.01 | 0.71 | 1.00 | 0.34 | 0.42 | 848 |
| 0.08 | 2.0 | 0.5 | 0.557 | 0.148 | 1.01 | −1.00 | 0.68 | 1.00 | 0.29 | 0.50 | 902 |
| 0.10 | 1.0 | 0.5 | 0.555 | 0.148 | 1.05 | −0.99 | 0.67 | 1.00 | 0.25 | 0.57 | 967 |
| 0.10 | 2.0 | 1.0 | 0.534 | 0.146 | 1.04 | −0.92 | 0.62 | 1.00 | 0.18 | 0.58 | 1051 |
| 0.10 | 1.0 | 1.5 | 0.512 | 0.143 | 1.13 | −0.84 | 0.59 | 1.00 | 0.11 | 0.79 | 1145 |
| 0.10 | 1.0 | 1.0 | 0.511 | 0.143 | 1.03 | −0.96 | 0.61 | 1.00 | 0.15 | 0.69 | 1094 |
| 0.10 | 2.0 | 1.5 | 0.511 | 0.143 | 1.07 | −0.84 | 0.60 | 1.00 | 0.14 | 0.74 | 1111 |
| 0.08 | 2.0 | 1.0 | 0.510 | 0.143 | 1.07 | −0.93 | 0.58 | 1.00 | 0.14 | 0.67 | 1095 |
| 0.08 | 1.0 | 0.5 | 0.507 | 0.143 | 0.99 | −0.96 | 0.62 | 1.00 | 0.19 | 0.67 | 1036 |
| 0.05 | 2.0 | 0.5 | 0.503 | 0.142 | 1.06 | −0.86 | 0.58 | 1.00 | 0.16 | 0.71 | 1025 |
| 0.08 | 2.0 | 1.5 | 0.480 | 0.139 | 1.15 | −0.86 | 0.54 | 1.00 | 0.07 | 0.85 | 1189 |
| 0.08 | 1.0 | 1.0 | 0.476 | 0.139 | 1.10 | −0.79 | 0.55 | 1.00 | 0.10 | 0.79 | 1150 |
| 0.08 | 1.0 | 1.5 | 0.459 | 0.137 | 1.13 | −0.86 | 0.53 | 1.00 | 0.05 | 0.90 | 1215 |
| 0.05 | 1.0 | 0.5 | 0.433 | 0.134 | 1.12 | −0.83 | 0.49 | 1.00 | 0.05 | 0.89 | 1167 |
| 0.05 | 2.0 | 1.0 | 0.403 | 0.130 | 1.07 | −0.76 | 0.45 | 1.00 | 0.04 | 0.86 | 1172 |
| 0.03 | 2.0 | 0.5 | 0.374 | 0.125 | 1.08 | −0.85 | 0.42 | 1.00 | 0.04 | 0.93 | 1065 |
| 0.05 | 2.0 | 1.5 | 0.340 | 0.120 | 1.18 | −0.69 | 0.37 | 1.00 | 0.01 | 0.98 | 1219 |
| 0.05 | 1.0 | 1.0 | 0.333 | 0.119 | 1.00 | −0.83 | 0.39 | 1.00 | 0.01 | 0.96 | 1214 |
| 0.05 | 1.0 | 1.5 | 0.304 | 0.114 | 1.09 | −0.70 | 0.34 | 0.99 | 0.00 | 1.00 | 1227 |
| 0.03 | 2.0 | 1.0 | 0.241 | 0.103 | 0.89 | −0.64 | 0.28 | 1.00 | 0.00 | 0.98 | 1106 |
| 0.03 | 1.0 | 0.5 | 0.252 | 0.105 | 0.91 | −0.78 | 0.30 | 1.00 | 0.00 | 1.00 | 1110 |
| 0.03 | 2.0 | 1.5 | 0.201 | 0.094 | 1.10 | −0.39 | 0.20 | 0.99 | 0.00 | 1.00 | 1110 |
| 0.03 | 1.0 | 1.0 | 0.192 | 0.092 | 0.89 | −0.50 | 0.22 | 0.86 | 0.00 | 1.00 | 1110 |
| 0.03 | 1.0 | 1.5 | 0.174 | 0.088 | 0.98 | −0.40 | 0.19 | 0.70 | 0.00 | 1.00 | 1110 |

3-name Sharpe ceiling is ~1.0–1.18 — **well below the single-name SPX 1.83** because of the
IWM/QQQ dilution. The overlay lifts raw return but Sharpe stays flat (leverage, not edge).

### 2.6 Entry / exit & trade frequency — realized (SPX, base_risk_pct 0.32, mini)

- **325 rungs / 17.2y**, span 2009-01-02 → 2026-03-02.
- **Hold:** median **43 calendar days** (mean 43.5, range 42–47) = the 30-trading-day hold.
- **Gap between entries:** median **8 days** (consecutive weeks fire), mean **19.2 days** (the
  gate skips cheap-vol weeks).
- **Realized frequency ≈ 19 entries/yr → the weekly slot opens only ~36% of weeks.** The
  ramp+ gate alone opens ~28–32 weeks/yr; capital binding at $50k/0.32 trims to ~19. **In
  practice ~biweekly, clustered in rich-vol regimes — not a weekly trade.**
- **Last 5 SPX rungs** (1 contract, ~$13–16k margin each): net +$3,779 / +$3,056 / +$3,176
  / +$3,165 / +$3,240 — all held clean to expiry, no breach.

### 2.7 Live signal (2026-06-18, mini)

`current_macro_signal(SPX)`: spot **7501**, IV 0.164, **vrp_z −1.95**, weight **0.00**,
**action = SKIP**. Vol cheap → gate shut → stand aside. Live proof the base case is a
rich-vol harvester, not an always-on seller.

### 2.8 Max drawdown — both senses (they are DIFFERENT events)

Two honest numbers, measured on the equity curve **anchored at the $50,000 funding point**:
1. **maxDD $ (absolute):** the largest peak-to-trough **dollar** drop in equity.
2. **maxDD % of peak equity:** the largest **percentage** peak-to-trough, vs the running peak.

These usually occur in **different years**: the biggest *percentage* hit is the **2009 GFC
start** (the strategy sold puts into the crash, equity ≈ $50k → trough), while the biggest
*dollar* hit comes later at higher equity (2018/2025). The earlier-quoted "−9% of peak"
was wrong — it divided by the *terminal* peak, not the *running* peak at the drawdown.

| Config | maxDD $ (abs) [when] | as % of $50k base | maxDD % of peak [when] |
|---|---|---|---|
| **SPX direct, brp 0.20** | −$28,565 [2018-11] | −57.1% | **−49.8%** [2009-03] |
| SPX direct, brp 0.32 | −$39,291 [2009-03] | −78.6% | **−78.6%** [2009-03] |
| SPX direct, brp 0.50 | −$38,081 [2009-03] | −76.2% | −76.2% [2009-03] |
| SPY direct, brp 0.10 | −$22,672 [2018-11] | −45.3% | **−18.4%** [2009-03] |
| **SPY direct, brp 0.20** | −$40,028 [2018-11] | −80.1% | **−41.0%** [2009-03] |
| SPY direct, brp 0.35 | −$42,476 [2025-04] | −85.0% | −49.4% [2009-02] |
| SPY direct, brp 0.50 | −$47,545 | −95.1% | −70.6% [2009] |
| 3-name max-return (0.10/×2/0.5) | −$50,591 | −101.2% of base | (single-name only) |

**Honest risk statement for the recommended SPY @ brp 0.20:** worst drawdown **≈ −41% of
capital** (March-2009 GFC, $50k → ~$29.5k) in percentage terms, or **≈ −$40,000 absolute**
(Nov-2018) in dollar terms. SPX at brp 0.32 is far worse early: **−78.6%** in March 2009.
The **% of $50k base** column can exceed −100% (the 3-name max cell) only because the
*dollar* drawdown is divided by the constant non-compounding base, not by peak equity — but
the genuine peak-relative drawdowns above (−18% to −79%) are the real risk.

### 2.9 Equity curve & buy-and-hold benchmark — see the notebook

Clean matplotlib charts (equity vs buy-hold, the compounding question, underwater drawdowns,
the frontiers) live in **`macro-capital-utilisation-findings.ipynb`** (executed, charts
embedded). Headline numbers, 2009 → 2026-06 (mini), $50k start:

| Curve | terminal equity | CAGR | maxDD % of peak |
|---|---|---|---|
| **Short-vol SPY 0.20 (non-compounding)** | $490,109 | 14.1% | −41.0% (2009 GFC) |
| Buy & hold SPY (price only) | $499,912 | 14.2% | **−24.8%** (2022) |
| Short-vol SPY 0.20 (COMPOUNDING, §below) | $100,254,353 | 55.1% | −64.0% (2018) |

**The humbling read:** the non-compounding short-vol book ≈ buy-and-hold SPY on total return
($490k vs $500k), and on a *fair* basis (buy-hold + ~1.8%/yr dividends vs short-vol + rf on
~half-idle cash) buy-hold likely **wins** on raw return — while also having a **shallower**
max drawdown (−25% vs −41%). The short-vol edge is the **smoother monthly ride** (Sharpe
~1.56 vs ~0.7) and **capital efficiency** (~half the $50k sits free), **not** raw return or
drawdown. Its real role is a diversifier/overlay, not a standalone return engine. (Window is
the 2009–2026 bull market, which flatters buy-hold, and excludes 2008.)

### 2.10 The compounding question — "increase risk as equity grows"

Today every rung risks `base_risk_pct ×` the **original $50k**, forever → non-compounding →
equity grows ~linearly and banked P&L sits in cash. If you instead size each rung off
**current equity**, returns compound geometrically (return-on-risk is scale-invariant ⇒
compounding = cumprod of the same monthly returns). On paper $490k → **$100M** (CAGR
14%→55%). **This is a fantasy:** (1) **capacity** — you cannot scale SPY put-spread size to
$100M at backtest prices; (2) **tail/ruin** — the compounding maxDD deepens to **−64% of
peak** (Nov-2018), with the same dynamic that took XIV / Feb-2018 "Volmageddon" to zero, and
this **excludes 2008**. Sizing *into* a short-vol book as equity grows means your biggest
bets sit on right before the crashes that kill short vol. **Sub-linear scaling or a fixed
dollar risk cap is the only safe middle ground** — full equity-proportional compounding is a
ruin machine.

### 2.11 Compounding sweet spot — where to STOP (SPX, the preferred vehicle)

**Why SPX, not SPY:** for held-to-expiry defined-risk vol selling SPX is the better
instrument — cash-settled, European (no early assignment), §1256 60/40 tax, deepest
liquidity, and it *is* the 1.65-Sharpe sleeve. SPY was only a granularity crutch on a small
account, and compounding fixes that (the ~$15.7k SPX lump shrinks as a % as equity grows).

**Policy:** compound (size off current equity) **up to a cap $C, then freeze** the dollar bet
— "always risk X% of a growing book" (ruin-prone) → "risk a fixed $ once grown" (safe). The
all-history maxDD is **cap-invariant** (−63.6%) because the worst drawdown is the 2009 GFC at
the *start* (equity ≈ $50k, before any cap binds) — so the honest risk metric is the
**forward (2011+) drawdown**, which the cap actually controls. SPX 0.32, worst single month
**−45.7%**:

| stop-compound cap | terminal | CAGR | maxDD (all-history) | maxDD (forward, 2011+) |
|---|---|---|---|---|
| non-comp ($50k) | $0.63M | 15.7% | −63.6% | −5.1% |
| $100k | $1.18M | 20.0% | −63.6% | −5.7% |
| **$200k (4×)** | **$2.21M** | **24.4%** | −63.6% | **−7.1%** |
| **$400k (8×)** | **$4.12M** | **29.0%** | −63.6% | **−10.5%** |
| $1M | $9.32M | 35.2% | −63.6% | −10.5% |
| full compounding | $1.82B | 83.3% | −63.6% | −39.5% |

**Verdict: stop compounding around 4–8× ($200k–$400k).** That captures most of the uplift
(CAGR 15.7% → 24–29%) while keeping the *forward* drawdown bounded (−7% to −10%). Beyond ~$1M
you pay steeply in forward risk for diminishing CAGR; full compounding's $1.8B / 83% is a
capacity fantasy + ruin. **Practical step (in SPX contracts):** one spread ≈ $15.7k margin —
start ~3 contracts at $50k, **add 1 contract per ~$16k of equity gained, stop adding at
~12–25 contracts (~$200k–$400k)**, then hold size and let cash accumulate. (Caveat: the
forward-DD read is benign partly because the 2009 GFC tail is front-loaded out of the
post-2011 window and 2008 is excluded entirely — a future vol spike at high equity is the
residual risk the cap exists to bound.)

---

## 3. FINDINGS

1. **The base case is real and current:** Sharpe **1.652** capital-blind through 2026-06-18,
   unchanged from the deployed figure.
2. **Tradeable on $50k two ways, both single-name S&P:** SPX direct (Sharpe 1.4–2.0, lumpy
   at ~31%/contract, ~19 entries/yr) or SPY direct (Sharpe 1.43–1.63, granular, ~27/yr, no
   silent gaps).
3. **It does NOT beat buy-and-hold SPY (the humbling finding):** over 2009–2026 the
   non-compounding SPY 0.20 book ($490k, 14.1% CAGR, −41% maxDD) ≈ buy-hold SPY ($500k,
   14.2%, **−25% maxDD**) on total return — and on a fair basis (buy-hold + dividends vs
   short-vol + rf on idle cash) buy-hold likely **wins** on raw return, with a **shallower**
   drawdown. The edge is the smoother monthly ride (Sharpe ~1.56 vs ~0.7) + capital
   efficiency (half the $50k free), so its real role is a **diversifier/overlay**, not a
   standalone return engine. (Bull-market window flatters buy-hold; excludes 2008.)
4. **Compounding is a ruin trap:** sizing off current equity turns 14%→55% CAGR on paper
   ($490k→$100M) but deepens maxDD to −64% and is un-realisable (capacity + short-vol tail).
   Sub-linear scaling / a fixed dollar risk cap is the only safe middle ground.
5. **Do NOT dilute into a 3-name book.** Adding QQQ (1.01) and especially IWM (0.438, −128%
   maxDD) drags the blend to ~1.0 Sharpe. Single-name S&P wins decisively.
6. **base_risk_pct is the only real lever** — it trades CAGR for drawdown and skip-rate.
   util_mean caps ~0.7 because the ramp+ gate forces idle cash in cheap vol (the cost of the edge).
7. **The overlay is leverage, not edge** — lifts raw return strictly in proportion to extra
   risk; Sharpe flat. Only a tight gate (rich_threshold 1.5) nudges risk-adjusted return
   (3-name best Sharpe 1.18 at 0.05/×2/1.5).
8. **Arithmetic ≫ geometric** — best 3-name cell prints 60.5% arithmetic but only 15.3%
   geometric CAGR. The CAGR is the deployable number; the arithmetic is a per-month-risk rate.

**Recommended deployable:** **SPX** (not SPY — cash-settled, §1256, the true 1.65 sleeve) at
base_risk_pct ≈ **0.20–0.32**, **sub-linear compounding capped at ~$200k–$400k (4–8×)**, gate
ramp+ (idle when vol cheap — live signal right now is SKIP, vrp_z −1.95). Drop IWM. Add ~1 SPX
contract (~$15.7k) per ~$16k of equity gained, stop at the cap. Over 2009–26 the conservative
version roughly matches buy-and-hold on raw return; the aggressive SPX 0.32 beats it but with
a far deeper tail (−64% vs −25%). Treat it as a risk-adjusted sleeve, sized to a drawdown you
can survive.

---

## 4. CAVEATS & LIMITATIONS

- Flat-vol BS ignores skew → modeled credit is a conservative floor (real fills ≥ modeled);
  no real-fill NBBO. Absolute return is approximate; the *harvest direction* and *relative*
  rankings are faithful.
- $50k ledgers exclude **2008** (min_date 2009-01-01); the capital-blind 1.652 includes it.
  QQQ/IWM sleeves only reach full breadth ~Oct 2010 (VXN/RVX begin 2009-09 + 252d vrp-z warmup).
- SPX margin scales with index level; the "base_risk_pct ≥ 0.31 to trade every year" floor is
  a today-level figure (SPX 7,501).
- SPX/0.32 Sharpe 1.98 is partly a capital-cap quality-filter artifact (in-sample fragile);
  the robust SPX read is base_risk_pct 0.20 → 1.43.
- maxDD past −100% = dollar drawdown exceeding starting capital, drawn from a higher banked
  peak (a real ruin-risk flag for aggressive cells, not an arithmetic glitch).
- T+1 settlement not modeled (margin frees at expiry, same-day reuse) — minor optimism on
  expiry-day entries.
- Same-date entries rotate priority unbiased-on-average; per-name attribution under capital
  binding is noisy by design (read skip_rate / fill_rate).

---

## 5. ARTIFACT INDEX (all committed on `feat/vrp-backtest-r2`)

| File | What |
|---|---|
| `src/uw_scan/reports/vrp_capital_account.py` | The $50k dollar ledger (CapitalConfig, desired_contracts, simulate_account, account_metrics) |
| `src/uw_scan/reports/vrp_macro_drawdown.py` | +SPY in INDEX_SPECS; +`_lake_spot` null-date guard |
| `scripts/research/vrp_capital_sweep.py` | 3-name 28-config sweep runner + reconciliation |
| `docs/research/vrp/capital-sweep-results.csv` | 3-name full trace (28 configs × 23 metrics) |
| `docs/research/vrp/base-case-mini-sweep-2026-06-23.csv` | Mini base-case run: SPX/SPY $50k (incl. maxDD) |
| `docs/research/vrp/equity-series-2026-06-23.csv` | Monthly equity: non-comp / compounding / buy-hold SPY |
| `docs/research/vrp/macro-capital-utilisation-findings.ipynb` | **Findings notebook (clean matplotlib charts, executed)** |
| `scripts/_build_vrp_capital_notebook.py` | Notebook builder (reads the CSVs above) |
| `docs/research/vrp/macro-capital-utilisation-verdict.md` | 3-name verdict |
| `docs/research/vrp/base-case-mini-run-summary-2026-06-23.md` | Mini run summary |
| `docs/research/vrp/MASTER-macro-short-vol-capital-utilisation-2026-06-23.md` | **This document** |
| `tests/unit/reports/test_vrp_capital_account.py` | 19 unit tests |
| `tests/integration/reports/test_vrp_capital_account_db.py` | 2 DB-gated tests (incl. reconciliation) |
| `docs/research/vrp/macro-short-vol-verdict.md` | Prior PR #150 verdict (the 1.65 winner origin) |

---

## Iteration 4 — Robustness (2026-06-23)

Five stress-tests of the deployed WINNER, **SPX-only**, each benchmarked against two fixed
references: the **iteration-3 SPX base case** (Sharpe **1.68**, CAGR 13.6%) and **SPY
buy-and-hold** (Sharpe **0.62**, CAGR 8.8%). The base-case arm reconciles to the
iteration-3 baseline exactly (both 1.680). Engine: six backward-compatible flags on
`simulate_account` (compounding, entry-weekday, entry-jitter, staggered tranche) +
`reports/vrp_robustness.py`. Full traces in `docs/research/vrp/iter4-*.csv`.
**Reproduce:** `uv run python scripts/research/vrp_robustness_run.py` (SEED=20260623; data
SPX+VIX `vol_index_daily` 2006→, SPY spot from the lake; ran on `option_wizard_local`).

### 0 · Smallest starting capital — two answers

SPX bull-put-spread max-loss **rises ~15× over 2007→2026** with spot (`$1,819` → `$28,408`),
so "smallest to start" and "smallest to run the strategy" are different numbers:

| | max-loss/contract | floor @ 20%-risk/spread |
|---|---|---|
| Smallest to **start** (cheapest 2007 spread) | $1,819 | **$10k** |
| Smallest to trade **throughout** (afford the recent spread) | $28,408 | **$143k** |

The $10k start-floor goes **dormant by ~2015** (can't afford a single spread once spot
rises), so all dollar experiments use the **$143k trade-throughout account**. *This is the
honest headline: defined-risk SPX vol-selling is a six-figure-capital strategy.* (`iter4-min-capital.csv`.)

### 1 · Extra position when rich — exposure, not edge (`iter4-extra-position.csv`)

| Variant (floor $143k account) | Sharpe | CAGR | maxDD %cap |
|---|---|---|---|
| base — non-comp | **1.680** | 13.6% | −90% |
| +contract overlay — non-comp | 1.668 | 14.3% | −117% |
| +staggered tranche — non-comp | **1.705** | 14.3% | −118% |
| base — **compounding** | 1.457 | **57.0%** | (util_peak 466×) |

The staggered second entry marginally *improves* Sharpe (1.705 vs 1.680); the same-day
contract overlay marginally *hurts* it (1.668) and deepens the drawdown. Both add exposure
without adding risk-adjusted edge. Compounding lifts CAGR to ~57% but amplifies drawdown
proportionally (the iteration-3 "fantasy"). Note the dollar account's deep −90% maxDD: at
~100% utilisation through 2008 the fully-deployed short-vol book is near-wipeout tail risk —
far worse than the capital-blind −25/−41% because utilisation amplifies it.

### 2 · Entry weekday matters modestly (`iter4-weekday.csv`, uncapped clean-signal basis)

| Mon | Tue | Wed | Thu | Fri | 5-day stride |
|---|---|---|---|---|---|
| 1.40 | **1.53** | 1.35 | 1.42 | 1.33 | **1.65** |

Single-weekday Sharpes cluster 1.33–1.53 — Tuesday best, Friday worst — but **all sit below
the natural 5-day stride (1.65)**. So the entry day has a modest effect (~0.2 Sharpe spread)
and committing to a fixed weekday is slightly worse than the stride, but the edge stays
robustly positive (>1.3) on every weekday.

### 3 · Bear-market start — rich vol → strong recovery harvest (`iter4-bear-start{,-path}.csv`)

| Start | n | Sharpe | +6m | +12m | +36m |
|---|---|---|---|---|---|
| 2015-08 | 260 | 1.87 | +17% | +65% | +182% |
| 2018-09 | 184 | 1.92 | +11% | +31% | +155% |
| 2020-02 | 146 | 2.58 | +35% | +100% | +167% |
| 2022-01 | 100 | 2.35 | +7% | +16% | +184% |

Starting the strategy **at** a bear-market top does **not** hurt — every start delivers
+150–180% over 36 months at Sharpe 1.9–2.6, *better* than the full-history base. Selling
into the elevated post-shock vol harvests rich premium on the recovery. Full lived equity
paths in `iter4-bear-start-path.csv`.

### 4 · Monte-Carlo robustness (`iter4-mc.csv` + `iter4-mc-trials.csv`, uncapped, SEED=20260623)

| Driver | mean | p5 | p95 |
|---|---|---|---|
| entry-timing jitter (±2 days) | 1.38 | 1.19 | 1.60 |
| stationary block bootstrap | 1.72 | 1.05 | 2.54 |
| randomised start (full history) | 2.00 | 1.60 | 2.73 |
| randomised start (GFC window — #5) | 1.75 | 1.62 | 2.02 |
| **config perturbation** (overfit test) | 1.37 | **1.05** | 1.64 |

The headline: **config-perturbation p5 = 1.05** — jittering the tuned knobs (short_delta
0.20–0.30, hold 20–40, ramp_full_z 0.3–0.7) keeps Sharpe above 1.0, so the result is **not a
knife-edge overfit**. Entry-timing jitter (p5 1.19) and the bootstrap CI (p5 1.05) corroborate.
The GFC-windowed random-start (1.75) is the #5 bear-extension — entering short-vol *during*
2007–2009 still clears Sharpe 1.6+.

### Look-ahead audit

Every input to the entry decision is known at the entry-day close: `vrp_z` (trailing-252
z-score), `rv` (trailing-20 realized vol), IV (contemporaneous VIX). Settlement walks the
realized forward path — the *outcome* of a decision already made, not an input. The only
forward-looking risk is **in-sample config selection**, which §4's config-perturbation
quantifies (survives, p5 1.05).

**Caveat — compounding `util_peak` > 1:** for compounding rows `util_peak` is deployed margin
÷ *initial* capital, so it exceeds 1.0 (e.g. 466×) as equity grows — read it as
leverage-vs-start, not a cap breach.

### Iteration-4 artifacts

| Path | What |
|---|---|
| `src/uw_scan/reports/vrp_robustness.py` | min-capital, buy-hold, geometric metrics, weekday/bear/MC drivers |
| `scripts/research/vrp_robustness_run.py` | runner (writes the 7 CSVs) |
| `docs/research/vrp/iter4-*.csv` | full traces (per-config + per-trial) |
| `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` | executed findings notebook (4 figures) |
| `tests/unit/reports/test_vrp_robustness.py` | 12 unit tests |
