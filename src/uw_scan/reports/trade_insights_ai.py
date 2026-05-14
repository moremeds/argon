"""Prompt contract helpers for Trade Insights AI analysis.

V1.5 keeps the model runner local and audit-oriented: the worker passes a
bounded deterministic payload into Codex and stores the validated JSON result.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from uw_scan.models import TradeInsightAiOutcome

PROMPT_VERSION = "trade-insights-ai-v2"
STRATEGY_FAMILY_IDS = frozenset(
    {
        "long_stock",
        "long_call",
        "call_debit_spread",
        "put_credit_spread",
        "covered_call",
        "cash_secured_put",
        "iron_condor",
        "short_strangle",
        "long_put",
        "put_debit_spread",
        "calendar_spread",
        "no_trade",
    }
)
FINAL_RATING_VALUES = ("A", "B", "C", "D", "F")

MARKET_INTELLIGENCE_PROMPT = """You are an institutional options strategist, market-structure analyst, and risk manager.

Your job is to analyze one stock using three evidence pillars:

1. Market Structure
   - Spot price
   - GEX flip
   - Net GEX
   - Net DEX
   - Gamma magnets / max pain / put wall / call wall
   - GEX profile by strike
   - Expected range
   - Dealer gamma regime
   - Support / resistance from options positioning

2. Volatility
   - IV ATM
   - Realized volatility
   - IV/RV ratio
   - VRP
   - IV rank / IV percentile
   - Term structure
   - Skew
   - IV distribution
   - IV vs RV time series
   - Regime quadrant: Goldilocks / Fragile Calm / Stock Picker / Systemic Panic

3. Flow and Positioning
   - Options premium
   - Bull vs bear premium
   - Call / put volume
   - Call / put OI
   - Top alerts
   - OI change movers
   - Dark pool prints
   - Short availability / borrow fee / rebate
   - Sweep / repeated hit / churn flags
   - Large notional strikes and expiries

The objective is to produce a high-quality trading interpretation, not a dashboard summary.

Important rules:

- Do not invent data.
- Only use the input provided.
- If a required field is missing, say “Missing / not provided.”
- Do not overfit to one metric.
- Do not blindly say bullish just because call premium is high.
- Do not blindly say bearish just because puts are active.
- Resolve conflicts explicitly.
- Distinguish between:
  - directional signal
  - volatility signal
  - positioning signal
  - execution readiness
- Explain whether the setup favors:
  - long stock
  - long calls
  - call debit spread
  - put credit spread
  - covered call
  - short strangle / iron condor
  - long put / put debit spread
  - no trade
- If the data is contradictory or incomplete, recommend “watch / wait” and specify exactly what would make it actionable.
- Trade recommendations must include entry trigger, invalidation level, target zone, time horizon, preferred option structure, and risk notes.
- All recommendations are research-only and not financial advice.

Input:

Ticker: {{ticker}}
As-of date: {{as_of_date}}
Spot: {{spot}}

Market Structure Data:
{{market_structure_data}}

Volatility Data:
{{volatility_data}}

Flow and Positioning Data:
{{flow_positioning_data}}

Optional User Context:
- Current position: {{current_position_or_none}}
- Trading horizon: {{trading_horizon}}
- Risk tolerance: {{risk_tolerance}}
- Preferred strategy type: {{preferred_strategy_type}}
- Earnings / event calendar known? {{event_calendar_status}}

Now produce the analysis using the following structure.

# {{ticker}} Options Market Intelligence Report

## 1. Executive Decision

Give one clear headline:

- Bullish directional
- Bearish directional
- Range-bound / pinned
- Volatility-selling setup
- Volatility-buying setup
- Conflicted / no-trade

Then provide:

| Field | Answer |
|---|---|
| Primary Setup | One sentence |
| Trade Bias | Bullish / Bearish / Range / Volatility |
| Confidence | High / Medium / Low |
| Actionability | Ready / Watchlist / No Trade |
| Best Structure | Specific option or stock structure |
| Main Risk | One sentence |
| Key Trigger | One sentence |

Do not write generic language. Make a decision.

## 2. Market Structure Interpretation

Analyze the market structure in plain English.

Must cover:

- Where spot is relative to GEX flip.
- Whether spot is above or below the dealer regime boundary.
- Whether net GEX is stabilizing or destabilizing.
- Whether net DEX supports directional acceleration or mean reversion.
- Where the nearest magnets are.
- Whether price is likely pinned, pulled upward, pulled downward, or exposed to acceleration.
- Which strikes are likely support and resistance.
- Whether the expected range is narrow, wide, useful, or unreliable.

