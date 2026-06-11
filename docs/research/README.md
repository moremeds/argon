# Research Projects

This index pulls together the research work that is ready to browse from the
`docs/` tree.

VCG / regime research is intentionally not listed here while the current VCG
composite-proxy work is in progress. See `docs/research/regime/` and
`docs/superpowers/specs/2026-05-26-vcg-composite-research-design.md` only if
you are working that branch directly.

## Active Research Sets

| Project | Status | Start Here |
|---|---|---|
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
