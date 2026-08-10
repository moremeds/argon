# 08 — Implementation Gaps vs Current `uw_scan` Setup

> Cross-reference of each matrix dimension against the *actual* state of the codebase as of 2026-05-14. Identifies what is built, what is missing, and the concrete file/method changes required to reach a fully matrix-compatible system.

For background on layout, see [`src/uw_scan/CLAUDE.md`](../../../src/uw_scan/CLAUDE.md) (pipeline & layer conventions) and the "When adding a new endpoint" 6-step workflow it prescribes.

---

## 1. Status summary

| # | Dimension | Data layer | API layer | UI layer | Derived analytics |
|---|---|---|---|---|---|
| 1 | Vanna | ✅ DB (no read methods) | ❌ none | ❌ none | ❌ no conditional-reading classifier |
| 2 | Charm | ✅ DB (no read methods) | ❌ none | ❌ none | ❌ no pin classifier |
| 3 | Skew | ✅ full | ✅ `SkewBlock` + `VolMetrics.skew_25d` | ✅ watchlist block + SVG chart | ⚠️ no acceleration / regime detector |
| 4 | Term Structure | ✅ full | ✅ Volatility tab v2 | ✅ Volatility tab curve | ⚠️ no four-state classifier |
| 5 | Implied Move + Flow | ⚠️ Flow ✅ end-to-end; IM not derived | ⚠️ Flow ✅; IM ❌ | ⚠️ FlowTab ✅; IM not shown | ❌ no IM deriver, no event-distribution benchmark, no 4-footprint classifier |
| 6 | VRP | ✅ proxy only | ✅ Volatility tab v2 | ✅ Volatility tab | ⚠️ no strict (subsequent-RV) VRP, no regime classifier |
|   | **Skew (reference impl)** | ✅ full | ✅ | ✅ | The pattern to mirror for vanna/charm/term-classifier/VRP-strict |

Legend: ✅ = production-ready; ⚠️ = partial / proxy / missing classifier; ❌ = absent

---

## 2. Per-dimension gap detail

### 2.1 Vanna

| Layer | File / location | Status |
|---|---|---|
| UW endpoint | `/api/stock/{T}/greeks`, `/api/stock/{T}/greek-exposure/strike-expiry`, `/api/stock/{T}/spot-exposures/expiry-strike` | ✅ |
| Slug enum | `src/uw_scan/api/endpoints.py:14` (`GREEKS`, `GREEK_EXPOSURE`, `SPOT_EXPOSURES`) | ✅ |
| Fetcher | `src/uw_scan/sources/uw.py:170, 188, 206` | ✅ |
| Pipeline call | `src/uw_scan/pipeline.py:121, 144, 147` | ✅ (note: `fetch_spot_exposures` at 144 discards typed rows with `_ = …`) |
| Persistence | `uw_scan.greeks_by_expiry_strike.call_vanna/put_vanna` (per-contract), `uw_scan.exposures_by_expiry_strike.call_vanna/put_vanna` (aggregated) | ✅ |
| Repository read | None — `fetch_vanna_*_for_ticker` does not exist | ❌ |
| Report assembler | No assembler reads vanna | ❌ |
| API router | No router exposes vanna; `net_dex` hardcoded `None` in `src/uw_scan/reports/stock_history.py::build_stock_history_response` — the single builder behind both `/api/stock/{T}/history` and the Trade Insights payload (DEX is also unsurfaced) | ❌ |
| UI | No component | ❌ |
| Conditional reading classifier | None — the 4 conditional readings from [`01-vanna.md`](01-vanna.md) §2 require joining vanna with flow color + dealer net-gamma + IV direction | ❌ |
| AI blacklist | `src/uw_scan/reports/trade_insights_ai.py:965` rejects `"vanna"` in source paths | (block) |
| Intent-split (ask/bid/vol/oi) | Discarded at `pipeline.py:144`; raw lives in `uw_scan.raw_payloads` (JSONB) | ⚠️ recoverable but not typed |

**Build-out (small → large effort)** — Cockpit codepath, **not** stock-detail:
1. Add `Repository.fetch_vanna_curve(ticker, expiry, date)` and `Repository.fetch_vanna_aggregate(ticker, expiry, date)`
2. Compute derived metrics `dealer_net_vanna_proxy`, `flow_color_lookback_3d`, `iv_30d_delta_5d` — persist into a new `vanna_signals` table
3. Build the 4-condition classifier as a pure function in `src/uw_scan/cards/vanna_conditional.py`
4. Wire into `reports/cockpit_matrix.py` assembler (new — indexes only); expose via `/cockpit/{T}/dealer` payload
5. Regen `web/lib/types.ts`; build `DealerTab.tsx` under `web/app/cockpit/[ticker]/`
6. (Optional) Persist intent-split into a typed `spot_exposures_by_intent` table to enable real-time flow-color reading