Output:

### Market Structure Read

State the core read in 3-5 sentences.

### Key Levels

| Level | Price | Meaning | Trading Use |
|---|---:|---|---|
| Spot | | Current reference | |
| GEX Flip | | Regime boundary | |
| Max Magnet | | Attraction / pin risk | |
| Put Wall | | Downside support / risk level | |
| Call Wall / Resistance | | Upside resistance | |
| Max Accel | | Acceleration risk | |

### Market Structure Verdict

Choose one:

- Bullish with positive gamma support
- Bullish but pinned
- Bearish below flip
- Range-bound / magnet-dominated
- Fragile because positive gamma conflicts with aggressive flow
- Unclear due to missing data

Explain why.

## 3. Volatility Interpretation

Analyze whether volatility is cheap, fair, or rich.

Must cover:

- IV vs RV
- VRP
- IV rank / percentile
- term structure
- skew
- whether volatility selling or buying is favored
- whether high IV is justified by event risk
- whether the setup favors defined-risk or undefined-risk structures

Output:

### Volatility Read

3-5 sentences.

### Volatility Evidence

| Metric | Value | Interpretation |
|---|---:|---|
| IV ATM | | |
| RV | | |
| IV/RV | | |
| VRP | | |
| IV Rank | | |
| IV Percentile | | |
| Skew | | |
| Term Structure | | |

### Volatility Verdict

Choose one:

- IV rich, short-vol favored
- IV cheap, long-vol favored
- IV rich but dangerous to sell due to flow/event risk
- IV fair, no edge
- Data insufficient

Then explain which option structures fit the volatility regime.

## 4. Flow and Positioning Interpretation

Analyze whether flow confirms or contradicts market structure.

Must cover:

- Bull premium vs bear premium
- Call demand vs put demand
- Ask-side vs bid-side premium
- Volume/OI quality
- Whether alerts are opening, closing, churn, or ambiguous
- Whether large call flow is bullish speculation, call overwriting, closing, or mixed
- Whether large put flow is protection, bearish bet, or premium sale
- Dark pool / short interest context if available

Output:

### Flow Read

3-5 sentences.

### Flow Quality Check

| Signal | Read | Quality |
|---|---|---|
| Bull premium vs bear premium | | Strong / Medium / Weak |
| Ask vs bid premium | | |
| Call volume / OI | | |
| Put volume / OI | | |
| Top alerts | | |
| OI change | | |
| Dark pool / short data | | |

### Flow Verdict

Choose one:

- Clean bullish accumulation
- Bullish but crowded
- Bearish protection building
- Bearish speculation
- Short-vol / overwrite activity
- Churn / noisy / low signal
- Mixed and not actionable

Explain why.

## 5. Cross-Pillar Conflict Resolution

This is the most important section.

Create a table:

| Pillar | Bias | Strength | Evidence | Conflict |
|---|---|---:|---|---|
| Market Structure | Bull / Bear / Range | 1-5 | | |
| Volatility | Long vol / Short vol / Neutral | 1-5 | | |
| Flow | Bull / Bear / Mixed | 1-5 | | |

Then answer:

1. What is the dominant signal?
2. What is the biggest contradiction?
3. Which data should be trusted more for the next 1-5 trading days?
4. Which data should be trusted more for the next 2-6 weeks?
5. What would invalidate the current interpretation?

Do not skip this. Do not say “mixed” without explaining what wins.

## 6. Scenario Map

Produce three scenarios.

| Scenario | Probability | Trigger | Expected Move | Best Trade |
|---|---:|---|---|---|
| Bullish Breakout | % | | | |
| Range / Pin | % | | | |
| Bearish Breakdown | % | | | |

Probabilities must sum to 100%.

Use the options levels to define triggers.

Example style:

- Bullish breakout if spot holds above GEX flip and breaks above max magnet / call wall with confirming call OI expansion.
- Range if spot remains between flip and magnet with positive GEX.
- Bearish breakdown if spot loses flip and put wall fails.

## 7. Trade Recommendation

Give a concrete recommendation, but only if actionability is sufficient.

If actionable, provide:

### Preferred Trade

| Field | Recommendation |
|---|---|
| Structure | |
| Direction | |
| Entry Trigger | |
| Entry Zone | |
| Expiry | |
| Strike Selection Logic | |
| Target | |
| Stop / Invalidation | |
| Position Size | Conservative / Normal / Small only |
| Why This Structure | |
| Main Risk | |

