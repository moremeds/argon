# Trade Insights Tab — volatility research presentation design

**Date:** 2026-05-13
**Status:** Draft
**Context:** Presentation design for research-grade trade ideas using the Volatility Tab v2 features plus cross-source option-chain analysis. This is based on the TSLA analysis example that reconciled TradingView-style IV, yfinance-style IV, option prices, volume/OI, term structure, and candidate structures.

## 1. Goal

Add a new stock-detail tab that presents **research-grade trade ideas** without pretending they are executable orders.

Proposed route:

```text
/stock/{ticker}/trade-insights
```

Proposed tab order:

```text
Market Structure | Volatility | Flow | Trade Insights | Trade Plan
```

(The standalone `Tables` tab was merged into `Flow` in 2026-05; raw rows now live there.)

The tab answers:

- Is volatility cheap or rich?
- Are sources agreeing or disagreeing?
- What is the dominant flow/positioning read?
- Which option structures express the setup?
- What checks are still required before sizing?
- Why is a structure preferred or rejected?

It should not submit orders, auto-size positions, or claim backtested edge.

## 2. Why this should be separate from Trade Plan

The existing `TradePlanTab` is order-plan shaped: setup, confirmations, warnings, structure, legs, max loss, max profit. The TSLA-style analysis is **research shaped**:

- source reconciliation;
- IV methodology disagreement;
- flow/OI interpretation;
- term-structure interpretation;
- several candidate structures;
- qualitative synthesis;
- required checks before sizing.

Putting all of that inside Trade Plan would make the order plan noisy. Trade Insights should sit upstream: it narrows candidates and records evidence. Trade Plan can later consume one selected idea and convert it into a concrete, risk-sized plan.

## 3. Page hierarchy

```text
┌─ IDEA HEADER ───────────────────────────────────────────────────────────────┐
│ TSLA  |  Research-grade trade ideas  |  As of 2026-05-13 15:59 ET          │
│ Bias: Neutral / Short Vol  |  Confidence: Medium  |  Data Quality: Mixed   │
│ Badges: IV-source mismatch, event check required, liquid chain             │
└────────────────────────────────────────────────────────────────────────────┘

┌─ SOURCE RECONCILIATION ───────────────┐ ┌─ SIGNAL STACK ───────────────────┐
│ Prices match, IV differs              │ │ IV-RV z, divergence, regime      │
│ TV IV 44%, YF IV 52%                  │ │ Flow, term, structure agreement  │
│ Use vendor IV for relative shape only │ │ Dominant read + conflicts        │
└───────────────────────────────────────┘ └──────────────────────────────────┘

┌─ CHAIN / FLOW READ ────────────────────────────────────────────────────────┐
│ Strike rows: call vol, call OI, put vol, put OI, vol/OI, read              │
│ Headline: Call volume 1.9x put volume; major strikes show volume > OI      │
└────────────────────────────────────────────────────────────────────────────┘

┌─ TERM STRUCTURE / IMPLIED MOVE ────────────────────────────────────────────┐
│ Expiry table: DTE, ATM straddle, implied move, daily implied move          │
│ Headline: Front-week vol elevated vs back-week                             │
└────────────────────────────────────────────────────────────────────────────┘

┌─ CANDIDATE STRUCTURES ─────────────────────────────────────────────────────┐
│ [A] Call credit spread  [B] Put credit spread  [C] Long straddle           │
│ [D] Iron condor         [E] Calendar spread                                │
│ Each card: thesis, legs, credit/debit, max loss/profit, breakeven, risks   │
└────────────────────────────────────────────────────────────────────────────┘

┌─ SYNTHESIS / NEXT CHECKS ──────────────────────────────────────────────────┐
│ What the data says, preferred expression, rejected ideas, required checks  │
└────────────────────────────────────────────────────────────────────────────┘
```

## 4. Core panels

### 4.1 Idea Header

Purpose: make the tab's status obvious in one scan.

Fields:

| Field | Example | Notes |
|---|---|---|
| `ticker` | `TSLA` | From route. |
| `as_of` | `2026-05-13 15:59 ET` | Must reflect source timestamp. |
| `dominant_bias` | `Neutral / Short Vol` | Not simply bullish/bearish. |
| `primary_setup` | `Front-vol mean reversion` | Human-readable setup. |
| `confidence_label` | `Medium` | Derived from source agreement, freshness, liquidity, event status. |
| `data_quality_label` | `Mixed` | Separate from confidence. |
| `idea_count` | `5 candidates` | Count of candidate structures. |
| `preferred_idea_id` | `D` | Nullable. |