The stock-detail AI blacklist at `trade_insights_ai.py:965` (`"vanna"`/`"charm"`) **stays** — see §4 and the Cockpit product decision. Vanna surfaces only through the Cockpit codepath; nothing in single-stock changes.

### 2.2 Charm

Mirror structure of vanna. Same data path; same gaps.

| Layer | Status | Notes |
|---|---|---|
| UW endpoint | ✅ | same three endpoints |
| Fetcher / pipeline / persistence | ✅ | columns `call_charm/put_charm` exist in `greeks_by_expiry_strike` (`migrations/001:228-231`) and `exposures_by_expiry_strike` (`001:258-261`) |
| Repository read | ❌ | |
| Pin classifier | ❌ | needs `pin_candidate_strike`, `pin_distance_sigma`, `pin_regime_flag` — see [`02-charm.md`](02-charm.md) §7 |
| API / UI | ❌ | |
| AI blacklist | `"charm"` also blocked at `trade_insights_ai.py:965` | (block) |
| Joint Vanna+Charm consistency | Required for Scenario B grind-up confirmation | ❌ |

**Build-out**: same 7-step sequence as vanna. Combined Vanna+Charm work makes sense — same data tables, same repository methods, same conditional-classifier scaffolding.

### 2.3 Skew — **the reference implementation**

| Layer | Status | Location |
|---|---|---|
| Endpoint, fetcher, persistence | ✅ | `fetch_skew` (uw.py:151), `risk_reversal_skew_history` table |
| Rollup | ✅ | `watchlist_cards.skew_25d_30dte` (`migrations/003:49`) |
| Repository read | ✅ | `repository.py:1438` |
| Assembler | ✅ | `reports/single_stock.py:176`, `reports/volatility_series.py:115` |
| API | ✅ | `SkewBlock.rr25d_30dte`, `VolMetrics.skew_25d` |
| UI | ✅ | `web/components/watchlist/SkewBlock.tsx`, `web/components/stock/panels/VolMetricsCard.tsx`, `.skew-chart` SVG |

**Skew is the architectural pattern other dimensions should follow.** The end-to-end flow (DB → API → UI + SVG chart) is the template for Vanna, Charm, and the missing derivers.

**Gaps**:
| Gap | Effort | Doc |
|---|---|---|
| Acceleration detector (`skew_25d_5d_change`, z-score) | small | [`03-skew.md`](03-skew.md) §7 |
| Regime classifier (smirk / accelerated / crash-smile) | small | |
| Multi-expiry skew (`skew_term_structure`) | medium — current fetch picks one expiry | |
| Single-name baseline adjustment | medium — currently universal threshold | |
| Flow-corroborated reading (`skew_flow_concordance`) | medium — joins with flow data | |

### 2.4 Term Structure

| Layer | Status | Location |
|---|---|---|
| Endpoint, fetcher, persistence | ✅ | `fetch_term_structure` (uw.py:137) |
| Assembler | ✅ | `_build_term_structure` — `reports/volatility_series.py:268` |
| API + UI | ✅ | Volatility tab v2 renders the curve |

**Gaps**:
| Gap | Effort | Doc |
|---|---|---|
| Four-state classifier (`ts_state`) | medium — the matrix's primary classifier; currently the user must visually classify | [`04-term-structure.md`](04-term-structure.md) §6 |
| `front_back_spread` derived metric | small | |
| `single_point_bump_pct` event detector | small–medium | |
| `ts_johnson_slope_pc1` (per Johnson 2017) | small | |
| `event_back_collapse_eta` predictor | medium | |
| Per-ticker persistent classification + reason label | small (after classifier exists) — needed for backtest replay | |

### 2.5 Implied Move + Flow

#### Flow — full surface

| Layer | Status | Location |
|---|---|---|
| Endpoint, fetcher | ✅ | `fetch_flow_alerts` (uw.py:102) |
| Assembler | ✅ | `reports/single_stock.py:48-101` |
| API + UI | ✅ | `FlowTab.tsx`, `FlowSnapshotGrid`, `TopAlertsTable`, `OiMoversTable` (with aggressor labeling per memory `project_aggressor_classification_semantics.md`) |
| Dark pool | ✅ | Integrated into flow panels |

#### Implied Move — **mostly missing**

| Layer | Status | Notes |
|---|---|---|
| IV inputs | ✅ | `interpolated_iv` / `volatility_stats` |
| IM deriver | ❌ | `implied_move_expected_abs = 0.7979 × ATM_straddle_mid / spot` (= straddle/S ≈ E[\|R\|]; **not** the 1σ band — see [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) §1) not computed. 1σ band, if needed, is `1.2533 × straddle/spot`. |
| Persistence | ❌ | no `implied_move_history` table |
| Historical-event distribution | ❌ | no `event_realized_move_distribution` table joining earnings/FOMC/CPI calendar with realized post-event returns |
| Event percentile metric | ❌ | `implied_move_event_percentile` not computed |
| UI display | ❌ | not surfaced |

