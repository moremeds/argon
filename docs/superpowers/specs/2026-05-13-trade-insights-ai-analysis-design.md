# Trade Insights V1.5 AI Analysis Design

**Date:** 2026-05-13
**Status:** Draft
**Source:** Extracted from the V1.5 notes in `docs/superpowers/plans/2026-05-13-trade-insights-codex-analysis.md` and expanded after V1 Trade Insights landed.

## 1. Goal

Add an optional operator-triggered AI analysis layer to the Trade Insights tab.

The deterministic V1 system remains the source of truth. V1.5 adds a local Codex CLI analysis job that reads the already-persisted Trade Insights JSON plus locally assembled deterministic context from the Market Structure, Volatility, and Flow tabs, then returns a structured research summary. The AI analysis must never change candidate status, max loss, risk flags, required checks, or any deterministic field.

The outcome should produce a compact, structured market brief similar in density to an experienced options desk note. It should answer:

- What is the dominant read across deterministic panels?
- What is the current analytical stance: bullish, bearish, neutral, or wait?
- What exact time was the analysis produced, and which deterministic snapshot/data timestamps does it rely on?
- Which headline metrics explain the read at a glance?
- What are the key upside, base-case, and downside scenarios?
- Which existing candidate structures look most expressive, and why?
- Which single defined-risk expression is the best fit, if any deterministic candidate supports it?
- What conflicts should the operator notice?
- Which checks must be completed before sizing?
- Which candidate ideas should be rejected or de-emphasized?
- What data is missing or stale?

The output should use a combined deterministic prompt payload built from the Trade Insights snapshot and the three preceding analytical tabs.

Actual local data produced by those tabs today:

- Market Structure tab uses `SingleStockReport` plus `StockHistoryResponse`.
  - `market_structure`: spot, nearest expiry, total call/put GEX, net GEX, total call/put DEX OI, max pain, top call/put OI strikes.
  - `market_structure_levels`: GEX flip, call wall, put wall, max magnet, second magnet, max accel, including strike, net GEX, percent from spot, and gamma-per-dollar where available.
  - `strike_gex_curve`: per-strike/per-expiry net, call, and put GEX.
  - `max_pain_rows`: expiry-level max pain and adjacent strikes.
  - `stock_history.rows`: daily spot, GEX flip, net GEX, net DEX, IV30D, PCR volume, and bias.
- Volatility tab uses `VolatilitySeriesResponse`.
  - `header`: IV, RV, IV rank, IV rank 1Y, IV/RV 52-week ranges, 30-day IV percentile, 30-day implied move, 25-delta skew, VRP, VRP signal, and VRP note.
  - `term_structure`: expiry, DTE, per-strike IV maps, and strike maps.
  - `smile`: expiry-level IV smile points.
  - `hv_iv_history`: dated IV/RV history.
  - `iv_percentile_distribution`: histogram bins, current IV, and current percentile.
  - `iv_of_iv`, `rv_spy_corr`, `regime_quadrant`, `divergence`, `divergence_headline`, `vrp_spread`, `vrp_spread_headline`, and `spot`.
- Flow tab uses `SingleStockReport`.
  - `flow`: alert count, net premium, bull/bear premium, ask/bid-side premium, and top alerts.
  - `dark_pool_print_count`, `dark_pool_notional`.
  - `short_data`: shares available, fee rate, rebate rate, timestamp.
  - `options_timeline`: daily call/put volume and premium, ask/bid-side volume, OI totals, rolling volume averages, and bullish/bearish premium.
  - `option_chain_per_strike`: expiry/strike call and put volume/OI.
  - `oi_change_top`: current/previous OI, OI diff/change, volume, trades, average/last fill, rank, ask/bid/mid/no-side volume.
  - `aggregates`: call/put OI totals, call/put volume totals, ask/bid-side volume totals, PCR OI, PCR volume, and IV30D.
  - `next_earnings_date` when promoted from top alerts.
- Trade Insights tab uses `TradeInsightsResponse`.
  - Header, source reconciliation, signal stack, chain/flow read rows, term/move read rows, deterministic candidate structures, and synthesis.

Do not claim unavailable fields. For example, current tab payloads do not expose charm/vanna summaries or a traditional short-interest percentage; the AI should call those out as missing if they matter.

## 2. Non-Goals

