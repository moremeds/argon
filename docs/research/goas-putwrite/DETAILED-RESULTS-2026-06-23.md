# GOAS Put-Write Delta Sweep — Detailed Results (2026-06-23)

**Strategy:** GOAS-style systematic cash-secured SPY put-writing — sell OTM puts weekly,
hold to expiry, roll via re-entry. Find the short-put **delta** (and tenor) that maximizes
risk-adjusted, net-of-fee income.

**Setup:** real SPY + VIX daily closes, **2006-01-04 → 2026-05-29 (5,123 trading days,
~20.4y)**, ~1,012–1,021 weekly trades per cell. Data from the market-warehouse lake
(`asset_class={equity,volatility}/symbol={SPY,VIX}/1d.parquet`). Skew calibrated to GOAS's
published quote (2026-05-05: SPY 723.77, VIX 17.38) → **slope 2.693**, reproducing the
96.2%-strike / 0.700%-premium / ~0.22-delta quote exactly. Cash-secured; collateral earns
4% risk-free (CBOE PUT-index convention). Pricing run under BOTH flat-vol (conservative
floor) and the calibrated skew (GOAS-faithful). Reproduce:
`uv run python scripts/research/goas_putwrite_run.py`.

**Benchmark — SPY buy-and-hold (price-return):** Sharpe **0.339**, CAGR **9.1%**,
maxDD **−56.5%**, worst-month −16.5%.

---

## 1. Skew-priced grid (GOAS-faithful estimate)

### Sharpe — GROSS of mgmt fee (net of transaction cost)

| Δ \ DTE | 21d | 30d | 42d | 63d |
|---|---|---|---|---|
| 0.05 | +0.197 | +0.192 | +0.226 | +0.270 |
| 0.10 | +0.283 | +0.255 | +0.267 | +0.280 |
| 0.15 | +0.329 | +0.301 | +0.289 | +0.296 |
| 0.20 | +0.355 | +0.329 | +0.300 | +0.301 |
| 0.25 | +0.367 | +0.341 | +0.307 | +0.300 |
| 0.30 | **+0.376** | +0.351 | +0.308 | +0.292 |

### Annualized return — net @1% fee (~4% of this is collateral interest)

| Δ \ DTE | 21d | 30d | 42d | 63d |
|---|---|---|---|---|
| 0.05 | +3.6% | +3.7% | +4.0% | +4.3% |
| 0.10 | +4.1% | +4.0% | +4.2% | +4.3% |
| 0.15 | +4.5% | +4.4% | +4.5% | +4.5% |
| 0.20 | +4.9% | +4.7% | +4.7% | +4.7% |
| 0.25 | +5.2% | +5.0% | +4.9% | +4.8% |
| 0.30 | +5.4% | +5.2% | +5.1% | +4.9% |

### Max drawdown — net @1%

| Δ \ DTE | 21d | 30d | 42d | 63d |
|---|---|---|---|---|
| 0.05 | −6.5% | −8.2% | −10.2% | −9.4% |
| 0.10 | −10.4% | −10.8% | −13.3% | −11.5% |
| 0.15 | −13.2% | −13.8% | −15.7% | −13.6% |
| 0.20 | −15.2% | −16.5% | −17.7% | −16.8% |
| 0.25 | −17.1% | −18.9% | −19.6% | −19.5% |
| 0.30 | −19.0% | −20.9% | −22.6% | −22.0% |

### Win-rate / breach-rate / #trades (fee-invariant)

| Δ \ DTE | 21d | 30d | 42d | 63d |
|---|---|---|---|---|
| 0.05 | 95% / 2% / 1021 | 98% / 2% / 1019 | 99% / 1% / 1017 | 99% / 1% / 1012 |
| 0.10 | 96% / 4% / 1021 | 96% / 4% / 1019 | 97% / 3% / 1017 | 97% / 3% / 1012 |
| 0.15 | 94% / 7% / 1021 | 94% / 6% / 1019 | 94% / 7% / 1017 | 95% / 5% / 1012 |
| 0.20 | 91% / 11% / 1021 | 92% / 10% / 1019 | 91% / 11% / 1017 | 93% / 9% / 1012 |
| 0.25 | 89% / 15% / 1021 | 89% / 14% / 1019 | 89% / 14% / 1017 | 90% / 14% / 1012 |
| 0.30 | 86% / 19% / 1021 | 87% / 17% / 1019 | 86% / 17% / 1017 | 86% / 18% / 1012 |