#### Flow footprint classifier — **not built**

| Layer | Status | Notes |
|---|---|---|
| 4-footprint classifier | ❌ | the {Directional Whale / Hedge Flow / Dealer Hedge / Gamma Scalper} taxonomy is not labeled on `FlowAlert` rows |
| Aggressor confidence flag | ❌ | per-ticker liquidity-based confidence per Savickas-Wilson is not computed |
| Flow-color 3-day rollup | ❌ | `directional_imbalance_3d` (input to Vanna conditional reading) is not derived |

**Build-out priority**:
1. IM deriver — trivial; persist into a new `implied_move_history` table (ticker × expiry × date)
2. Historical-event distribution table — requires an earnings/macro calendar (FMP earnings calendar or massive's calendar endpoint)
3. Event-percentile metric — joins (1) and (2)
4. 4-footprint flow classifier — design as a rule-based classifier first; ML refinement is Phase 2

### 2.6 VRP

| Layer | Status | Location |
|---|---|---|
| Proxy VRP | ✅ | `build_vrp` at `reports/single_stock.py:181`; `vrp = vol.iv - vol.rv` at line 184 (IV − RV with ±0.05 thresholds) |
| Proxy VRP time series | ✅ | `reports/volatility_series.py:116` |
| API + UI | ✅ | Volatility tab v2 |
| **Strict VRP** (IV_t vs subsequent t→t+30 RV) | ❌ | requires 30-day-lagged comparison; not currently in pipeline |
| Long-run regime classifier (252d / 504d / 1260d z-score) | ❌ | |
| Sign-flip detector | ❌ | |
| Bekaert-Hoerova decomposition (conditional variance + premium) | ❌ | optional / Phase 2 |

**Build-out** (for strict VRP):

Option A — *Compute historically*: at each nightly rollup, compute strict VRP for `t < today − 30d` using existing IV and RV history. Easiest; immediately backtestable. Cannot produce *real-time* strict VRP.

Option B — *Settlement table*: maintain a `vrp_30d_settlements` table; insert `IV_30d(t)` at `t`, update with `RV_subsequent` at `t + 30d`. Cleaner; matches the strict Carr-Wu definition.

**Recommendation**: Option A for backtest, Option B for production. Both can coexist.

---

## 3. Cross-dimension dependencies

The decision tree's Step 1 (consistency check) requires all 6 dimensions to be queryable from a **single read-path**. Currently:

| Source | Reads needed | Built? |
|---|---|---|
| `dealer_net_vanna_proxy` | vanna repository methods | ❌ |
| `dealer_net_charm_proxy` | charm repository methods | ❌ |
| `skew_25d` + acceleration | skew repository (built) + derived (missing) | ⚠️ |
| `ts_state` | term-structure classifier | ❌ |
| `implied_move_event_percentile` | IM deriver + event distribution | ❌ |
| `flow_footprint_label` | flow classifier | ❌ |
| `vrp_strict_zscore` | strict VRP estimator | ❌ |

**Implication**: even after individual dimension build-outs, a **unified consistency-check endpoint** (`GET /stock/{T}/matrix-state`) needs to be designed to atomically return the 6 readings + the meta-classification (consistent / 3-3 conflict / 2-4 conflict).

### Proposed assembler: `reports/matrix_state.py`

```python
def build_matrix_state(repo: Repository, ticker: str, asof: date) -> MatrixState:
    """
    Assembles the 6-dimension matrix reading for a single ticker at a single date.

    Returns:
        MatrixState with: vanna_signal, charm_signal, skew_signal, term_state,
        implied_move_signal, vrp_signal, plus aggregate consistency_label
        ∈ {consistent_vol_up, consistent_vol_down, conflict_3_3, conflict_2_4, mixed}.
    """
    ...
```

This becomes the **primary backtest input** in [`09-backtest-plan.md`](09-backtest-plan.md).

---

## 4. Recommended build sequence — Cockpit product direction

**Product scope (2026-05-14 decision)**: matrix ships as a dedicated `/cockpit/[ticker]` section, indexes only (SPX / SPY / QQQ / IWM). Stock-detail AI report keeps the `"vanna"/"charm"` blacklist; a separate `reports/cockpit_ai.py` codepath consumes the matrix.

Ranked by (a) leverage on the Cockpit's tradeable consistency check and (b) effort:

| # | Build | Effort | Why first |
|---|---|---|---|
| 1 | Vanna + Charm repository reads + derived metrics (`dealer_net_vanna/charm_proxy`) | medium (combined) | Foundation for Dealer tab; same data substrate |
| 2 | Implied Move deriver (`0.7979 × straddle/spot`) | trivial | Math is closed-form; persists into a small new table |
| 3 | Term-structure four-state classifier (`ts_state`) | small–medium | Directly feeds decision tree Step 2 and Surface tab |
| 4 | Skew acceleration + regime classifier (`skew_25d_5d_change`, `skew_25d_zscore_180d`) | small | Builds on existing skew data; small leap |
| 5 | Strict VRP (historical compute) | small | Backtest-grade; computable for any `t < today − 30d` using existing data |
| 6 | Historical-event distribution table + IM event-percentile | medium | Required for Scenario A short-vol candidate detection |
| 7 | Index-only ticker filter / `is_cockpit_universe(ticker)` helper | trivial | Universe gate: `{SPX, SPY, QQQ, IWM}` |
| 8 | `reports/cockpit_matrix.py` — unified 6-dim assembler returning `MatrixState` | medium | Single read path serving all 5 tabs |
| 9 | API: `/cockpit/{ticker}/state` + `/cockpit/{ticker}/{tab}` routers (5 endpoints) | medium | Tab-aligned API surface |
| 10 | UI: `web/app/cockpit/[ticker]/` route + 5 tab components (State / Dealer / Surface / Flow+IM / VRP) | medium-large | Cockpit's user-facing surface |
| 11 | Vanna conditional-reading classifier (4-rule) | medium | Powers Dealer tab's conditional readings |
| 12 | Charm pin classifier + Vanna+Charm joint consistency | medium | Powers Scenario B detection in Dealer tab |
| 13 | 4-footprint flow classifier | medium | Powers Flow+IM tab |
| 14 | `reports/cockpit_ai.py` — index-only AI report consuming `MatrixState` | medium | Separate codepath; new prompt; **no** vanna/charm blacklist |
| 15 | (Phase 3) Bekaert-Hoerova VRP decomposition | medium-large | Optional refinement |

**Phase-1 (items 1–7)**: data + derivations. Computable from existing tables; no UI yet. Backtest-runnable.
**Phase-2 (items 8–10)**: API + UI surface. The Cockpit becomes usable.
**Phase-3 (items 11–14)**: classifiers + AI. The Cockpit becomes opinionated.
**Phase-4 (item 15)**: research extensions.

### What this revises from earlier doc versions

Previous build sequences (pre-product-decision) recommended *lifting* the `trade_insights_ai.py:965` blacklist for vanna/charm so the stock-detail AI could cite them. **That recommendation is now wrong.** The blacklist stays — it correctly enforces single-name AI scope. The matrix gets a **separate** AI codepath (`reports/cockpit_ai.py`) for indexes only.

---

## 5. Required new tables (consolidated)

| Table | Purpose | Source |
|---|---|---|
| `vanna_signals` | derived `dealer_net_vanna_proxy`, `flow_color_lookback_3d`, conditional-reading label | [`01-vanna.md`](01-vanna.md) §7 |
| `charm_signals` | derived `pin_candidate_strike`, `pin_distance_sigma`, `pin_regime_flag` | [`02-charm.md`](02-charm.md) §7 |
| `skew_signals` | derived `skew_25d_5d_change`, `skew_25d_zscore_180d`, `skew_term_structure`, `crash_smile_flag` | [`03-skew.md`](03-skew.md) §7 |
| `term_structure_state` | derived `ts_state`, `front_back_spread`, `single_point_bump_pct`, `ts_johnson_slope_pc1` | [`04-term-structure.md`](04-term-structure.md) §7 |
| `implied_move_history` | `implied_move_expected_abs` per ticker per expiry per date (column is E[\|R\|], NOT the 1σ band) | [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) §9 |
| `event_realized_move_distribution` | historical realized moves grouped by (ticker, event_type) | [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) §8 |
| `flow_footprint_labels` | per-alert classification + confidence | [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) §9 |
| `vrp_30d_settlements` | settled strict VRP entries | [`06-vrp.md`](06-vrp.md) §7 |
| `matrix_state_snapshots` | unified 6-dim reading per ticker per date for backtest replay | [`09-backtest-plan.md`](09-backtest-plan.md) |

All tables follow the existing `uw_scan` conventions (idempotent migrations, `Decimal` round-tripping, `Repository` methods one-per-query). See `src/uw_scan/storage/CLAUDE.md`.

---

## 6. Cross-references

- Per-dimension specifics — `01-vanna.md` through `06-vrp.md`
- Limitations that gate each dimension's safe use — [`07-limitations.md`](07-limitations.md)
- Backtest plan — [`09-backtest-plan.md`](09-backtest-plan.md) (consumes the build sequence above)
- Memory note (older, DEX/GEX-based 6-dim framework — to be replaced) — `~/.claude/projects/-Users-chenxi-projects-unusual-whales/memory/project_six_dimension_option_analysis.md`