- No automatic analysis on page load or every scan.
- No user-authored prompts.
- No direct OpenAI API integration in V1.5. The only model runner is the local `codex exec` CLI.
- No order placement, sizing, or executable trading instructions.
- No AI override of deterministic `status`, `risk_flags`, `max_loss`, `max_profit`, `preferred_idea_id`, or `required_before_sizing`.
- No hidden analysis that is not persisted.

## 3. Product Behavior

The Trade Insights page remains fully usable without AI. Below deterministic synthesis, the page shows a secondary generated-analysis panel:

```text
AI Analysis
[Run AI Analysis]
Status: Not run / Queued / Running / Complete / Failed
```

When the operator clicks the control:

1. The API reuses or creates the latest deterministic Trade Insights snapshot for the ticker.
2. The API assembles a combined deterministic analysis input from the Trade Insights snapshot plus current local Market Structure, Volatility, and Flow tab payloads.
3. The API computes `analysis_input_hash` from that combined deterministic input, excluding volatile execution fields such as `requested_at`, `produced_at`, prompt text, and schema.
4. If a successful analysis already exists for the same `(ticker, analysis_input_hash, prompt_version, model)`, the API returns that analysis instead of enqueueing a duplicate unless `force_rerun=true`.
5. Otherwise, the API enqueues a `trade_insight_ai_analyses` row with the deterministic `analysis_input_jsonb` and `analysis_input_hash`.
6. The worker claims one queued AI analysis at a time.
7. The worker injects a fresh `produced_at` timestamp into the stored analysis input, then runs local `codex exec` with a fixed prompt, read-only sandbox, structured output schema, hard timeout, minimal environment, and no UW/FMP/Massive secrets.
8. The worker stores the exact prompt, final prompt payload, JSON schema, structured outcome, rendered Markdown summary, and production timestamp for audit/review.
9. The UI polls by `analysis_id`, then renders the structured result.

The UI must label the result as generated commentary. It must not visually promote a candidate from `needs_check` to executable.

The generated view should be concise. The first screen of the AI panel should show a card grid with the headline read, score/conviction, key metrics, scenarios, primary risk, and watch trigger. More verbose sections such as Market Structure, Volatility, Flow/Positioning, VRP, and candidate expression details can sit below as grouped cards. The page should not become a long wall of prose.

## 4. Local Codex CLI Contract

V1.5 uses local Codex CLI only.

The official Codex docs describe non-interactive mode as `codex exec`, intended for scripts, CI, scheduled jobs, and output that can be piped into other tools. The same docs state that `codex exec` runs read-only by default, supports explicit sandbox settings, supports JSONL event output, and supports writing the final message to a file with `--output-last-message`. They also describe `--output-schema` for machine-readable final output.

Local command shape:

```bash
codex exec \
  --ephemeral \
  --sandbox read-only \
  --ignore-user-config \
  --ignore-rules \
  --skip-git-repo-check \
  --cd "$TMPDIR" \
  [--model "$TRADE_INSIGHTS_AI_MODEL"] \
  --output-schema "$SCHEMA_PATH" \
  --output-last-message "$RESULT_PATH" \
  -
```

Notes:

- Prompt input is passed on stdin, not interpolated into a shell command.
- The working directory is an empty temp directory, not the repo root. Codex does not need repository files to analyze the deterministic JSON.
- The prompt includes the deterministic payload inline or by temp-file contents controlled by the worker.
- Before runner implementation, verify the installed CLI with `codex --version` and `codex exec --help`. Do not use or silently drop unverified sandbox/config flags.
- The `--model` flag is omitted when no model is configured. Stored rows use a normalized model label such as `codex-default` in that case.
- `--ignore-user-config` prevents local Codex config from changing sandbox, model, tool, or environment behavior; Codex auth still uses `CODEX_HOME`.
- The child process environment is allowlisted. It may include `PATH`, `HOME`, `CODEX_HOME`, locale variables, and optional Codex auth variables needed by the CLI. It must not include `UW_SCAN_API_KEY`, `MASSIVE_API_KEY`, database credentials, or unrelated app secrets.
- Timeout is enforced by the Python subprocess wrapper.
- Output size is capped before writing to Postgres. Default cap is `262144` bytes.

## 5. Prompt Contract

The prompt is fixed backend code. It is not user-editable.

