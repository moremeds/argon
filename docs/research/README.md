# Research Projects

This index pulls together the research work that is ready to browse from the
`docs/` tree.

## Active Research Sets

| Project | Status | Start Here |
|---|---|---|
| Macro Short-Vol (VRP) | First drawdown-robust edge in the VRP line: SPX/SPY bull put spread sized by a VRP-z richness gate, Sharpe ≈ 1.65 (2006–2026). Matches buy-and-hold on return; the edge is the smoother ride. | [vrp/README.md](vrp/README.md) |
| Regime Indicators (CRI / VCG / Canary) | Three macro-regime *classifiers* (not strategies): CRI leads (AUC ~0.63), VCG is descriptive, the 5% Canary is validated v1 (AUC ~0.62). | [regime/README.md](regime/README.md) |
| Gamma Rotation Gap (GRG) | SPY-vs-TLT cross-asset dealer-gamma divergence — a descriptive cross-asset gamma-state indicator, not yet predictive (YTD n=4). | [grg-gamma-rotation-gap/README.md](grg-gamma-rotation-gap/README.md) |
| Gold SDF Framework | Research foundation for Gold Compass: structural flows, cyclical factors, valuation overlay, source catalog, and data-quality gaps. | [gold-sdf-framework/README.md](gold-sdf-framework/README.md) |
| Goyal-Saretto IPCA Options | Replication and codebase impact analysis for the option-return IPCA paper, centered on RV-IV as the dominant cross-sectional factor. | [goyal-saretto-ipca-options/README.md](goyal-saretto-ipca-options/README.md) |
| Six-Dimension Options Matrix | Cockpit research set for index market structure: vanna, charm, skew, term, implied move plus flow, and VRP. | [six-dimension-matrix/README.md](six-dimension-matrix/README.md) |

## Focused Research Notes

| Note | Why It Exists |
|---|---|
| [Spec % and Skew DTE](options-signals/2026-05-12-spec-pct-and-skew-dte-research.md) | Defines the watchlist card's flow-aggression metric and records why the UI avoids copying an undefined proprietary "Spec %" number. |
| [Skew DTE Verification](options-signals/2026-05-12-skew-dte-verification.md) | Confirms that the existing `volatility.skew_25d` is nearest-expiry skew, not 30-DTE skew. |
| [Vol-Neutral Mean Reversion](options-signals/2026-05-13-vol-neutral-mean-reversion-strategy-research.md) | Maps Volatility Tab v2 features to future defined-risk volatility and mean-reversion research. |
| [Setup Classifier Evidence](options-signals/2026-05-15-setup-classifier-evidence.md) | Documents why signed option flow drives setup direction while IV rank is retained as context instead of a hard directional gate. |
| [Radon Feature Probe](2026-07-03-radon-feature-probe.md) | Full-repo pass over sibling project radon; 5 ranked feature candidates for argon (SVI vol-surface fit, walk-forward backtest harness, alert rules engine, Polymarket divergence, order-book microstructure) with fit/lift notes. |