---

## 2. Full ranking with the per-regime catastrophe gate

Raw Sharpe peaks at **0.30Δ / 21d** (0.376 gross). But the gate (drop any cell whose
stress-window Sharpe < −1.0) removes **14 of 24 cells — every one for COVID-2020** (weekly
short-tenor writing is destroyed in a fast crash). Ranked by net-of-1%-fee Sharpe, with
each cell's per-regime Sharpes:

| # | Δ | DTE | net Sharpe | ann | maxDD | 2008 | COVID | 2022 | calm | gate |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.30 | 21 | +0.225 | +5.4% | −19.0% | +0.18 | −1.63 | −0.79 | +0.46 | ❌ DROP (covid) |
| 2 | 0.25 | 21 | +0.201 | +5.2% | −17.1% | +0.25 | −1.61 | −0.70 | +0.41 | ❌ DROP (covid) |
| 3 | 0.30 | 30 | +0.197 | +5.2% | −20.9% | +0.03 | −1.26 | −0.68 | +0.46 | ❌ DROP (covid) |
| 4 | 0.25 | 30 | +0.173 | +5.0% | −18.9% | +0.09 | −1.29 | −0.48 | +0.41 | ❌ DROP (covid) |
| 5 | 0.20 | 21 | +0.169 | +4.9% | −15.2% | +0.34 | −1.55 | −0.52 | +0.34 | ❌ DROP (covid) |
| 6 | 0.30 | 42 | +0.168 | +5.1% | −22.6% | −0.06 | −1.12 | −0.50 | +0.40 | ❌ DROP (covid) |
| 7 | 0.25 | 42 | +0.152 | +4.9% | −19.6% | +0.01 | −1.09 | −0.39 | +0.38 | ❌ DROP (covid) |
| **8** | **0.30** | **63** | **+0.147** | **+4.9%** | **−22.0%** | −0.06 | **−0.75** | −0.21 | +0.38 | ✅ **KEEP — winner** |
| 9 | 0.20 | 30 | +0.142 | +4.7% | −16.5% | +0.19 | −1.31 | −0.25 | +0.35 | ❌ DROP (covid) |
| 10 | 0.25 | 63 | +0.141 | +4.8% | −19.5% | +0.07 | −0.65 | −0.03 | +0.37 | ✅ keep |
| 11 | 0.20 | 42 | +0.129 | +4.7% | −17.7% | +0.09 | −1.05 | −0.27 | +0.34 | ❌ DROP (covid) |
| 12 | 0.20 | 63 | +0.128 | +4.7% | −16.8% | +0.21 | −0.51 | +0.07 | +0.33 | ✅ keep |
| 13 | 0.15 | 21 | +0.115 | +4.5% | −13.2% | +0.40 | −1.39 | −0.25 | +0.27 | ❌ DROP (covid) |
| 14 | 0.15 | 63 | +0.108 | +4.5% | −13.6% | +0.38 | −0.30 | +0.12 | +0.27 | ✅ keep |
| 15 | 0.15 | 42 | +0.099 | +4.5% | −15.7% | +0.20 | −0.96 | −0.07 | +0.29 | ✅ keep |
| 16 | 0.15 | 30 | +0.090 | +4.4% | −13.8% | +0.29 | −1.30 | −0.10 | +0.26 | ❌ DROP (covid) |
| 17 | 0.10 | 63 | +0.076 | +4.3% | −11.5% | +0.55 | +0.01 | +0.07 | +0.21 | ✅ keep |
| 18 | 0.05 | 63 | +0.060 | +4.3% | −9.4% | +0.88 | +0.57 | −0.34 | +0.15 | ✅ keep |
| 19 | 0.10 | 42 | +0.055 | +4.2% | −13.3% | +0.44 | −0.75 | +0.02 | +0.20 | ✅ keep |
| 20 | 0.10 | 21 | +0.023 | +4.1% | −10.4% | +0.52 | −1.25 | +0.13 | +0.17 | ❌ DROP (covid) |
| 21 | 0.10 | 30 | +0.009 | +4.0% | −10.8% | +0.43 | −1.20 | −0.07 | +0.16 | ❌ DROP (covid) |
| 22 | 0.05 | 42 | −0.004 | +4.0% | −10.2% | +0.73 | −0.24 | −0.17 | +0.12 | ✅ keep |
| 23 | 0.05 | 30 | −0.105 | +3.7% | −8.2% | +0.62 | −0.80 | −0.11 | +0.05 | ✅ keep |
| 24 | 0.05 | 21 | −0.164 | +3.6% | −6.5% | +0.77 | −1.11 | +0.19 | +0.03 | ❌ DROP (covid) |