If not actionable, provide:

### No-Trade / Watchlist Plan

| Watch Item | Trigger Needed | Why It Matters |
|---|---|---|
| Price | | |
| OI confirmation | | |
| IV confirmation | | |
| Flow confirmation | | |
| Event check | | |

## 8. Strategy Selection Logic

Choose the best structure from the following, and explain why others are rejected.

Possible structures:

- Long stock
- Long call
- Call debit spread
- Put credit spread
- Covered call
- Cash-secured put
- Iron condor
- Short strangle
- Long put
- Put debit spread
- Calendar spread
- No trade

Output:

| Strategy | Fit | Reason |
|---|---|---|
| Long stock | Good / Bad / Conditional | |
| Long call | | |
| Call debit spread | | |
| Put credit spread | | |
| Covered call | | |
| Iron condor | | |
| Long put / put spread | | |
| No trade | | |

## 9. Final Trading Plan

End with a direct, practical summary:

- Base case:
- Best trade:
- Avoid:
- Add risk only if:
- Reduce / hedge if:
- Key level to watch:
- Key options signal to watch:
- Final rating:

The final rating must be one of:

- A: Actionable high-conviction
- B: Actionable but size small
- C: Watchlist only
- D: No trade
- F: Data insufficient

Do not end with vague commentary.
Do not simply repeat the dashboard.
Do not use generic phrases like “monitor closely” unless you specify what to monitor and what action follows."""

_VOLATILE_HASH_KEYS = {
    "analysis_input_hash",
    "analysis_produced_at",
    "as_of",
    "generated_at",
    "produced_at",
    "prompt_payload_jsonb",
    "prompt_text",
    "requested_at",
    "output_schema_jsonb",
}


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        _coerce_error = repr(exc)
        return Decimal("0")


def _sorted_recent(
    rows: list[dict[str, Any]], limit: int, key: str = "date"
) -> list[dict[str, Any]]:
    if not rows:
        return []
    return sorted(rows, key=lambda row: str(row.get(key) or ""))[-limit:]


def _sorted_front(
    rows: list[dict[str, Any]], limit: int, key: str = "expiry"
) -> list[dict[str, Any]]:
    if not rows:
        return []
    return sorted(rows, key=lambda row: str(row.get(key) or ""))[:limit]


def _strike_value(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("strike")
        if value is not None:
            return str(value)
    return None


def _named_level_strikes(levels: dict[str, Any]) -> set[str]:
    strikes: set[str] = set()
    for value in levels.values():
        strike = _strike_value(value)
        if strike is not None:
            strikes.add(strike)
    return strikes


def _prune_strike_gex_curve(
    rows: list[dict[str, Any]],
    levels: dict[str, Any],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    named = _named_level_strikes(levels)
    top = sorted(
        rows,
        key=lambda row: abs(_to_decimal(row.get("net_gex"))),
        reverse=True,
    )[:40]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*top, *[r for r in rows if str(r.get("strike")) in named]]:
        by_key[(str(row.get("expiry")), str(row.get("strike")))] = row
    return list(by_key.values())


def _downsample_smile_points(
    points: list[dict[str, Any]], limit: int = 25
) -> list[dict[str, Any]]:
    if len(points) <= limit:
        return sorted(points, key=lambda row: _to_decimal(row.get("strike")))
    sorted_points = sorted(points, key=lambda row: _to_decimal(row.get("strike")))
    if limit <= 1:
        return sorted_points[:limit]
    step = (len(sorted_points) - 1) / (limit - 1)
    indexes = sorted({round(i * step) for i in range(limit)})
    return [sorted_points[i] for i in indexes[:limit]]


def _combined_chain_interest(row: dict[str, Any]) -> Decimal:
    keys = ("call_volume", "put_volume", "call_open_interest", "put_open_interest")
    return sum((_to_decimal(row.get(key)) for key in keys), Decimal("0"))


def _prune_chain_rows(
    rows: list[dict[str, Any]],
    *,
    spot: Any,
    limit: int = 120,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    top = sorted(rows, key=_combined_chain_interest, reverse=True)[:limit]
    if spot is None:
        return top
    near_spot = sorted(
        rows,
        key=lambda row: abs(_to_decimal(row.get("strike")) - _to_decimal(spot)),
    )[:20]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*near_spot, *top]:
        by_key[(str(row.get("expiry")), str(row.get("strike")))] = row
    return list(by_key.values())[:limit]


def _strip_volatile_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile_for_hash(item)
            for key, item in value.items()
            if key not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile_for_hash(item) for item in value]
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_trade_insights_ai_analysis_input(
    *,
    ticker: str,
    run_id: int,
    trade_insights_input_hash: str,
    trade_insights_payload: dict[str, Any],
    stock_report_payload: dict[str, Any],
    stock_history_payload: dict[str, Any],
    volatility_series_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the bounded deterministic payload captured at POST time."""

    market_structure_levels = stock_report_payload.get("market_structure_levels") or {}
    spot = (stock_report_payload.get("market_structure") or {}).get(
        "spot"
    ) or volatility_series_payload.get("spot")
    missing_data: list[str] = []

    stock_history_rows = _sorted_recent(
        list((stock_history_payload.get("rows") or [])),
        30,
    )
    if not stock_history_rows:
        missing_data.append("tabs.market_structure.stock_history.rows is empty")

    hv_iv_history = _sorted_recent(
        list(volatility_series_payload.get("hv_iv_history") or []),
        90,
    )
    if not hv_iv_history:
        missing_data.append("tabs.volatility.hv_iv_history is empty")

    vrp_spread = _sorted_recent(
        list(volatility_series_payload.get("vrp_spread") or []),
        30,
    )
    if not vrp_spread:
        missing_data.append("tabs.volatility.vrp_spread is empty")

    volatility_smile = []
    for curve in _sorted_front(list(volatility_series_payload.get("smile") or []), 6):
        item = dict(curve)
        item["points"] = _downsample_smile_points(list(item.get("points") or []), 25)
        volatility_smile.append(item)

    trade_candidates = list(trade_insights_payload.get("candidate_structures") or [])
    synthesis = trade_insights_payload.get("synthesis") or {}

    analysis_input: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "ticker": ticker.upper(),
        "run_id": run_id,
        "trade_insights_input_hash": trade_insights_input_hash,
        "tabs": {
            "market_structure": {
                "generated_at": stock_report_payload.get("generated_at"),
                "market_structure": stock_report_payload.get("market_structure") or {},
                "market_structure_levels": market_structure_levels,
                "strike_gex_curve": _prune_strike_gex_curve(
                    list(stock_report_payload.get("strike_gex_curve") or []),
                    market_structure_levels,
                ),
                "max_pain_rows": _sorted_front(
                    list(stock_report_payload.get("max_pain_rows") or []),
                    12,
                ),
                "stock_history": {
                    **{
                        key: value
                        for key, value in stock_history_payload.items()
                        if key != "rows"
                    },
                    "rows": stock_history_rows,
                },
            },
            "volatility": {
                "as_of": volatility_series_payload.get("as_of"),
                "backfill_status": volatility_series_payload.get("backfill_status")
                or "ready",
                "header": volatility_series_payload.get("header") or {},
                "term_structure": _sorted_front(
                    list(volatility_series_payload.get("term_structure") or []),
                    20,
                ),
                "smile": volatility_smile,
                "hv_iv_history": hv_iv_history,
                "iv_percentile_distribution": volatility_series_payload.get(
                    "iv_percentile_distribution"
                )
                or {},
                "iv_of_iv": _sorted_recent(
                    list(volatility_series_payload.get("iv_of_iv") or []),
                    90,
                ),
                "rv_spy_corr": _sorted_recent(
                    list(volatility_series_payload.get("rv_spy_corr") or []),
                    90,
                ),
                "regime_quadrant": volatility_series_payload.get("regime_quadrant")
                or {},
                "divergence": _sorted_recent(
                    list(volatility_series_payload.get("divergence") or []),
                    20,
                ),
                "divergence_headline": volatility_series_payload.get(
                    "divergence_headline"
                )
                or "",
                "vrp_spread": vrp_spread,
                "vrp_spread_headline": volatility_series_payload.get(
                    "vrp_spread_headline"
                )
                or "",
                "spot": volatility_series_payload.get("spot"),
            },
            "flow": {
                "flow": stock_report_payload.get("flow") or {},
                "options_timeline": _sorted_recent(
                    list(stock_report_payload.get("options_timeline") or []),
                    60,
                ),
                "option_chain_per_strike": _prune_chain_rows(
                    list(stock_report_payload.get("option_chain_per_strike") or []),
                    spot=spot,
                    limit=120,
                ),
            },
            "positioning": {
                "dark_pool_print_count": stock_report_payload.get(
                    "dark_pool_print_count"
                ),
                "dark_pool_notional": stock_report_payload.get("dark_pool_notional"),
                "short_data": stock_report_payload.get("short_data"),
                "oi_change_top": list(stock_report_payload.get("oi_change_top") or [])[
                    :50
                ],
                "aggregates": stock_report_payload.get("aggregates") or {},
                "next_earnings_date": stock_report_payload.get("next_earnings_date"),
            },
            "trade_insights": trade_insights_payload,
        },
        "candidate_structures": trade_candidates,
        "required_before_sizing": list(synthesis.get("required_before_sizing") or []),
        "event_data_known": False,
        "data_freshness": _build_data_freshness(
            stock_history_rows=stock_history_rows,
            hv_iv_history=hv_iv_history,
            short_data=stock_report_payload.get("short_data") or {},
            volatility_as_of=volatility_series_payload.get("as_of"),
            trade_insights_as_of=trade_insights_payload.get("as_of"),
        ),
        "missing_data": missing_data,
    }
    analysis_input["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        analysis_input
    )
    return analysis_input