Prompt version:

```text
trade-insights-ai-v1
```

The prompt payload must have this high-level shape:

```jsonc
{
  "prompt_version": "trade-insights-ai-v1",
  "analysis_input_hash": "sha256-combined...",
  "analysis_produced_at": "2026-03-24T20:18:42Z",
  "ticker": "TSLA",
  "run_id": 123,
  "trade_insights_input_hash": "sha256-trade-insights...",
  "tabs": {
    "market_structure": {},
    "volatility": {},
    "flow": {},
    "positioning": {},
    "trade_insights": {}
  },
  "candidate_structures": [],
  "required_before_sizing": [],
  "data_freshness": []
}
```

Rules for building the prompt payload:

- Use existing local assemblers/repository reads only. Do not call UW, FMP, Massive, broker APIs, or web search during AI analysis.
- Compute `analysis_input_hash` from canonical JSON of the normalized deterministic input before adding `analysis_produced_at` or any worker execution metadata. Canonical JSON must sort keys and use deterministic separators.
- Exclude volatile assembly timestamps from `analysis_input_hash`, including `SingleStockReport.generated_at`, `TradeInsightsResponse.as_of` when it reflects assembly time, `requested_at`, `produced_at`, prompt text, and schema. The prompt may still include assembly timestamps as non-authoritative metadata, but source data dates/timestamps must drive freshness.
- Exclude `VolatilitySeriesResponse.as_of` from `analysis_input_hash` in V1.5 because the current assembler sets it to request-time `_date.today()`, not an underlying source timestamp.
- Include true source freshness fields in the hash when present, such as row dates, expiry dates, short-data timestamp, and persisted Trade Insights candidate/synthesis content after volatile fields are removed.
- Include enough Market Structure fields to explain GEX flip, walls/magnets/accelerators, net GEX/DEX, max pain, strike GEX curve, and historical flip/bias migration.
- Include enough Volatility fields to explain IV/HV, IV rank/percentile, skew, term structure, VRP, and volatility regime when available.
- Include enough Flow/Positioning fields to explain net premium, ask/bid-side premium, bull/bear premium, expiry/strike concentration, dark pool context, short-share availability/borrow data, OI changes, PCR, and T+1 caveats when available.
- Split flow and positioning deliberately: `tabs.flow` contains `flow`, `options_timeline`, and `option_chain_per_strike`; `tabs.positioning` contains `dark_pool_print_count`, `dark_pool_notional`, `short_data`, `oi_change_top`, flow-related `aggregates`, and `next_earnings_date`.
- Include the deterministic Trade Insights candidates and synthesis exactly as persisted.
- If `next_earnings_date` is present, also include the deterministic V1 fact that `event_data_known=false` and every candidate remains `needs_check`. The AI may flag this as a required check, but must not treat the date as authoritative event validation.
- If a tab lacks a field, include a missing-data note rather than omitting the whole tab.
- Fresh tickers with empty `stock_history.rows`, `hv_iv_history`, or `vrp_spread` are valid degraded inputs. The analysis should mark the missing data instead of failing the request.
- Exclude secrets, DSNs, raw API tokens, and unnecessary raw payload bulk.

`data_freshness` is a compact audit array derived from the same normalized prompt input. Each item has `{ "source": "...", "as_of": "...", "freshness_type": "source|assembly|missing", "staleness_hint": "..." }`. Prefer true source dates such as history row dates, expiry dates, and short-data timestamps. Assembly-time fields may be listed with `freshness_type="assembly"`, but they do not participate in `analysis_input_hash`.

Prompt payload array bounds:

- `stock_history.rows`: newest 30 rows.
- `strike_gex_curve`: top 40 rows by absolute `net_gex`, plus any rows matching named `market_structure_levels` strikes when present.
- `max_pain_rows`: nearest 12 expiries.
- `volatility.term_structure`: nearest 20 expiries.
- `volatility.smile`: nearest 6 expiries, max 25 points per expiry after downsampling by strike order.
- `volatility.hv_iv_history`, `iv_of_iv`, and `rv_spy_corr`: newest 90 points.
- `volatility.divergence`: newest 20 points.
- `volatility.vrp_spread`: newest 30 points.
- `flow.top_alerts`: already capped by `SingleStockReport` at 10.
- `options_timeline`: newest 60 rows.
- `option_chain_per_strike`: top 120 rows by combined volume/OI, while preserving rows near spot when spot is known.
- `oi_change_top`: current repository result cap of 50 rows.