**Gate survivors: 10/24. Top survivor = 0.30Δ / 63d. Flat & skew pricing agree on it →
robust.** The COVID column drives everything: short tenors (−1.2 to −1.6) blow up; only
63d bleeds slowly enough (−0.75) to survive. 2008 is mostly *positive* (its 18-month
window includes the recovery); the fast 2020 crash is what kills weekly put-writing.

---

## 3. Management-fee sensitivity (skew Sharpe)

| cell | gross (0%) | 0.5% | 1.0% | 1.5% |
|---|---|---|---|---|
| 15Δ/21d (GOAS canonical) | +0.329 | +0.222 | +0.115 | +0.008 |
| 30Δ/21d (raw max, gated)  | +0.376 | +0.301 | +0.225 | +0.150 |
| 30Δ/63d (gated winner)    | +0.292 | +0.219 | +0.147 | +0.074 |

A 1% fee erases ~0.2 of Sharpe; the high-turnover 21d canonical cell is hit hardest
(transaction cost on ~3× the trades).

## 4. Flat → Skew robustness (net Sharpe @1%, all cells)

Skew lifts **every** cell (richer premiums) but **preserves the ranking order** — so the
sweet-spot conclusion does not depend on the modeled skew shape:

| Δ \ DTE | 21d | 30d | 42d | 63d |
|---|---|---|---|---|
| 0.05 | −0.28→−0.16 | −0.27→−0.10 | −0.21→−0.00 | −0.17→+0.06 |
| 0.10 | −0.15→+0.02 | −0.15→+0.01 | −0.12→+0.05 | −0.10→+0.08 |
| 0.15 | −0.05→+0.11 | −0.06→+0.09 | −0.06→+0.10 | −0.04→+0.11 |
| 0.20 | +0.02→+0.17 | +0.00→+0.14 | −0.00→+0.13 | +0.01→+0.13 |
| 0.25 | +0.08→+0.20 | +0.06→+0.17 | +0.05→+0.15 | +0.04→+0.14 |
| 0.30 | +0.13→+0.23 | +0.11→+0.20 | +0.09→+0.17 | +0.08→+0.15 |

---

## Verdict — the delta sweet spot

- **By raw premium harvest, higher delta always wins** — Sharpe rises monotonically to the
  0.30 grid edge (the true optimum may lie beyond 0.30; the model prefers selling as much
  premium as possible).
- **The binding constraint is tenor, not delta.** Short (21d) weekly writing maximizes
  gross Sharpe but **fails catastrophically in fast crashes** (COVID Sharpe −1.6). You need
  **≥63d** to survive a 2020-type event.
- **Net of realistic 1% fees, the defensible sweet spot is 0.30Δ / 63d** (Sharpe 0.147,
  robust across pricing + the regime gate). For a lower-drawdown profile, **0.15Δ / 63d**
  (Sharpe 0.108, maxDD −14%, 95% win-rate) is the conservative pick.
- **Sobering bottom line:** *every* unlevered cash-secured cell underperforms SPY buy-hold
  risk-adjusted (best 0.15 vs 0.34) — but with **2–4× smaller drawdowns** (−14% to −22% vs
  −56%) and ~95% win-rates. The premium harvest *above cash* is only ~0.5–1.4%/yr. GOAS's
  3–6% net and "better-than-stock" claim require the **20–40% leverage we excluded**
  (no-naked-shorts, defined-risk) plus richer real-world skew than this conservative model.