Badges:

- `IV source mismatch`
- `Event check required`
- `Defined-risk only`
- `Liquid near-ATM chain`
- `Historical backtest unavailable`

### 4.2 Source Reconciliation

The TSLA example shows why this panel matters: option prices matched, but IV differed by 6-9 vol points. That is a methodology issue, not necessarily a market-data issue.

Display:

| Source pair | Price agreement | IV agreement | Decision |
|---|---:|---:|---|
| TV vs YF | Matches to penny | YF +6-9 vol pts | Use price, distrust TV absolute IV |

Panel text should be concise:

```text
Option prices agree, absolute IV does not. Treat vendor IV as relative shape only.
Use chain-derived IV for cheap/rich decisions.
```

Recommended fields:

```jsonc
{
  "source_reconciliation": {
    "status": "mixed",
    "headline": "Prices match, IV differs by 6-9 vol points",
    "primary_iv_source": "yfinance",
    "relative_shape_source": "tradingview",
    "rows": [
      {
        "strike": 430,
        "call_mid": 9.68,
        "source_a_call_iv": 0.456,
        "source_b_call_iv": 0.523,
        "iv_diff": 0.067
      }
    ],
    "decision": "Use source B IV for absolute cheap/rich decisions; use source A only for relative shape."
  }
}
```

### 4.3 Signal Stack

Purpose: summarize the evidence without jumping straight to structures.

Rows:

| Lens | Signals | Read |
|---|---|---|
| Vol level | IV vs RV, `vrp_z_20` as IV-RV z-score, IV percentile | Cheap / fair / rich |
| Vol stability | `iv_of_iv_20`, term shape | Stable / unstable |
| Realized regime | `rvol_pctile`, realized move | Quiet / active |
| Correlation | `spy_corr_21`, regime quadrant | Systemic / idiosyncratic |
| Flow | call/put volume, volume/OI, ask-side premium | Bullish / bearish / mixed |
| Structure | GEX walls, max pain, pin zone | Range / trend / gap risk |

Example:

```text
Direction: bullish flow
Vol level: fair to slightly cheap by chain-derived IV
Term: front-week elevated vs back-week
Best expression: calendar or tight defined-risk range trade
Conflict: bullish flow fights short-call mean-reversion trade
```

### 4.4 Chain / Flow Read

The tab should make volume/OI visible because the TSLA analysis relied on it.

Table columns:

| Strike | Call Vol | Call OI | Put Vol | Put OI | C/P Vol | Vol/OI note | Read |
|---:|---:|---:|---:|---:|---:|---|---|
| 420 | 33,879 | 22,602 | 17,982 | 6,227 | 1.88x | Call vol > OI | New call exposure likely |
| 430 | 35,832 | 14,925 | 24,957 | 4,465 | 1.44x | Both sides active | ATM battle / pin candidate |
| 440 | 29,045 | 9,103 | 4,987 | 2,281 | 5.82x | Call vol > OI | OTM call demand |

Derived fields:

- total call volume;
- total put volume;
- call/put volume ratio;
- volume greater than OI flags;
- `requires_t1_oi_confirmation` when volume materially exceeds OI;
- concentration by strike;
- "new positioning likely" flag when volume materially exceeds OI.

Caveat text:

```text
Volume > OI suggests new positioning but does not prove opening trades until next-day OI confirms. Volume can exceed OI because the same contract can trade multiple times intraday.
```

### 4.5 Term Structure / Implied Move

This panel presents the 4-DTE vs 11-DTE logic from the example.

Table columns:

| Expiry | DTE | ATM straddle | Implied move | Daily implied | Read |
|---|---:|---:|---:|---:|---|
| 2026-05-15 | 4 | `$20.65` | `4.8%` | `1.20%/day` | Front elevated |
| 2026-05-22 | 11 | `$28.80` | `6.7%` | `0.61%/day` | Back calmer |
| Marginal | +7 | `+$8.15` | `+1.9%` | `0.27%/day` | Back-week cheap vs front |

Headline examples:

- `Front-week backwardation: short-dated vol is elevated.`
- `Calendar candidate: sell front, buy back, if event risk is clean.`
- `No term edge: curve is smooth and fairly priced.`

### 4.6 Candidate Structure Cards

Cards should be compact and comparable. The tab should avoid large prose blocks when a table or card can carry the same information.

Common fields:

| Field | Meaning |
|---|---|
| `idea_id` | `A`, `B`, `C`, etc. |
| `structure` | `Iron condor`, `Calendar`, `Call credit spread`. |
| `thesis` | One-line reason. |
| `expression_type` | `Short vol`, `Long vol`, `Direction + theta`, `Term structure`. |
| `legs` | Side, expiry, strike, call/put, estimated mid. |
| `net_credit_debit` | Positive for credit, negative for debit. |
| `max_profit` | If defined. |
| `max_loss` | Required for all candidate structures. |
| `breakevens` | Where applicable. |
| `profit_zone` | For spreads/condors. |
| `greeks_summary` | Delta/gamma/vega/theta, approximate. |
| `edge_source` | `Theta`, `IV-RV spread`, `term structure`, `flow confirmation`. |
| `risk_flags` | Event, spread width, assignment, source mismatch. |
| `rank` | 1-N. |
| `status` | `candidate`, `rejected`, `preferred`, `needs_check`. |

Example card:

```text
D. Iron condor 417.5/422.5 - 432.5/437.5
Type: range / short vol / defined risk
Credit: $3.72
Max loss: $1.28
Profit zone: $422.50 - $432.50
Why it exists: spot is centered, front-week premium elevated, defined risk.
Conflict: bullish flow could break the call side.
Required checks: earnings, spread width, OI, actual NBBO, max-loss budget.
Status: candidate, not executable.
```

### 4.7 Synthesis / Decision Panel

This is the narrative close. It should be shorter than the pasted analysis, but still explain the conclusion.

Suggested fields:

```jsonc
{
  "synthesis": {
    "dominant_story": "Bullish flow but front-week volatility is elevated after a large move.",
    "preferred_expression": "Calendar spread or tight iron condor depending on event/liquidity checks.",
    "best_risk_reward": "Iron condor",
    "most_thesis_aligned": "Calendar spread",
    "avoid": [
      "Long front-week straddle unless realized movement is expected to exceed implied",
      "Naked short options"
    ],
    "required_before_sizing": [
      "Confirm event calendar through both expiries",
      "Confirm bid/ask and OI from live chain",
      "Confirm realized vol over last 5 sessions",
      "Cross-check absolute IV with chain-derived calculation"
    ]
  }
}
```

## 5. Data model proposal

Add a new response shape rather than overloading `SingleStockReport.trade_plan`.

Endpoint:

```text
GET /api/stock/{ticker}/trade-insights
```

Response outline:

```jsonc
{
  "ticker": "TSLA",
  "as_of": "2026-05-13T15:59:00-04:00",
  "mode": "research",
  "header": {
    "dominant_bias": "NEUTRAL_SHORT_VOL",
    "primary_setup": "FRONT_VOL_MEAN_REVERSION",
    "confidence_label": "MEDIUM",
    "data_quality_label": "MIXED",
    "idea_count": 5,
    "preferred_idea_id": null,
    "badges": ["IV_SOURCE_MISMATCH", "EVENT_CHECK_REQUIRED", "DEFINED_RISK_ONLY"]
  },
  "source_reconciliation": {
    "status": "MIXED",
    "headline": "Prices match, IV differs by 6-9 vol points",
    "decision": "Use chain-derived IV for absolute cheap/rich decisions."
  },
  "event_context": {
    "status": "PARTIAL",
    "next_earnings_date": "2026-07-22",
    "next_dividend_date": null,
    "notes": ["Earnings date available from UW flow/screener data", "Ex-dividend date unavailable for this run"]
  },
  "signal_stack": [
    {"lens": "VOL_LEVEL", "read": "FAIR_TO_CHEAP", "evidence": ["ATM IV ~52%", "TV IV unreliable"]},
    {"lens": "FLOW", "read": "BULLISH", "evidence": ["Call volume 1.9x put volume"]},
    {"lens": "TERM", "read": "FRONT_ELEVATED", "evidence": ["4 DTE daily implied 1.20%", "11 DTE daily implied 0.61%"]}
  ],
  "flow_table": [],
  "term_structure_table": [],
  "candidate_structures": [],
  "synthesis": {
    "dominant_story": "...",
    "preferred_idea_id": "E",
    "best_risk_reward_idea_id": "D",
    "required_before_sizing": []
  }
}
```

## 6. Source requirements

Minimum sources for v1:

| Source | Use |
|---|---|
| Current option contracts snapshot | Bid/ask/mid, volume, OI, option symbol. Expiry, strike, and call/put are parsed from the OCC/OSI-style symbol unless normalized columns are added. |
| Current Greeks / smile | Delta, IV, skew shape, rough Greeks. |
| Volatility Tab v2 series | IV-RV spread / VRP proxy, regime, divergence, IV-of-IV. |
| Flow data | Ask/bid-side premium, call/put premium, expiry/strike concentration. |
| Event data | Earnings at minimum. Ex-dividend is strongly recommended before short-call/calendar logic. |

External source reconciliation can be modeled generically. The UI does not need to know whether a source is TradingView, yfinance, Funda, or UW. It needs:

- source name;
- timestamp;
- price fields;
- IV fields;
- agreement/difference metrics;
- decision on source trust.

Event context should use existing persisted UW fields before adding a new provider:

- `flow_events.next_earnings_date` is available on single-stock runs when flow alerts carry it;
- `scan_results.next_earnings_date` is available on full-scan rows;
- `BulkScreenerRow.next_dividend_date` exists in the normalized model but is not currently promoted into `SingleStockReport` or persisted as a single-stock event context.

Therefore V1 can treat earnings as `KNOWN` when a next earnings date is found, but should still mark ex-dividend as `UNKNOWN` unless it is explicitly persisted for the run.

### 6.1 Contract normalization

The current `option_contract_snapshots` table stores `option_symbol` plus tradability fields. It does not currently store normalized `expiry`, `strike`, or `right` columns. V1 can parse those fields from the OCC/OSI-style option symbol:

```text
<root><YYMMDD><C/P><strike * 1000 padded to 8 digits>
```

Example:

```text
TSLA260515C00430000 -> TSLA, 2026-05-15, call, 430.00
```

For implementation robustness, prefer adding normalized columns or a materialized view:

```sql
option_expiry DATE
option_right  TEXT CHECK (option_right IN ('C','P'))
strike        NUMERIC
```

The UI should not depend on string parsing in React. Backend responses should return normalized contract fields.

## 7. Ranking logic

Candidate ranking should be rule-based first, not ML.

All weights and thresholds in v1 are hypotheses. They should be configurable and later validated through walk-forward tests before any downstream Trade Plan automation depends on them.

Score components:

| Component | Direction |
|---|---|
| Signal fit | Does the structure express the dominant setup? |
| Defined risk | Defined-risk structures rank above undefined risk. |
| Liquidity | Tight spreads and high OI/volume rank higher. |
| Event cleanliness | No known event inside holding window ranks higher. |
| Source agreement | Price/IV/source agreement raises confidence. |
| Risk/reward | Favorable max loss vs max profit improves rank, but not alone. |
| Conflict penalty | Directional flow against the structure lowers rank. |

Example:

- Calendar ranks high if term-structure dislocation is the cleanest signal.
- Iron condor ranks high if spot is centered, realized vol is quiet, and flow is not strongly directional.
- Long straddle ranks low if chain-derived IV is fair/rich and realized-vol expectation is not strong.

### 7.1 Persistence for validation

V1 must persist the deterministic Trade Insights output. The point is not only to render cards; it is to build a research log that can later answer whether the rules, ranks, and gates had predictive value.

Persist at two levels:

1. **Snapshot payload:** one idempotent row per `(run_id, ticker, assembler_version, input_hash)` containing the full deterministic response JSON, data-quality labels, source-reconciliation status, and preferred/null status.
2. **Candidate rows:** one row per generated candidate with structure, rank, status, max loss, max profit, debit/credit, risk flags, edge source, and legs JSON.

This enables later analysis such as:

- Which candidate structures were most often generated?
- Did `needs_check` ideas later become valid after event/source/liquidity data improved?
- Did rank 1 outperform lower-ranked candidates under a later payoff model?
- Which risk flags correlated with bad outcomes?
- Which thresholds should be changed before any idea becomes a downstream Trade Plan input?

The persistence layer should be idempotent. Page refreshes must not create duplicate research rows for the same input snapshot.

## 8. Optional Codex ad-hoc analysis

The tab can leave room for LLM support without making the LLM part of the core signal engine.

Recommended UI control:

```text
[Run AI Analysis]
```

Button behavior:

```text
POST /api/stock/{ticker}/trade-insights/ai-analysis
  -> enqueue analysis job
  -> worker builds deterministic Trade Insights JSON from DB
  -> worker runs codex exec in read-only mode with that JSON
  -> worker stores markdown summary + structured metadata
  -> UI polls /api/jobs/{job_id} or a trade-insight-analysis job endpoint
  -> UI renders the returned commentary below the deterministic panels
```