The prompt must instruct Codex:

- Analyze only the supplied combined deterministic prompt payload.
- Do not fetch outside data.
- Do not use tools.
- Produce `analysis_produced_at` as the current worker-provided timestamp, not a model-invented time.
- Echo deterministic snapshot/data timestamps exactly where supplied, and mark stale/unknown data instead of implying freshness.
- Build the read from `tabs.market_structure`, `tabs.volatility`, `tabs.flow`, and `tabs.positioning` before discussing trade expressions.
- Preserve every candidate `status`.
- Preserve every candidate `risk_flags` array.
- Preserve every candidate max-loss/max-profit value exactly as supplied.
- Treat all `needs_check` candidates as not executable.
- Mention missing data rather than filling gaps.
- Avoid order placement, position sizing, or personalized financial advice.
- Keep the result compact and card-friendly.
- Emit only JSON matching the provided schema.

## 6. Structured Outcome

The AI output is JSON, not free-form Markdown. Markdown is a rendered view of the JSON, generated by backend code after validation.

Schema name:

```text
TradeInsightAiOutcome
```

Top-level shape:

```jsonc
{
  "schema_version": "trade-insights-ai-v1",
  "analysis_produced_at": "2026-03-24T20:18:42Z",
  "ticker": "TSLA",
  "underlying_price": "$380.88",
  "snapshot": {
    "run_id": 123,
    "trade_insights_input_hash": "sha256-trade-insights...",
    "analysis_input_hash": "sha256-combined...",
    "data_as_of": "2026-03-24",
    "freshness_label": "mixed",
    "source_notes": ["Flow: same-day snapshot", "Positioning: prior close T+1"]
  },
  "headline": {
    "title": "TSLA near gamma resistance with cheap vol and bullish flow",
    "stance": "bullish",
    "stance_label": "BUY setup",
    "score": 31,
    "score_scale": 100,
    "conviction": "B",
    "conviction_label": "Moderate",
    "top_reason": "Cheap IV plus bullish flow",
    "primary_risk": "$382.50 GEX wall may cap immediate upside",
    "watch_trigger": "Break above $382.50 with volume"
  },
  "metric_cards": [
    {
      "label": "IV Rank",
      "value": "3.4/100",
      "tone": "bullish",
      "source_path": "tabs.volatility.header.iv_rank",
      "note": "Options screen historically cheap."
    }
  ],
  "scenario_cards": [
    {
      "case": "upside",
      "tone": "bullish",
      "title": "Break $382.50 wall",
      "description": "$392-$400 target zone from supplied GEX levels."
    },
    {
      "case": "base",
      "tone": "neutral",
      "title": "$375-$385 range",
      "description": "Positive gamma can pin price near the wall."
    },
    {
      "case": "downside",
      "tone": "bearish",
      "title": "Lose $370 support",
      "description": "Risk of gap-fill behavior if support fails."
    }
  ],
  "score_breakdown": [
    {
      "section": "market_structure",
      "score": 8,
      "max_score": 28,
      "summary": "Positive gamma with a nearby resistance wall."
    },
    {
      "section": "volatility",
      "score": 8,
      "max_score": 28,
      "summary": "IV rank near one-year floor favors long premium over selling."
    },
    {
      "section": "flow_positioning",
      "score": 15,
      "max_score": 44,
      "summary": "Bullish premium and OI concentration support upside watch."
    }
  ],
  "section_cards": {
    "market_structure": {
      "title": "Market Structure",
      "score": 8,
      "max_score": 28,
      "summary": "Positive gamma above the flip, but a large wall caps immediate upside.",
      "highlights": [
        {"label": "GEX Flip", "value": "$376.25", "source_path": "tabs.market_structure.market_structure_levels.gex_flip.strike", "note": "Below live price."},
        {"label": "Net GEX", "value": "Positive", "source_path": "tabs.market_structure.market_structure.net_gex", "note": "Mean-reverting/pinning action likely."}
      ],
      "levels": [
        {"price": "$382.50", "kind": "resistance", "value": "+$100.4M", "importance": "major", "source_path": "tabs.market_structure.strike_gex_curve"},
        {"price": "$370", "kind": "support", "value": "-$44.2M", "importance": "major", "source_path": "tabs.market_structure.strike_gex_curve"}
      ],
      "data_quality": "high"
    },
    "volatility": {
      "title": "Volatility",
      "score": 8,
      "max_score": 28,
      "summary": "IV is cheap versus its own range; term structure is normal.",
      "highlights": [
        {"label": "IV / HV", "value": "42.0% / 31.1%", "source_path": "tabs.volatility.header", "note": "Spread +10.9%."},
        {"label": "Term Structure", "value": "Contango", "source_path": "tabs.volatility.term_structure", "note": "No supplied event inversion."}
      ],
      "data_quality": "medium"
    },
    "flow_positioning": {
      "title": "Flow & Positioning",
      "score": 15,
      "max_score": 44,
      "summary": "Bullish net premium and call-heavy strikes support breakout monitoring.",
      "highlights": [
        {"label": "Net Premium", "value": "+$524.3M", "source_path": "tabs.flow.flow.net_premium", "note": "One-day snapshot."},
        {"label": "OI Signal", "value": "Bullish [T+1]", "source_path": "tabs.positioning.oi_change_top", "note": "Prior close positioning caveat."}
      ],
      "data_quality": "medium"
    }
  },
  "vrp_assessment": {
    "signal": "do_not_sell",
    "title": "VRP Assessment - Do Not Sell",
    "summary": "IV rank is near the 52-week floor and VRP is thin.",
    "metrics": [
      {"label": "VRP", "value": "7.6%"},
      {"label": "Z-Score", "value": "0.28"}
    ],
    "reason": "Failed VRP entry threshold in supplied deterministic data."
  },
  "preferred_expression": {
    "idea_id": "A",
    "structure": "bull_call_spread",
    "title": "Bull Call Spread - TSLA",
    "subtitle": "Buy $385 Call / Sell $400 Call - Apr 17, 2026",
    "estimated_entry": "~$6.40 debit",
    "max_profit_observed": "~$8.60",
    "max_loss_observed": "~$6.40",
    "reward_risk": "1.34:1",
    "why": "Cheap IV and bullish flow make the supplied defined-risk long-delta candidate the cleanest expression.",
    "management_notes": [
      "Take-profit, stop, and time-stop ideas are commentary only and must be verified before sizing."
    ],
    "status_observed": "needs_check",
    "risk_flags_observed": ["verify_bid_ask", "verify_open_interest"]
  },
  "dominant_read": {
    "headline": "Front premium is elevated, but flow is mixed.",
    "summary": "Plain-English synthesis of deterministic evidence.",
    "confidence_commentary": "Why confidence is high/medium/low.",
    "data_quality_commentary": "What source/data caveats matter."
  },
  "best_expressions": [
    {
      "idea_id": "A",
      "structure": "call_credit_spread",
      "role": "best_defined_risk_short_vol_expression",
      "why": "Reason grounded in supplied deterministic fields.",
      "caveats": ["Bullish flow can break the call side."],
      "status_observed": "needs_check",
      "risk_flags_observed": ["bullish_flow_can_break_call_side"]
    }
  ],
  "conflicts": [
    {
      "lens": "flow_vs_structure",
      "severity": "medium",
      "description": "Bullish call demand conflicts with short-call premium.",
      "affected_idea_ids": ["A"]
    }
  ],
  "required_checks": [
    {
      "check": "Confirm event calendar",
      "reason": "The deterministic payload marks event_data_known=false.",
      "blocks_sizing": true,
      "source": "synthesis.required_before_sizing"
    }
  ],
  "rejected_ideas": [
    {
      "idea_id": "C",
      "structure": "long_straddle",
      "reason": "No clear long-vol edge in supplied deterministic setup."
    }
  ],
  "missing_data": [
    "No event calendar data in deterministic payload."
  ],
  "rendering": {
    "disclaimer": "Generated by local Codex from deterministic Trade Insights data. Not financial advice.",
    "card_order": [
      "headline",
      "metrics",
      "scenarios",
      "market_structure",
      "volatility",
      "flow_positioning",
      "vrp_assessment",
      "preferred_expression",
      "checks"
    ]
  },
  "guardrails": {
    "statuses_preserved": true,
    "risk_flags_preserved": true,
    "no_executable_recommendations": true
  }
}
```