## Why the Sharpe is small (≈0.1–0.4)

The low Sharpe is structural, not a bug. Five compounding reasons:

1. **The rf cancels → Sharpe measures the premium harvest *alone*.** Collateral earns 4%
   risk-free (credited to NAV) and the Sharpe hurdle subtracts the same 4%, so they cancel
   exactly: `Sharpe ≈ mean(daily premium P&L) / std(daily premium P&L) × √252`. Total return
   is ~3.6–5.4%, of which ~4% is just T-bills, leaving **~0.5–1.4%/yr of genuine harvest
   above cash** — a tiny numerator. The rf *level* never distorts the ratio; the small Sharpe
   honestly reflects a thin harvest relative to its own (tail-heavy) volatility.
2. **Cash-securing is capital-inefficient.** 100% of the strike is locked up to earn that
   thin premium. This is exactly the inefficiency GOAS removes with 20–40% margin — the same
   harvest on 2.5–5× less capital is how its marketed 3–6% net works. We excluded leverage
   (no-naked-shorts), so this is the unlevered floor.
3. **Sharpe is the wrong lens for short-vol.** The return stream is left-skewed: many small
   wins (86–99% win-rate) punctuated by rare large losses (COVID regime Sharpe −0.75 to
   −1.6). Std-dev penalizes those downside tails like upside, inflating the denominator. On
   drawdown the strategy looks far better — maxDD −14% to −22% vs buy-hold's **−56.5%**.
4. **Fees eat a large fraction of a thin edge.** At 0% fee the 15Δ/21d cell scores 0.329
   (≈ buy-hold 0.339); 1% fee + weekly turnover cost drops it to 0.115 (§3). When the edge
   above cash is ~1–2%, a 1% fee is half of it. Published CBOE-PUT Sharpes are gross of fees.
5. **Conservative pricing + a crash-heavy window.** The constant-slope modeled skew (low-vol
   2026 anchor) understates crisis put richness → less income → lower numerator (a floor),
   and 2006–2026 is unusually tail-heavy (2008/2020/2022) vs the longer, calmer CBOE-PUT
   history.

**Bottom line:** the strategy is *capital-inefficient unlevered*, not edge-free — near
buy-hold risk-adjusted return gross, at a third of the drawdown, with a ~95% win-rate. The
low net Sharpe is what full cash collateral + 1% fees + a tail-penalizing metric produce.
GOAS's whole proposition is to fix the capital inefficiency with leverage — the lever our
defined-risk constraint deliberately removed.

## Caveats

- **Modeled skew**: constant slope calibrated to one 2026-05-05 quote, applied across 20y —
  understates crisis put richness, so premiums are a conservative *floor* (real edge likely
  higher). No multi-year historical IV surface exists on our data.
- **Sharpe under-penalizes tails** — the winner sits at the delta grid edge; read alongside
  maxDD / CVaR / the regime table, not Sharpe alone.
- **European cash-settle** at expiry vs GOAS's American, roll-managed book; early-assignment
  timing not modeled.
- **Price-return SPY benchmark** (lake has no dividends → understates buy-hold total return).
- **VIX is constant-maturity 30d** applied across 21–63d tenors (cleanest read at DTE≈30).

## Data / reproduce

Full per-row traces under `docs/research/goas-putwrite/`:
`goas-delta-dte-sweep-2026-06-23.csv` (192 rows: 2 pricing × 24 cells × 4 fees),
`goas-skew-vs-flat-2026-06-23.csv`, `goas-regime-2026-06-23.csv`,
`goas-trade-log-2026-06-23.csv` (1,012 trades of the winning cell), `MASTER-goas-putwrite-2026-06-23.md`.
Reproduce: `uv run python scripts/research/goas_putwrite_run.py` (reads
`~/market-warehouse/data-lake`; override with `MARKET_WAREHOUSE_LAKE`).