This should be operator-triggered only. It should not run automatically on every scan, page load, or watchlist refresh.

### 8.1 Division of responsibility

| Layer | Owner | Notes |
|---|---|---|
| Numeric signals | Deterministic backend | IV-RV spread / VRP proxy, divergence, term shape, flow ratios, liquidity gates. |
| Structure generation | Deterministic backend | Contract selection, debit/credit, max loss, max profit, risk flags. |
| Hard blocking checks | Deterministic backend | Stale chain, missing NBBO, undefined max loss, event missing, unsupported naked short. |
| Narrative synthesis | Optional Codex job | Explain evidence, conflicts, preferred expression, and checks still needed. |
| Final UI rendering | Frontend | Render source numbers/cards from JSON; render AI text as commentary only. |

Codex must not override deterministic checks. If the backend marks a candidate `rejected` or `needs_check`, the AI summary may explain why, but cannot promote it to `preferred`.

### 8.2 Backend command shape

Local development can use the non-interactive Codex CLI:

```bash
codex exec \
  --cd /Users/chenxi/projects/unusual-whales \
  --sandbox read-only \
  --ask-for-approval never \
  "Analyze this structured trade-insight JSON. Do not invent missing data..."
```

Implementation detail: avoid passing large raw JSON directly in the shell command. Prefer one of:

- write sanitized structured input to a temporary read-only artifact and pass the path;
- store the payload in Postgres and pass an `analysis_job_id`;
- pass compact JSON through stdin if the runner supports it.

The prompt should tell Codex to:

- analyze only the supplied structured payload;
- preserve the backend's candidate statuses and risk flags;
- state when data is missing;
- avoid executable recommendations;
- produce concise Markdown with sections: `Dominant Read`, `Best Expressions`, `Conflicts`, `Required Checks`, `Rejected Ideas`.

### 8.3 Storage proposal

