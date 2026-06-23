# Single-Name Iron-Condor — Verdict (2026-06-22)

**Question.** The VRP research layer established that rich single-name vol *realizes*
a harvest (IV > RV) by sector. Is that harvest **tradeable** as a defined-risk
16Δ/8Δ iron condor?

**Method.** Flat-vol Black–Scholes condor priced at each RICH day's spot + IV,
settled hold-to-expiry against the corporate-action-adjusted realized price.
Entry-spaced (one position per name at a time — trade only when flat). Honest
latest-40% holdout. 82 single-name tickers, ~11 months (2025-07 → 2026-06), local
warm store. Full detail + charts: [`vrp-tradable-condor-findings.ipynb`](./vrp-tradable-condor-findings.ipynb).

## Findings

1. **Signal is real at the measurement layer.** The single_name RICH bucket is
   `HARVEST_SELLABLE` at T+5 / T+20 (mean realized VRP ≈ 0.08 vol pts) — but decays
   to `NONE` by T+60 (single names blow through over longer holds).
2. **The naive backtest was overlap inflation.** Opening a condor on *every* RICH
   day gave T+20 holdout **+$110,883 / 72% win** — but ~**97%** of that P&L was the
   same rich names re-counted dozens of times. Not tradeable.
3. **Entry-spaced (realistic) T+20 holdout: 163 trades, 66% win, −$1,491, 32.5%
   breach.** No horizon shows a robust spaced edge — T+5 is clearly negative; T+60
   was +$5,861 on only **23 trades** (noise).
4. **Win/loss asymmetry is the killer.** A 16Δ condor wins ~+0.17 ROR and loses
   ~−0.63 ROR → it needs a **~79% win-rate** to break even on risk. The spaced book
   gets 66%.
5. **Credit fragility — the decisive caveat.** A ±**$0.09/share** credit shift flips
   the holdout sign. The result is **thinner than one leg's bid/ask spread**, so the
   flat-vol backtest *cannot distinguish a small edge from a small loss*. A real
   answer needs real-fill NBBO (forward-only; recorder designed, not yet running).
6. **Sample collapse.** ~2 spaced trades/name → per-ticker P&L is statistically
   empty.

## Verdict

**No deployable edge as modeled.** The VRP signal is real, but the wide defined-risk
condor *under-monetizes* it: it sells OTM (16Δ/8Δ) where little VRP lives, caps the
harvest at a small credit (~14% of the wing width), and keeps the full breach tail.
A positive VRP buys a decent win-rate (66–72%) — just not the ~79% the structure
needs.

**Parked, not killed.** The result lives inside the bid/ask spread → *inconclusive*,
not *proven negative*. Resolving it requires the forward NBBO recorder (real fills).

## Pivot

Effort moves to **systematically harvesting the macro VRP** (SPY / SPX / QQQ / IWM),
where the case is structurally better:

- **Premium is well-sampled and durable** — `index_macro` RICH is `HARVEST_SELLABLE`
  at *all* horizons (n = 350 pooled), unlike single-name which dies at T+60;
  `sector_etf` T+20 harvest (0.073) is the richest of any class.
- **Tight spreads** → flat-vol model error is smallest exactly here.
- **No earnings landmines** — indices/ETFs don't report.
- **Structure can match a directional view** — bull put credit spread on
  bullish large-caps (SPY/SPX/QQQ), iron condor on neutral IWM. See the macro
  harvest effort (next).