Validation rules:

- `schema_version` must equal the prompt version.
- `analysis_produced_at` must equal the worker-supplied production timestamp.
- `ticker`, `snapshot.run_id`, `snapshot.trade_insights_input_hash`, and `snapshot.analysis_input_hash` must match the deterministic payload/row.
- `headline.stance` must be one of `bullish`, `bearish`, `neutral`, `mixed`, or `wait`.
- `headline.stance_label` may use compact market language such as `BUY setup`, `SELL setup`, `WAIT`, or `NO TRADE`, but the renderer must label it as an analytical stance rather than an order instruction.
- `headline.score` and all `score_breakdown[].score` values must be integers in their declared scales.
- `metric_cards`, `scenario_cards`, `score_breakdown`, and `section_cards` must be present so the UI can render a compact card grid without parsing prose.
- `section_cards.market_structure`, `section_cards.volatility`, and `section_cards.flow_positioning` are required. They must cite supplied deterministic fields from the actual tab payload inventory above or explicitly say the data is missing.
- Every `metric_cards[]`, `section_cards.*.highlights[]`, and `section_cards.*.levels[]` item must include a `source_path` pointing into the prompt payload, unless the item is explicitly describing missing data. Validation should require enough path segments to prove the source family exists, for example `tabs.volatility.header`, `tabs.flow.flow`, or `tabs.positioning.oi_change_top`; it should not require full resolution into pruned arrays.
- Every `best_expressions[].idea_id` and `rejected_ideas[].idea_id` must exist in the deterministic payload.
- `preferred_expression.idea_id`, when present, must exist in the deterministic payload and must also satisfy the status/risk-flag echo checks.
- `status_observed` must equal the deterministic candidate status for that idea.
- `risk_flags_observed` must exactly equal the deterministic risk flags for that idea, order-preserving.
- `guardrails.statuses_preserved`, `guardrails.risk_flags_preserved`, and `guardrails.no_executable_recommendations` must all be `true`.
- Output is rejected for field-aware imperative instructions, not for naive whole-JSON substring matches. Reject imperatives in `headline.stance_label`, `preferred_expression.title`, `preferred_expression.subtitle`, and sentence starts in free-text fields, such as `buy now`, `sell now`, `enter now`, `execute this trade`, `place this order`, or `size this position`. Do not reject compact analytical labels such as `BUY setup`, conditional scenario prose, or benign nouns such as `sizing` inside required-check text.
- Output is rejected if serialized JSON exceeds the configured max bytes.
- AI Pydantic outcome models must reject unknown extra fields rather than silently ignoring them.