Add a separate table rather than mixing AI output into trade-insight rows:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_ai_analyses (
    analysis_id    UUID PRIMARY KEY,
    ticker         TEXT NOT NULL,
    run_id         BIGINT,
    input_hash     TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
    markdown       TEXT,
    error_message  TEXT,
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);
```

`input_hash` makes repeat runs auditable: if the deterministic payload has not changed, the UI can show the existing analysis or offer a "rerun anyway" control.

### 8.4 Guardrails for Codex jobs

- Run only from the worker, not inside a synchronous API request.
- Use `codex exec`, not the interactive TUI.
- Use `--sandbox read-only`.
- Use `--ask-for-approval never`.
- Set a hard timeout, e.g. 60-120 seconds.
- Run under a constrained service account or process environment.
- Use an allowlisted command wrapper rather than arbitrary shell strings.
- Limit concurrency and rate of AI jobs per ticker/user.
- Enforce max input and output sizes.
- Prefer a temporary working directory with no workspace write permissions for generated artifacts.
- Do not pass secrets, environment variables, API keys, cookies, or raw `.env` contents.
- Do not allow arbitrary user-written prompts in v1; use a fixed prompt template plus structured payload.
- Store input hash, prompt version, model, status, output, and error.
- Treat Codex output as commentary, not source of truth.
- If Codex fails, keep the deterministic Trade Insights tab usable.

This makes LLM support useful but optional: the product still works as a rule-based research tab, and Codex can add an analyst-style explanation when explicitly requested.

## 9. UI guardrails

- Label the tab `Trade Insights`, not `Recommendations`.
- Every structure card must show `max_loss` or be rejected.
- Undefined-risk short options should be hidden or marked unsupported.
- Use `candidate`, `preferred`, `rejected`, and `needs_check` statuses.
- Show source mismatches prominently.
- Show "required before sizing" near the top and bottom.
- Do not show a "Place order" control.
- If event data is missing, block "preferred" status and use `needs_check`.
- If option chain is stale or illiquid, show signal-only analysis and suppress structures.
- AI analysis must be visually labeled as generated commentary and must not replace the deterministic signal/structure panels.

## 10. Relationship to existing tabs

| Existing tab | Role | Trade Insights relationship |
|---|---|---|
| Market Structure | GEX, walls, positioning | Provides pin/range/trend context. |
| Volatility | IV/RV spread proxy, regime, term, smile | Provides vol setup and mean-reversion signal. |
| Flow | Premium/strike/expiry flow | Provides direction and concentration. |
| Trade Insights | New research synthesis | Combines the above into candidate expressions. |
| Trade Plan | Concrete selected plan | Downstream of one selected idea after checks. |

The raw audit-trail tables previously under a `Tables` tab now live inside `Flow` (post-2026-05 merge); Trade Insights does not need its own raw-rows surface.

## 11. First implementation scope

V1 should be deliberately narrow:

1. Add tab route and UI shell.
2. Add static response model and mock data from current report fields.
3. Implement signal stack from existing `SingleStockReport` + Volatility v2 endpoint.
4. Implement current-chain flow table from stored `option_contract_snapshots`.
5. Implement term-structure table from current IV term snapshots.
6. Generate candidate structures with rule-based templates:
   - call credit spread;
   - put credit spread;
   - iron condor;
   - long straddle;
   - calendar spread.
7. Require event/liquidity checks before any idea can be `preferred`.

Out of scope for V1:

- order placement;
- portfolio sizing;
- backtest claims;
- ML ranking;
- assignment modeling;
- exact broker margin;
- automatic AI analysis.

Optional V1.5:

1. Add `Run AI Analysis` button.
2. Add AI analysis job table.
3. Add worker path that runs `codex exec` against sanitized deterministic JSON.
4. Render the returned Markdown below the synthesis panel.

## 12. Evidence / references

- Peter Carr and Liuren Wu, "Variance Risk Premiums," Review of Financial Studies, 2009. Use for the distinction between true variance risk premium and the project's IV-RV proxy. https://doi.org/10.1093/rfs/hhn038
- Tim Bollerslev, George Tauchen, and Hao Zhou, "Expected Stock Returns and Variance Risk Premia," Review of Financial Studies, 2009. Use for model-free implied variation and realized-variation measurement caveats. https://doi.org/10.1093/rfs/hhp008
- Gurdip Bakshi and Nikunj Kapadia, "Delta-Hedged Gains and the Negative Market Volatility Risk Premium," Review of Financial Studies, 2003. Use for delta-hedged option P&L needing real option and hedge mechanics. https://doi.org/10.1093/rfs/hhg002
- Amit Goyal and Alessio Saretto, "Cross-section of option returns and volatility," Journal of Financial Economics, 2009. Use for cross-sectional realized-minus-implied volatility sorting and option-return testing. https://doi.org/10.1016/j.jfineco.2009.01.001
- Joost Driessen, Pascal Maenhout, and Grigory Vilkov, "Option-Implied Correlations and the Price of Correlation Risk." Use for true dispersion/implied-correlation requirements. https://ssrn.com/abstract=2166829
- John C. Hull, *Options, Futures, and Other Derivatives*, 11th edition, Pearson, 2022. Use for Greeks, strategy payoff mechanics, smiles/surfaces, and volatility/correlation basics.
- Euan Sinclair, *Volatility Trading*, 2nd edition, Wiley, 2013. Use for volatility trading, implied-vs-realized framing, hedging, sizing, and variance-premium practice.
- The Options Clearing Corporation, "Characteristics and Risks of Standardized Options." Use for exercise, assignment, settlement, and standardized-options risk disclosure. https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- Cboe Options Institute. Use as an exchange-backed education reference for options, multi-leg structures, hedging, and risk management. https://www.cboe.com/optionsinstitute/
- Fidelity OSI explainer. Use for option symbol parsing and the OCC/OSI-style contract identity format. https://www.fidelity.com/webcontent/ap102701-quotes-content/18.11/shtml/osi.shtml
- Option Alpha, "Options Volume vs Open Interest." Use for volume/OI caveats and the fact that volume can exceed OI without proving opening flow. https://optionalpha.com/learn/options-volume-vs-open-interest
- Cboe Open-Close Volume Summary. Use as the stronger data source category when open/close positioning attribution is needed. https://datashop.cboe.com/cboe-options-open-close-volume-summary

## 13. Open questions

- Naming is resolved as `Trade Insights`.
- Which source should be canonical for absolute IV if UW, yfinance, TradingView, and Funda disagree?
- Do we have historical event data, or only next earnings?
- Should calendar spreads be allowed before ex-dividend data is available?
- What minimum OI/volume/spread thresholds should block a structure?
- Should the tab support one preferred idea or multiple ranked ideas?
- Should `Run AI Analysis` be local-dev only, operator-only in production, or available to all authenticated users?
- Should AI analysis reuse an existing result when `input_hash` is unchanged?
- Should normalized option contract columns be added to `option_contract_snapshots`, or should a backend view parse them from `option_symbol`?
