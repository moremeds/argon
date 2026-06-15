# GRG — Gamma Rotation Gap: evidence check

> SPY-vs-TLT cross-asset dealer-gamma divergence. Ported from radon
> (`scripts/gamma_rotation_gap.py`). This note records what the academic /
> practitioner literature actually supports, so the indicator is presented
> honestly: **descriptive, not predictive.** (Mirrors the VCG precedent —
> see project memory `project_vcg_forward_returns_descriptive`.)

## The thesis, in four claims

1. Dealer net gamma (GEX) in equity index ETFs (SPY) mechanically
   dampens/amplifies realized vol (positive = cushion, negative = whip).
2. The same mechanic applies to bond ETFs (TLT) for duration vol.
3. A SPY-vs-TLT gamma divergence signals a cross-asset risk-off rotation.
4. The gap has tradeable / forward-predictive content.

## Verdict

| Claim                                              | Grounding                                                                                                                                     | Verdict                                                                     |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1. Gamma → realized vol (equity index)             | Peer-reviewed                                                                                                                                 | **Established mechanic.**                                                   |
| 2. Same mechanic in bonds (TLT)                    | Peer-reviewed for MBS/swaption **convexity hedging**, NOT TLT option gamma                                                                    | **Mechanism real; TLT-GEX application is an analogy, not a tested result.** |
| 3. SPY-vs-TLT gamma divergence = risk-off rotation | Vendor/blog only; flight-to-safety regimes exist but not identified from gamma                                                                | **Practitioner folklore + novel untested combination.**                     |
| 4. Gap is tradeable / forward-predictive           | No peer-reviewed support; one quasi-academic source shows post-2020 decay; our YTD backtest (below) shows the watch days LEAD, not coincident | **Speculative. Not presented as established.**                              |

## Forward-return backtest (YTD 2026, first pass)

A first-pass forward-return backtest of the gate-confirmed TOP_WATCH /
BOTTOM_WATCH events against SPY's actual daily close (warm-store `daily_ohlc`),
30-session forward window. Computed in `cards/grg_scoring._annotate_event_backtest`,
persisted on every snapshot (`events.stats` + per-event `lead_sessions` /
`extreme_gap_pct` / `fwd_20d_pct`), and surfaced in the UI.

| Event        | Date       | SPY @ signal | Lead to adverse extreme | Further move              | fwd +20d |
| ------------ | ---------- | ------------ | ----------------------- | ------------------------- | -------- |
| TOP-WATCH    | 2026-05-13 | 742.31       | 13 sessions             | **+2.33%** (kept rising)  | −0.61%   |
| BOTTOM-WATCH | 2026-02-20 | 689.43       | 26 sessions             | **−8.33%** (kept falling) | −5.93%   |
| BOTTOM-WATCH | 2026-02-19 | 684.48       | 27 sessions             | −7.67%                    | −3.61%   |
| BOTTOM-WATCH | 2026-02-13 | 681.75       | 30 sessions             | −7.30%                    | −1.87%   |

Context: the YTD low was **2026-03-30 @ 631.97**, the YTD high **2026-06-02 @
759.57**. Aggregate: 3 bottom-watches led the low by a median **27 sessions**
(median **−7.67%** further); 1 top-watch led the high by **13 sessions**
(**+2.33%** further).

**Conclusion — lead, not coincident; not inverted.** The labels are correct by
construction (TOP*WATCH fires on complacency/highs, BOTTOM_WATCH on stress/lows),
but the watch signals **fire early** — weeks before the actual extreme, with
price continuing in the pre-signal direction afterward. Plotted on the price
line they \_look* inverted (a "bottom" dot followed by a further −8% reads as a
local top); that visual inversion is a symptom of the lead timing, not a sign
error. Two caveats keep this descriptive: the sample is tiny (n=4 ≈ 2 episodes),
and historical events are scored with `spy_flip_gap_pct=None` (4 of 5 gates), a
weaker bar than the live headline signal. A **multi-year, per-regime
catastrophic-degradation** backtest (the VCG-style validation gate) remains the
next step before any predictive claim.

## Sources (verified)

**Claim 1 — gamma → vol (supports):**