## 7. Persistence

Add `uw_scan.trade_insight_ai_analyses`.

Required columns:

| Column | Type | Notes |
|---|---|---|
| `analysis_id` | `uuid primary key default gen_random_uuid()` | Returned to UI for polling. |
| `snapshot_id` | `bigint not null references trade_insight_snapshots(snapshot_id)` | Links to immutable deterministic payload. |
| `ticker` | `text not null` | Uppercase. |
| `run_id` | `bigint not null` | Copied from snapshot. |
| `trade_insights_input_hash` | `text not null` | Hash copied from `trade_insight_snapshots.input_hash`. |
| `analysis_input_hash` | `text not null` | Stable hash of the combined deterministic analysis input, excluding production timestamp and prompt execution metadata. |
| `analysis_input_jsonb` | `jsonb not null` | Combined deterministic tab payload captured at request time and used by the worker. |
| `model` | `text not null` | Local Codex model arg used, or `codex-default` when no model flag is passed. |
| `prompt_version` | `text not null` | `trade-insights-ai-v1`. |
| `prompt_text` | `text` | Exact prompt sent to local Codex for review/audit. Filled before the worker invokes Codex. |
| `prompt_payload_jsonb` | `jsonb` | Final sanitized prompt payload sent to Codex, including `analysis_produced_at`. Filled before the worker invokes Codex. |
| `output_schema_jsonb` | `jsonb` | JSON schema supplied through `--output-schema`. Filled before the worker invokes Codex. |
| `status` | `text not null` | `queued`, `running`, `succeeded`, `failed`. |
| `outcome_jsonb` | `jsonb` | Validated structured outcome on success. |
| `markdown` | `text` | Backend-rendered Markdown summary on success. |
| `error_message` | `text` | Truncated worker/API failure detail. |
| `requested_at` | `timestamptz not null default now()` | Enqueue time. |
| `started_at` | `timestamptz` | Worker start. |
| `produced_at` | `timestamptz` | Exact worker timestamp injected into the prompt and validated against `analysis_produced_at`. |
| `finished_at` | `timestamptz` | Worker terminal time. |