def _build_data_freshness(
    *,
    stock_history_rows: list[dict[str, Any]],
    hv_iv_history: list[dict[str, Any]],
    short_data: dict[str, Any],
    volatility_as_of: Any,
    trade_insights_as_of: Any,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    items.append(
        {
            "source": "stock_history",
            "as_of": str((stock_history_rows[-1] or {}).get("date"))
            if stock_history_rows
            else "",
            "freshness_type": "source" if stock_history_rows else "missing",
            "staleness_hint": "latest stored stock history row"
            if stock_history_rows
            else "no stored stock history rows",
        }
    )
    items.append(
        {
            "source": "volatility_hv_iv_history",
            "as_of": str((hv_iv_history[-1] or {}).get("date"))
            if hv_iv_history
            else "",
            "freshness_type": "source" if hv_iv_history else "missing",
            "staleness_hint": "latest stored HV/IV row"
            if hv_iv_history
            else "no stored HV/IV rows",
        }
    )
    items.append(
        {
            "source": "short_data",
            "as_of": str(short_data.get("snapshot_at") or ""),
            "freshness_type": "source" if short_data.get("snapshot_at") else "missing",
            "staleness_hint": "borrow/availability snapshot",
        }
    )
    if volatility_as_of is not None:
        items.append(
            {
                "source": "volatility_response_as_of",
                "as_of": str(volatility_as_of),
                "freshness_type": "assembly",
                "staleness_hint": "request-time assembler date; excluded from hash",
            }
        )
    if trade_insights_as_of is not None:
        items.append(
            {
                "source": "trade_insights_response_as_of",
                "as_of": str(trade_insights_as_of),
                "freshness_type": "assembly",
                "staleness_hint": "deterministic response assembly time; excluded from hash",
            }
        )
    return items


def hash_trade_insights_ai_analysis_input(analysis_input: dict[str, Any]) -> str:
    """Stable hash over deterministic input, excluding execution metadata."""

    return _canonical_hash(_strip_volatile_for_hash(analysis_input))


def build_trade_insights_ai_prompt_payload(
    analysis_input: dict[str, Any],
    *,
    produced_at: datetime,
) -> dict[str, Any]:
    payload = dict(analysis_input)
    payload["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        analysis_input
    )
    payload["analysis_produced_at"] = _iso_z(produced_at)
    return payload


def build_trade_insights_ai_prompt(prompt_payload: dict[str, Any]) -> str:
    payload_json = json.dumps(prompt_payload, sort_keys=True, indent=2, default=str)
    return (
        f"{MARKET_INTELLIGENCE_PROMPT}\n\n"
        "Integration notes for this local JSON runner:\n"
        "Analyze only the supplied combined deterministic prompt payload below.\n"
        "Do not fetch outside data. Do not use tools. Do not invent unavailable fields.\n"
        "Map the prompt placeholders from the JSON payload: ticker from ticker, as_of date "
        "from tabs.trade_insights.as_of or analysis_produced_at, spot from underlying_price "
        "or tabs.market_structure.market_structure.spot, market structure data from "
        "tabs.market_structure, volatility data from tabs.volatility, and flow/positioning "
        "data from tabs.flow and tabs.positioning.\n"
        "For optional user context, use Missing / not provided unless the payload explicitly "
        "contains that field.\n"
        "Build the read from Market Structure, Volatility, Flow, and positioning before "
        "discussing candidate expressions.\n"
        "Use analysis_produced_at exactly as supplied; do not invent a different production time.\n"
        f"schema_version must exactly equal {PROMPT_VERSION}.\n"
        "Preserve every candidate status, every risk_flags array, and every deterministic "
        "max_loss/max_profit value exactly as supplied.\n"
        "Do not defer solely because a deterministic candidate status is needs_check; give "
        "a research-only recommendation when the supplied evidence supports one, and put "
        "remaining checks into the trigger, risk, watchlist, or readiness language.\n"
        "Project safety override: do not recommend naked short options or undefined-risk "
        "short-vol structures; if the prompt's strategy list includes one, reject it unless "
        "it is converted to a defined-risk alternative such as an iron condor.\n"
        "Avoid order placement, position sizing, personalized financial advice, and imperative "
        "trade instructions.\n"
        "Map the full report into the existing TradeInsightAiOutcome JSON fields: use headline "
        "and dominant_read for Executive Decision, section_cards for the three pillar reads, "
        "conflicts for cross-pillar conflict resolution, scenario_cards for the scenario map, "
        "preferred_expression and best_expressions for the preferred trade/readiness, "
        "required_checks for precise triggers or confirmations, rejected_ideas for strategy "
        "selection rejects, and rendering.disclaimer/final text for research-only framing.\n"
        "For preferred_expression, best_expressions, and rejected_ideas idea_id fields, use "
        "a supplied candidate_structures idea_id when referencing a deterministic candidate. "
        "When referencing a strategy family from Strategy Selection Logic instead, use only "
        f"one canonical strategy id from {sorted(STRATEGY_FAMILY_IDS)}. For strategy-family "
        "preferred_expression or best_expressions entries, set status_observed to "
        "strategy_review and risk_flags_observed to [].\n"
        f"Put only one final rating letter from {list(FINAL_RATING_VALUES)} in "
        "headline.conviction; put the explanatory rating text in "
        "headline.conviction_label.\n"
        "Set guardrails.no_executable_recommendations=true when recommendations remain "
        "research-only, non-imperative, and not order-placement instructions; this field does "
        "not prohibit research recommendations.\n"
        "Keep the result compact enough for the AI Analysis card while preserving the "
        "decision, conflict resolution, scenario map, preferred structure, and final rating "
        "requested above.\n"
        "Emit only JSON conforming to the TradeInsightAiOutcome schema.\n\n"
        "Payload:\n"
        f"{payload_json}\n"
    )


def _coerce_strict_schema(node: Any) -> Any:
    if isinstance(node, dict):
        coerced = {key: _coerce_strict_schema(value) for key, value in node.items()}
        if "properties" in coerced and isinstance(coerced["properties"], dict):
            coerced["additionalProperties"] = False
            coerced["required"] = list(coerced["properties"].keys())
        return coerced
    if isinstance(node, list):
        return [_coerce_strict_schema(item) for item in node]
    return node


def trade_insights_ai_output_schema() -> dict[str, Any]:
    schema = _coerce_strict_schema(TradeInsightAiOutcome.model_json_schema())
    schema["properties"]["schema_version"]["const"] = PROMPT_VERSION
    schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"]["enum"] = (
        list(FINAL_RATING_VALUES)
    )
    return schema