- Barbon & Buraschi, "Gamma Fragility" (2021), SSRN 3725454 — negative dealer gamma → amplification, positive → suppression. (Working paper.)
- Baltussen, Da, Lammers & Martens, "Hedging Demand and Market Intraday Momentum," JFE 142(1) (2021) — option-MM + leveraged-ETF gamma hedging drives intraday momentum across equities, bonds, commodities, FX. (Peer-reviewed; also seeds claim 2.)
- Soebhag, "Option Gamma and Stock Returns," J. Empirical Finance 74 (2023) — net gamma predicts future realized vol (hedging channel).
- Dim, Eraker & Vilkov, "0DTEs: Trading, Gamma Risk and Volatility Propagation" (2023), SSRN 4692190 — higher dealer net gamma → lower intraday RV.
- Ni, Pearson & Poteshman, "Stock Price Clustering on Option Expiration Dates," JFE 78(1) (2005) — MM hedge rebalancing mechanically moves the underlying.
- Gârleanu, Pedersen & Poteshman, "Demand-Based Option Pricing," RFS 22(10) (2009) — dealers net short options bear hedging demand (structural premise).
- SqueezeMetrics GEX white paper (c. 2017) — practitioner origin of the GEX vocabulary; **not peer-reviewed, no verifiable author.**

**Claim 2 — bond/rates convexity hedging (supports the mechanism, NOT TLT options):**

- Hanson, "Mortgage Convexity," JFE 113(2) (2014).
- Malkhozov, Mueller, Vedolin & Venter, "Mortgage Risk and the Yield Curve," RFS 29(5) (2016).
- Perli & Sack, "Does Mortgage Hedging Amplify Movements in Long-Term Interest Rates?" Fed FEDS 2003-49 (2003).
- **Caveat:** these are MBS/swaption convexity-hedging flows — much larger and structurally different from TLT-listed-option dealer gamma. The TLT-GEX lens is a reasonable analogy, not what these papers tested.

**Claims 3 & 4 — the gap signal (no peer-reviewed support):**

- Flight-to-safety regimes are real: Baele & Bekaert et al., "Flights to Safety," NBER w19095 (RFS) — but FTS is identified from returns/correlation/VIX, **not** gamma.
- The cross-asset gamma-gap-as-rotation-signal appears only in vendor material (SpotGamma, Barchart, blogs). No peer-reviewed test of its forward-return content; the one quasi-academic GEX-predictiveness source (a DiVA student thesis) reports the effect weakening post-2020.

## How GRG is presented in argon

- The UI labels GRG a **descriptive cross-asset gamma-state indicator** (InfoTooltip in `GrgSubTab.tsx`), explicitly noting the gap-signal is an unvalidated hypothesis. The chart's top/bottom dots are framed as **early-warning watch signals, not the exact turn** (legend `TOP-WATCH` / `BOTTOM-WATCH`, per-event lead-time, and a backtest caption — see the section above).
- **Flip definition (intentional deviation from radon):** the flip gate + `spot_vs_flip` use argon's **canonical persisted gamma flip** (`gex_snapshots` `levels.gex_flip.strike`, the same flip the GEX tab shows) — one flip definition app-wide. radon instead recomputes a last-negative→positive-crossing-at/below-spot flip from by-strike rows. Consequence: when argon's flip sits above spot, GRG's flip gate / `spot_vs_flip` can differ in sign from radon. The headline GRG residual, pair state, and summary are flip-independent, so this only affects one of six gates.
- A **first-pass YTD forward-return backtest is now done** (see section above): it shows the gate-confirmed top/bottom days LEAD the turn by weeks (descriptive, small-sample). A **multi-year, per-regime catastrophic-degradation** backtest (the VCG-style validation gate) remains the **next** gate before any predictive claim.

## Code map

- Scoring (pure, ported): `src/uw_scan/cards/grg_scoring.py`
- Scanner (UW history + warm-store flip/spot + persist): `src/uw_scan/scanners/grg.py`
- Storage: `src/uw_scan/storage/grg_snapshot_repository.py` + migration `071_grg_snapshots.sql`
- API: `GET /api/regime/grg`, `POST /api/regime/grg/scan` (`api/routers/regime.py`)
- UI: `web/components/regime/GrgSubTab.tsx` + `GrgDivergenceChart.tsx`, route `web/app/regime/[[...tab]]/`
- Schedule: `regime_grg_scan` (uw-group, every 15 min RTH + post-close)