`analysis_input_jsonb` and `prompt_payload_jsonb` are expected to be moderately large audit rows because they include bounded tab slices and the exact prompt payload. Postgres JSONB/TOAST can handle this shape; V1.5 relies on pruning bounds plus the worker output cap rather than introducing a separate prompt-payload byte cap.

Indexes and constraints:

- Unique successful/reusable key on `(ticker, analysis_input_hash, prompt_version, model)` where `status='succeeded'`.
- Queue index on `(status, requested_at)`.
- Check constraint for allowed statuses.

Reuse lookup returns the most recent succeeded row for `(ticker, analysis_input_hash, prompt_version, model)`, or `None`. Failed, queued, and running rows are not reusable.

The table stores AI output separately from `trade_insight_snapshots`. No deterministic rows are mutated by AI.

## 8. API

Add endpoints under the existing Trade Insights router.

```text
POST /api/stock/{ticker}/trade-insights/ai-analysis
GET  /api/stock/{ticker}/trade-insights/ai-analysis/{analysis_id}
```

POST request:

```json
{
  "force_rerun": false
}
```

POST response:

```jsonc
{
  "analysis_id": "uuid",
  "ticker": "TSLA",
  "run_id": 123,
  "trade_insights_input_hash": "sha256-trade-insights...",
  "analysis_input_hash": "sha256-combined...",
  "model": "gpt-5.4",
  "prompt_version": "trade-insights-ai-v1",
  "status": "queued",
  "produced_at": null,
  "outcome": null,
  "markdown": null,
  "error_message": null,
  "requested_at": "...",
  "started_at": null,
  "finished_at": null,
  "reused": false
}
```

POST response when an existing successful analysis is reused:

```jsonc
{
  "analysis_id": "uuid",
  "ticker": "TSLA",
  "run_id": 123,
  "trade_insights_input_hash": "sha256-trade-insights...",
  "analysis_input_hash": "sha256-combined...",
  "model": "gpt-5.4",
  "prompt_version": "trade-insights-ai-v1",
  "status": "succeeded",
  "produced_at": "2026-03-24T20:18:42Z",
  "outcome": {
    "analysis_produced_at": "2026-03-24T20:18:42Z"
  },
  "markdown": "Generated Markdown summary...",
  "error_message": null,
  "requested_at": "...",
  "started_at": "...",
  "finished_at": "...",
  "reused": true
}
```

GET response has the same shape without `reused`.

Behavior:

- POST returns `404` if no deterministic run exists for the ticker.
- POST returns `503` before creating any new AI analysis row if AI analysis is disabled by configuration.
- POST first builds and persists the latest deterministic Trade Insights snapshot, using the same logic as `GET /trade-insights`.
- The deterministic snapshot helper returns the `snapshot_id` and `trade_insights_input_hash`, but callers own commits. GET commits after deterministic snapshot/candidates are written. POST commits after deterministic snapshot creation and AI row enqueue so the worker can query them.
- POST assembles and stores the combined deterministic analysis input at request time.
- POST must build the Volatility tab payload in a read-only assembler mode. Existing `assemble_volatility_series` persists VRP/analytics derived rows and commits unless changed; V1.5 must add and use a no-persistence path so reuse checks do not mutate derived volatility tables.
- POST must pass `backfill_status=(repo.get_volatility_backfill_status(ticker) or {}).get("status") or "ready"` into volatility assembly. `repo.get_volatility_backfill_status` returns a mapping or `None`, not a string.
- POST normalizes a blank model setting to `codex-default`, then reuses a completed matching analysis unless `force_rerun=true`.
- GET returns `404` if the analysis does not exist for that ticker.
- Failed analyses do not affect deterministic Trade Insights GET.

## 9. Worker

Add a worker polling job:

```text
trade_insights_ai_tick
```

Behavior:

- Runs every few seconds through `IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds)`.
- Heartbeats with `repo.upsert_heartbeat("trade_insights_ai_tick")`.
- Claims one queued analysis with `FOR UPDATE SKIP LOCKED`.
- Marks it `running`.
- Loads the queued row's `analysis_input_jsonb`.
- Creates a single `produced_at` timestamp at execution time.
- Builds the final prompt payload by adding `analysis_produced_at` to the stored deterministic analysis input.
- Builds the prompt with that `produced_at` timestamp.
- Stores the prompt text, prompt payload JSON, output schema JSON, and `produced_at` before running Codex.
- Commits the claim/prepare work and closes the database connection before running local Codex. Do not hold an idle DB connection across a 90-second subprocess timeout.
- Runs the local Codex CLI wrapper.
- Reopens a database connection to complete or fail the row after subprocess execution.
- Validates the JSON result against `TradeInsightAiOutcome`.
- Rejects the result if `analysis_produced_at` differs from the injected `produced_at`.
- Renders Markdown from validated JSON.
- Marks the row `succeeded`.
- On timeout, non-zero exit, invalid JSON, schema mismatch, guardrail mismatch, or output-size breach, marks the row `failed` with a concise error.

Concurrency:

- V1.5 should run one analysis at a time per worker process.
- Scheduler registration must use `max_instances=1`, `coalesce=True`, and an explicit `misfire_grace_time` so a long or hung Codex run does not queue many overlapping ticks.
- Duplicate successful analyses are prevented by the reusable-key lookup, not by letting several workers race.

## 10. UI

Add a client island below `InsightsSynthesisPanel`.

States:

- Not run: show secondary `Run AI Analysis` button.
- Disabled/unavailable: show that local Codex AI analysis is not enabled for this environment.
- Queued/running: disable button, show status.
- Succeeded: render structured sections.
- Failed: show failure message and allow retry.

Display as a grouped card grid, not a long linear report:

- Header card: ticker, underlying price, analytical stance label, score, conviction, production time, and data freshness.
- Metric cards: IV rank, IV/HV, skew, term structure, volatility regime, net premium, put/call ratios, GEX flip, short-borrow data, and OI signal when present.
- Scenario cards: upside, base, and downside.
- Section cards: Market Structure, Volatility, Flow/Positioning, and VRP Assessment.
- Preferred Expression card: one best defined-risk structure when validated, with deterministic max profit/loss and `needs_check` status visible.
- Operational cards: Conflicts, Required Checks, Rejected Ideas, Missing Data, and Guardrails.

The panel label must make generated status clear:

```text
Generated analysis from local Codex. Deterministic risk checks remain authoritative.
```

The UI should render from `outcome`, not parse `markdown`.
The UI should format `analysis_produced_at` and deterministic data timestamps so the operator can tell whether the read is current or stale.

## 11. Testing

Backend:

- Migration idempotency.
- Repository enqueue, reuse, claim, complete, fail, and fetch.
- API POST enqueue and reuse.
- Analysis input hash changes when Market Structure, Volatility, Flow, positioning, or Trade Insights deterministic inputs change.
- API GET status.
- 404 when no deterministic run exists.
- Worker success with mocked subprocess.
- Worker timeout and failure with mocked subprocess.
- Worker invalid JSON and guardrail mismatch.
- Output-size cap.
- Prompt text, prompt payload, output schema, and produced timestamp are persisted.
- Validation rejects mismatched `analysis_produced_at`.
- Validation rejects missing required card sections.

Frontend:

- Button calls POST.
- Polling transitions queued/running/succeeded.
- Structured card grid renders headline, metrics, scenarios, section cards, preferred expression, and operational cards.
- Failed status renders retry affordance.
- Deterministic panels render even when AI status fails.
- Production time and data freshness are visible.

CLI integration:

- Unit tests mock subprocess. Do not require local Codex auth in default test suite.
- An optional manual smoke can run local `codex exec` against a fixture payload when the developer explicitly opts in.

## 12. Open Questions For Implementation

- Exact default model: use a setting such as `TRADE_INSIGHTS_AI_MODEL`, defaulting to the installed Codex CLI default unless product wants a named model.
- Whether to expose a "rerun" menu in UI or keep retry only after failures in V1.5.
- Whether to prune old successful analyses later. V1.5 can leave pruning out.