_IMPERATIVE_PHRASES = (
    "buy now",
    "sell now",
    "enter now",
    "execute this trade",
    "place this order",
    "size this position",
)


def _candidate_map(deterministic_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("idea_id")): candidate
        for candidate in deterministic_payload.get("candidate_structures") or []
        if candidate.get("idea_id") is not None
    }


def _known_idea_id(idea_id: str, candidates: dict[str, dict[str, Any]]) -> bool:
    return idea_id in candidates or idea_id in STRATEGY_FAMILY_IDS


_PATH_PART_INDEX_RE = re.compile(r"\[(?:\d+)?\]")


def _path_family_exists(path: str, deterministic_payload: dict[str, Any]) -> bool:
    parts = [_PATH_PART_INDEX_RE.sub("", p) for p in path.split(".") if p]
    if not parts:
        return False
    node: Any = deterministic_payload
    for part in parts:
        while isinstance(node, list):
            if not node or not isinstance(node[0], dict):
                return False
            node = node[0]
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _mentions_missing_data(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    text = " ".join(str(item.get(key) or "") for key in ("label", "value", "note"))
    return "missing" in text.lower() or "unavailable" in text.lower()


def _missing_data_mentions(outcome: TradeInsightAiOutcome, token: str) -> bool:
    needle = token.lower()
    return any(needle in item.lower() for item in outcome.missing_data)


def _validate_source_path_item(
    item: Any,
    deterministic_payload: dict[str, Any],
    outcome: TradeInsightAiOutcome,
) -> None:
    source_path = getattr(item, "source_path", None)
    item_payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
    if not source_path:
        if _mentions_missing_data(item_payload):
            return
        raise ValueError(
            "source_path is required unless the item is a missing-data note"
        )
    lowered = source_path.lower()
    for unavailable in ("charm", "vanna", "short_interest"):
        if unavailable in lowered and not _missing_data_mentions(outcome, unavailable):
            raise ValueError(f"unavailable source field referenced: {source_path}")
    if not _path_family_exists(source_path, deterministic_payload):
        raise ValueError(f"source_path prefix does not exist: {source_path}")


def _reject_imperative_text(outcome: TradeInsightAiOutcome) -> None:
    checked = [
        outcome.headline.stance_label,
        outcome.preferred_expression.title if outcome.preferred_expression else "",
        outcome.preferred_expression.subtitle if outcome.preferred_expression else "",
    ]
    for text in checked:
        lowered = text.strip().lower()
        if any(lowered.startswith(phrase) for phrase in _IMPERATIVE_PHRASES):
            raise ValueError(f"imperative trade instruction rejected: {text}")

    free_text = json.dumps(outcome.model_dump(mode="json"), default=str)
    for phrase in _IMPERATIVE_PHRASES:
        if re.search(rf"(^|[.!?]\s+){re.escape(phrase)}\b", free_text, re.I):
            raise ValueError(f"imperative trade instruction rejected: {phrase}")


def validate_trade_insights_ai_outcome(
    outcome: dict[str, Any] | TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
) -> TradeInsightAiOutcome:
    """Validate model output against immutable deterministic inputs."""

    parsed = (
        outcome
        if isinstance(outcome, TradeInsightAiOutcome)
        else TradeInsightAiOutcome.model_validate(outcome)
    )
    expected_produced_at = _iso_z(produced_at)
    if _iso_z(parsed.analysis_produced_at) != expected_produced_at:
        raise ValueError(
            "analysis_produced_at does not match worker-produced timestamp"
        )
    if parsed.schema_version != PROMPT_VERSION:
        raise ValueError("schema_version does not match prompt version")
    if parsed.headline.conviction not in FINAL_RATING_VALUES:
        raise ValueError("final rating must be one of A, B, C, D, or F")
    if parsed.ticker != deterministic_payload.get("ticker"):
        raise ValueError("ticker does not match deterministic payload")
    if parsed.snapshot.run_id != deterministic_payload.get("run_id"):
        raise ValueError("snapshot.run_id does not match deterministic payload")
    if parsed.snapshot.trade_insights_input_hash != deterministic_payload.get(
        "trade_insights_input_hash"
    ):
        raise ValueError(
            "trade_insights_input_hash does not match deterministic payload"
        )
    expected_hash = hash_trade_insights_ai_analysis_input(deterministic_payload)
    if parsed.snapshot.analysis_input_hash != expected_hash:
        raise ValueError("analysis_input_hash does not match deterministic payload")

    candidates = _candidate_map(deterministic_payload)
    for item in [*parsed.best_expressions, *parsed.rejected_ideas]:
        if not _known_idea_id(item.idea_id, candidates):
            raise ValueError(f"unknown idea_id referenced: {item.idea_id}")
    if (
        parsed.preferred_expression is not None
        and not _known_idea_id(parsed.preferred_expression.idea_id, candidates)
    ):
        raise ValueError(
            f"unknown idea_id referenced: {parsed.preferred_expression.idea_id}"
        )

    echo_items = list(parsed.best_expressions)
    if parsed.preferred_expression is not None:
        echo_items.append(parsed.preferred_expression)
    for item in echo_items:
        if item.idea_id in STRATEGY_FAMILY_IDS:
            if item.status_observed != "strategy_review":
                raise ValueError(
                    f"strategy status_observed must be strategy_review for {item.idea_id}"
                )
            if item.risk_flags_observed != []:
                raise ValueError(
                    f"strategy risk_flags_observed must be empty for {item.idea_id}"
                )
            continue
        candidate = candidates[item.idea_id]
        if item.status_observed != candidate.get("status"):
            raise ValueError(f"status_observed changed for idea_id {item.idea_id}")
        if item.risk_flags_observed != list(candidate.get("risk_flags") or []):
            raise ValueError(f"risk_flags_observed changed for idea_id {item.idea_id}")

    if not (
        parsed.guardrails.statuses_preserved
        and parsed.guardrails.risk_flags_preserved
        and parsed.guardrails.no_executable_recommendations
    ):
        raise ValueError("guardrails must all be true")

    for card in parsed.metric_cards:
        _validate_source_path_item(card, deterministic_payload, parsed)
    for section in (
        parsed.section_cards.market_structure,
        parsed.section_cards.volatility,
        parsed.section_cards.flow_positioning,
    ):
        for highlight in section.highlights:
            _validate_source_path_item(highlight, deterministic_payload, parsed)
        for level in section.levels:
            _validate_source_path_item(level, deterministic_payload, parsed)

    _reject_imperative_text(parsed)
    return parsed


def render_trade_insights_ai_markdown(outcome: TradeInsightAiOutcome) -> str:
    """Render compact Markdown from validated structured output."""

    lines: list[str] = [
        f"# {outcome.ticker} - {outcome.headline.stance_label}",
        outcome.headline.title,
        "",
        f"Produced: {_iso_z(outcome.analysis_produced_at)}",
        f"Score: {outcome.headline.score}/{outcome.headline.score_scale}",
        f"Conviction: {outcome.headline.conviction} - {outcome.headline.conviction_label}",
        f"Top reason: {outcome.headline.top_reason}",
        f"Primary risk: {outcome.headline.primary_risk}",
        f"Watch: {outcome.headline.watch_trigger}",
        "",
        "## Metrics",
    ]
    for card in outcome.metric_cards:
        note = f" - {card.note}" if card.note else ""
        lines.append(f"- {card.label}: {card.value}{note}")

    lines.extend(["", "## Scenarios"])
    for card in outcome.scenario_cards:
        lines.append(f"- {card.case}: {card.title} - {card.description}")

    lines.extend(["", "## Sections"])
    for section in (
        outcome.section_cards.market_structure,
        outcome.section_cards.volatility,
        outcome.section_cards.flow_positioning,
    ):
        score = (
            f" ({section.score}/{section.max_score})"
            if section.score is not None and section.max_score is not None
            else ""
        )
        lines.append(f"### {section.title}{score}")
        lines.append(section.summary)
        for highlight in section.highlights:
            note = f" - {highlight.note}" if highlight.note else ""
            lines.append(f"- {highlight.label}: {highlight.value}{note}")
        for level in section.levels:
            note = f" - {level.note}" if level.note else ""
            lines.append(f"- {level.kind}: {level.price} {level.value}{note}")

    if outcome.vrp_assessment is not None:
        lines.extend(["", f"## {outcome.vrp_assessment.title}"])
        lines.append(outcome.vrp_assessment.summary)
        for metric in outcome.vrp_assessment.metrics:
            lines.append(f"- {metric.label}: {metric.value}")
        lines.append(f"Reason: {outcome.vrp_assessment.reason}")

    if outcome.preferred_expression is not None:
        expression = outcome.preferred_expression
        lines.extend(["", f"## {expression.title}"])
        if expression.subtitle:
            lines.append(expression.subtitle)
        lines.append(f"Why: {expression.why}")
        lines.append(f"Status: {expression.status_observed}")
        lines.append(
            f"Risk flags: {', '.join(expression.risk_flags_observed) or 'none'}"
        )
        for note in expression.management_notes:
            lines.append(f"- {note}")

    if outcome.conflicts:
        lines.extend(["", "## Conflicts"])
        for item in outcome.conflicts:
            lines.append(f"- {item.severity}: {item.description}")

    if outcome.required_checks:
        lines.extend(["", "## Required Checks"])
        for item in outcome.required_checks:
            blocker = "blocks sizing" if item.blocks_sizing else "informational"
            lines.append(f"- {item.check}: {item.reason} ({blocker})")

    if outcome.rejected_ideas:
        lines.extend(["", "## Rejected Ideas"])
        for item in outcome.rejected_ideas:
            lines.append(f"- {item.idea_id} {item.structure}: {item.reason}")

    if outcome.missing_data:
        lines.extend(["", "## Missing Data"])
        for item in outcome.missing_data:
            lines.append(f"- {item}")

    lines.extend(["", outcome.rendering.disclaimer])
    return "\n".join(lines)
