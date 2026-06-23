# GRG — Gamma Rotation Gap (results)

SPY-vs-TLT cross-asset **dealer-gamma divergence** as a risk-off-rotation signal (ported from
radon). **Status: descriptive cross-asset gamma-state indicator — explicitly NOT presented as
predictive.** Like VCG, it ships in the UI with that honesty label.

> No iterations subfolder: this research line is a single evidence-check doc plus a first-pass
> backtest. [`CLAUDE.md`](./CLAUDE.md) is the source of truth (full literature audit, code map,
> the radon flip-definition deviation) and is referenced by `cards/grg_scoring.py`,
> `scanners/grg.py`, and the UI — it stays in place. There is **no tradeable equity curve** (it's an
> indicator, not a strategy); the metrics below are forward-return event studies.

---

## 1. The thesis vs. what the evidence supports

| Claim | Grounding | Verdict |
|---|---|---|
| 1. Dealer gamma → realized vol (equity index) | Peer-reviewed (Barbon-Buraschi, Baltussen et al. JFE 2021, Soebhag 2023, Dim-Eraker-Vilkov) | **Established mechanic** |
| 2. Same mechanic in bonds (TLT) | Peer-reviewed for **MBS/swaption** convexity hedging, not TLT option gamma | **Mechanism real; TLT-GEX is an analogy, not a tested result** |
| 3. SPY-vs-TLT gamma divergence = risk-off rotation | Vendor/blog only; flight-to-safety is real but identified from returns/VIX, not gamma | **Practitioner folklore + novel untested combination** |
| 4. The gap is tradeable / forward-predictive | No peer-reviewed support; one quasi-academic source shows post-2020 decay | **Speculative — not presented as established** |

---

## 2. Metrics — forward-return backtest (YTD 2026, first pass)

Gate-confirmed TOP_WATCH / BOTTOM_WATCH events vs SPY's actual daily close (warm-store
`daily_ohlc`), 30-session forward window. Computed in `cards/grg_scoring._annotate_event_backtest`,
persisted on every snapshot, surfaced in the UI.

| Event | Date | SPY @ signal | Lead to adverse extreme | Further move | fwd +20d |
|---|---|--:|--:|--:|--:|
| TOP-WATCH | 2026-05-13 | 742.31 | 13 sessions | **+2.33%** (kept rising) | −0.61% |
| BOTTOM-WATCH | 2026-02-20 | 689.43 | 26 sessions | **−8.33%** (kept falling) | −5.93% |
| BOTTOM-WATCH | 2026-02-19 | 684.48 | 27 sessions | −7.67% | −3.61% |
| BOTTOM-WATCH | 2026-02-13 | 681.75 | 30 sessions | −7.30% | −1.87% |

Context: YTD low **2026-03-30 @ 631.97**, YTD high **2026-06-02 @ 759.57**. Aggregate: 3
bottom-watches led the low by a median **27 sessions** (median **−7.67%** further); 1 top-watch led
the high by **13 sessions** (**+2.33%** further).

---

## 3. Conclusion

**Lead, not coincident; not inverted.** The labels are correct by construction (TOP_WATCH on
complacency/highs, BOTTOM_WATCH on stress/lows), but the watch signals **fire early** — weeks before
the actual extreme, with price continuing in the pre-signal direction afterward. Plotted on the price
line they *look* inverted (a "bottom" dot followed by a further −8%); that visual inversion is a
symptom of the lead timing, not a sign error.

**Two caveats keep this strictly descriptive:** the sample is tiny (**n = 4 ≈ 2 episodes**), and the
historical events were scored with `spy_flip_gap_pct=None` (4 of 5 gates) — a weaker bar than the live
headline signal.

---

## 4. Can we improve it?

1. **The gating next step is a multi-year, per-regime catastrophic-degradation backtest** — the same
   VCG-style validation gate the regime indicators use. [KNOWN gap, HIGH] No predictive claim is
   defensible until GRG clears it across regimes; the YTD n=4 is far too thin. (Per-regime gates are a
   standing requirement here — see project memory `feedback_per_regime_catastrophic_gate`.)
2. **Resolve the radon flip-definition deviation.** [INFERRED, LOW] argon's GRG uses the canonical
   persisted gamma flip (one flip app-wide), where radon recomputes a last-negative→positive crossing.
   When argon's flip sits above spot the flip gate / `spot_vs_flip` can differ in sign — confirm this is
   the intended trade-off (it only affects 1 of 6 gates; the headline residual is flip-independent).
3. **Test the TLT-GEX leg directly** rather than leaning on the MBS/swaption analogy. [INFERRED, MED]
   Claim 2's evidence is for a structurally different (much larger) convexity-hedging flow; an explicit
   TLT-listed-option dealer-gamma → TLT realized-vol check would either ground or retire the bond leg.

---

**Code map:** scoring `src/uw_scan/cards/grg_scoring.py`; scanner `src/uw_scan/scanners/grg.py`;
storage `storage/grg_snapshot_repository.py` + migration `071`; API `GET /api/regime/grg`; UI
`web/components/regime/GrgSubTab.tsx`. Full literature audit + sources: [`CLAUDE.md`](./CLAUDE.md).
