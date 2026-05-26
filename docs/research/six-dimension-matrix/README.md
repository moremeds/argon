# 6-Dimension Options Matrix — Research Set

> **Start here for execution**: [`../../plans/2026-05-15-cockpit-matrix-plan.md`](../../plans/2026-05-15-cockpit-matrix-plan.md) is the single actionable plan that supersedes the per-doc build sequences in `08 §4` and `09 §9`. The 10 research docs in this directory are background reference — read them when the plan points you to a specific section, not front-to-back.

**Status**: research idea (2026-05-14). Source: FutureAlpha podcast Season 02 Episode 10 finale.

## Product direction (2026-05-14 decision)

Ships as a dedicated **Cockpit** section: `/cockpit/[ticker]` with 5 tabs.

- **Universe**: SPX, SPY, QQQ, IWM (4 tickers). Single-name out of scope per Limitation #4.
- **AI scope**: Stock-detail AI (`reports/trade_insights_ai.py:965`) keeps the `"vanna"/"charm"` blacklist — single-name AI does not reason over these dimensions. A *separate* index-only AI (`reports/cockpit_ai.py`) consumes the matrix.
- **Tabs**: **State** · **Dealer** (Vanna + Charm) · **Surface** (Skew + Term) · **Flow + IM** · **VRP** — grouped by collinearity cluster per Limitation #1.

Build sequence in [`08-implementation-gaps.md`](08-implementation-gaps.md) §4.

## ⚠️ Backtest blocked (verified 2026-05-15)

The 2018-2025 historical backtest plan in `09 §3` is **infeasible on the current UW subscription** — UW serves only the last 30 trading days for per-strike greeks/exposures (verified by `scripts/uw_history_spike.py`). Skew is the one exception (~1 year window).

Path forward: ship Cockpit as **display-only**, accumulate forward via the nightly worker, do skew-only Phase 0.5 validation immediately, and spend $30 of our $40 UW Data Shop credit on a **30d SPY Option Chains validation purchase** to derisk the eventual $720 historical-data buy. Re-evaluate the full historical-data-purchase decision after 6 months of live `matrix_state_snapshots`.

Full result and options: [`reviews/2026-05-15-uw-history-spike.md`](reviews/2026-05-15-uw-history-spike.md).
Codex review of §0 operational definitions: [`reviews/2026-05-15-codex-section0.md`](reviews/2026-05-15-codex-section0.md).

## Reading order

1. **[`00-overview.md`](00-overview.md)** — Framework summary, 4-step decision tree, 3 scenarios, position translation, takeaways. **Start here.**
2. **[`01-vanna.md`](01-vanna.md)** through **[`06-vrp.md`](06-vrp.md)** — Per-dimension deep dives with definition, framework reading, academic citations (verified), misreadings, single-name caveats, current `uw_scan` mapping, derived metrics required.
3. **[`07-limitations.md`](07-limitations.md)** — 8 limitations validated against literature (collinearity, stress correlation breakdown, data lag, single-name vs index, flow ≠ ground truth, you're not the dealer, 0DTE intraday hijacking, **per-dim credibility uneven + joint claim unvalidated**).
4. **[`08-implementation-gaps.md`](08-implementation-gaps.md)** — Cross-reference with current `uw_scan` setup. Per-dimension file paths. Recommended build sequence. New tables required.
5. **[`09-backtest-plan.md`](09-backtest-plan.md)** — Falsification criteria, 4 strategies, robustness tests, phasing, open research questions.

## The six dimensions at a glance

| # | Dim | Metaphor | Formula | Time window | Status |
|---|---|---|---|---|---|
| 1 | Vanna | 风/wind | ∂Δ/∂σ | 1–3 days | ⚠️ DB only |
| 2 | Charm | 重力/gravity | ∂Δ/∂t | 1–5 days | ⚠️ DB only |
| 3 | Skew | 形状/shape | OTM-put IV − OTM-call IV | 2–8 weeks | ✅ full (reference impl) |
| 4 | Term | 节奏/rhythm | front IV − back IV | hours–weeks | ✅ curve; ❌ classifier |
| 5 | IM + Flow | — | 0.7979 × straddle/spot + 4 flow footprints | real-time | ⚠️ Flow full; IM missing |
| 6 | VRP | — | VIX_t² − subsequent RV² | 4–12 weeks | ⚠️ proxy only |

## Decision tree (4 steps)

1. **Consistency** — 6 same direction = proceed; conflict = NO-TRADE
2. **Local vs global** — event-type isolate / liquidity-type portfolio-hedge
3. **Time window** — short (Vanna+Charm+IM) / mid (Skew+Term) / long (VRP+far Skew+Hedge Flow)
4. **Invalidation** — write down "if X then close" before entry; can't write → no entry

## Key sources cited

All citations verified during research (2026-05-14). The full bibliography by dimension is in the per-dimension docs. Headline sources:

- **VRP**: Carr & Wu (2009 RFS), Bollerslev/Tauchen/Zhou (2009 RFS), Drechsler & Yaron (2011 RFS), Bekaert & Hoerova (2014 JEcon), Bollerslev & Todorov (2011 JF)
- **Skew**: Bates (1991 JF, Crash of '87), Rubinstein (1994 JF), Bakshi/Kapadia/Madan (2003 RFS), Foresi & Wu (2005 JoD), Pan (2002 JFE)
- **Term**: Mixon (2007 JEF), Johnson (2017 JFQA), Britten-Jones & Neuberger (2000 JF)
- **Vanna/Charm/Pinning**: Castagna & Mercurio (2007 Risk), Gârleanu/Pedersen/Poteshman (2009 RFS), Ni/Pearson/Poteshman (2005 JFE), Avellaneda & Lipkin (2003 QF), Baltussen et al. (2021 JFE), Barbon & Buraschi (2021 SSRN)
- **Flow/Microstructure**: Easley/O'Hara/Srinivas (1998 JF), Pan & Poteshman (2006 RFS), Bollen & Whaley (2004 JF), Lee & Ready (1991 JF), Savickas & Wilson (2003 JFQA) — *options-specific Lee-Ready accuracy*, Cremers & Weinbaum (2010 JFQA)
- **0DTE**: Dim/Eraker/Vilkov (2024 SSRN), Brogaard/Han/Won (2024 SSRN)
- **Implied Move math**: Brenner & Subrahmanyam (1988 FAJ — the √(2/π) ≈ 0.7979 derivation)
- **Textbooks**: Natenberg *Option Volatility & Pricing* 2e, Sinclair *Volatility Trading* 2e, Hasbrouck *Empirical Market Microstructure*, Foucault/Pagano/Röell *Market Liquidity*, Bouchaud et al. *Trades, Quotes and Prices*

## Status

These docs are **research-stage**. They capture the framework, validate it against literature, map it to the current codebase, and propose a backtest. They do **not** constitute trading advice or a production specification — see [`09-backtest-plan.md`](09-backtest-plan.md) §1 for the falsification criteria that must be empirically resolved before any dimension here becomes a production trading signal.
