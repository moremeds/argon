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

PROMPT_VERSION = "trade-insights-ai-v4"
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
PREFERRED_STRATEGY_FAMILY_IDS = STRATEGY_FAMILY_IDS - {"short_strangle"}
# Subset valid as `preferred_expression` / `best_expressions` at the 1-2 week
# swing horizon. Excludes:
#   long_stock         — not a swing options structure in this product
#   covered_call       — 30-45d income trade, requires existing stock
#   cash_secured_put   — same, 30-45d income posture
#   short_strangle     — undefined-risk, blocked by safety override
# Rejected-ideas slots may still reference the full STRATEGY_FAMILY_IDS so the
# model can explain why an excluded family is the wrong tool at this horizon.
SWING_STRATEGY_FAMILY_IDS = frozenset(
    {
        "long_call",
        "call_debit_spread",
        "long_put",
        "put_debit_spread",
        "put_credit_spread",
        "iron_condor",
        "calendar_spread",
        "no_trade",
    }
)
FINAL_RATING_VALUES = ("A", "B", "C", "D", "F")

MARKET_INTELLIGENCE_PROMPT = """You are an institutional options strategist analyzing one stock for a 1-2 week SWING HOLD entry.

Time horizon (FIXED, not negotiable):
- The trade is HELD 5-10 trading sessions (1-2 calendar weeks). The trade is
  NOT held to expiry.
- Entry-expiry DTE MUST be 28-45 (preferred) or 21-60 (allowed). This leaves
  7-46 DTE remaining at exit. Do NOT pick an expiry that lands inside the
  5-10 session hold window — exiting at 0-7 DTE puts the trade at peak gamma
  and theta crush.
- Calendars: short (near) leg 21-45 DTE; long (far) leg 45-90 DTE.
- Reject any candidate with entry DTE < 21 or > 60 as `horizon_mismatch`,
  even if it appears in the supplied candidate_structures list.
- Triggers and invalidations are stated in daily-close terms or 2-session
  confirmations, never intraday wicks or single-session tape patterns.

Evidence weighting at this horizon:

PRIMARY (the call hangs on these):
- Dealer regime label + gamma/vanna/charm sub-scores
  (tabs.market_structure.dealer_regime.{label, gamma_score, vanna_score, charm_score, headline, subtitle})
- Per-expiry vanna regime + vanna_flip, charm_pin_strike + charm_imbalance_pct + charm_signal_quality
  for rows where 21 <= dte <= 60 only (the entry-expiry window)
  (tabs.market_structure.exposures_summary[])
- GEX flip vs spot, call wall, put wall, max magnet, max accel
  (tabs.market_structure.market_structure_levels)
- IV vs RV at the 28-45d horizon, term structure shape across 21-60 DTE
  (tabs.volatility.{header, term_structure})
- 90d GEX history extreme vs current — is today at a historically mean-reverting level?
- Earnings in window — HARD VETO if next_earnings_date falls inside the 5-10
  session hold (NOT the full DTE-to-expiry), unless the trade is explicitly
  an earnings IV-crush play (see Earnings filter below).

SECONDARY (confirms or contradicts, never the primary thesis):
- Multi-day OI build (tabs.positioning.oi_change_top), persistent top alerts
- Dark pool notional trend, short interest / borrow fee
- Skew (sets cost of bullish vs bearish bets)

CONTEXT only (do NOT base the call on these at swing-hold horizon):
- 0DTE GEX and 0DTE share (tabs.volatility.dealer_regime_header.{odte_net_gex, odte_share_pct})
  — same-day dealer hedging, not 1-2 week direction
- Any candidate_structures row whose preferred entry expiry is < 21 DTE —
  reject as `horizon_mismatch` (exit would land in theta-crush zone)
- Intraday tape direction, single-session bid/ask premium tilts

Hard rules:
- Do not invent data. If a field is missing, say "Missing / not provided."
- Pick a winner. If pillars conflict, name the winning pillar for the 1-2 week swing-hold horizon and downgrade conviction by one letter — do not default to no-trade unless >=2 of the 4 pillars are missing data.
- Recommendations are research-only. No order placement, no position sizing in dollars, no imperative trade instructions.
- Do not use the words "mixed", "unclear", or "monitor closely" in the Call section without a specific price level and a time window in the same sentence.

Input:

Ticker: {{ticker}}
As-of date: {{as_of_date}}
Spot: {{spot}}

Now produce the report using EXACTLY the structure below. Do not add sections. Do not repeat tables.

# {{ticker}} — {one-line decision: bias + structure + entry-expiry DTE in [21, 60], to hold 1-2 weeks}

## Call

| Field | Value |
|---|---|
| Bias | bullish / bearish / range / no_trade |
| Vol overlay | long_vol / short_vol / neutral |
| Conviction | A / B / C / D / F (one letter — see rating ladder below) |
| Preferred entry expiry | YYYY-MM-DD with DTE in [21, 60] — preferred [28, 45]. This is ENTRY DTE; the trade exits at +5 to +10 sessions, not at expiry. |
| Preferred structure | one of SWING_STRATEGY_FAMILY_IDS |
| Trigger | "two daily closes above/below X with confirming Y" — daily-close terms |
| Invalidation | "daily close above/below X" — daily-close terms |
| Target level | named level from market_structure_levels (call_wall / put_wall / max_magnet / max_accel / gex_flip) |
| Time stop | "close at mid after 7-10 trading sessions if neither trigger nor invalidation fires" |

## Why (<=120 words)

Three sentences max, one per supporting pillar. Cite primary evidence by source path the first time a claim appears. Name the single biggest conflicting piece of evidence in one clause — not a paragraph.

## Expiry Selection (mandatory)

| Field | Value |
|---|---|
| Preferred entry expiry | YYYY-MM-DD (must appear in tabs.volatility.term_structure with 21 <= dte <= 60; prefer 28 <= dte <= 45) |
| Entry DTE | integer in [21, 60] (preferred [28, 45]) |
| Why this expiry | one sentence citing IV level vs adjacent expiries, vanna regime in the entry-expiry window, or charm window position. State explicitly that this DTE leaves comfortable premium after the 5-10 session hold. |
| Alternative | second expiry in 28-45 DTE band, or "none — only one swing-hold expiry has acceptable liquidity" |

## Scenarios (3 rows, probabilities sum to 100%)

| Scenario | Probability | Trigger (daily close) | Level | Best expression |
|---|---:|---|---|---|
| upside | % | | named level | SWING_STRATEGY_FAMILY_IDS member |
| base | % | | named level | SWING_STRATEGY_FAMILY_IDS member |
| downside | % | | named level | SWING_STRATEGY_FAMILY_IDS member |

## Conflicts (cap = 2; severities high or medium only)

| Severity | One-sentence conflict, citing the pillars in tension |
|---|---|

State which pillar wins for the 1-2 week swing-hold horizon and why, in one sentence.

## Required Checks (cap = 2)

| Check | What confirms |
|---|---|

Each row must be either pre-entry (resolvable before the trigger fires) or in-trade (a monitor with an action). Do not list more than 2.

## Rejected Ideas (min 3, max 5)

| Strategy | Why rejected at 1-2 week swing-hold horizon |
|---|---|

Use canonical strategy ids from STRATEGY_FAMILY_IDS. At least one rejection must explicitly cite horizon mismatch (e.g. "long_stock is not a swing options structure in this product", or "<14 DTE candidate exits at peak gamma/theta") or the safety override ("short_strangle: undefined-risk short-vol, blocked by project policy").

## Earnings filter

If tabs.positioning.next_earnings_date falls inside the 5-10 session HOLD window (NOT the full entry-DTE-to-expiry), choose ONE:
- (a) Reject the candidate as `event_risk_in_window`, recommend `no_trade` or a watchlist entry triggering post-earnings. (Default.)
- (b) Accept ONLY if the trade is explicitly an earnings IV-crush play AND term structure shows clear front-expiry crush opportunity. Tag risk_flags_observed with ["earnings_in_window", "event_iv_crush_thesis"] and justify in headline.subtitle. Note that an earnings IV-crush play typically wants front-expiry (sub-21 DTE) entry — which conflicts with the swing-hold DTE rule above. If you take this path, state explicitly that you are overriding the standard swing-hold horizon for the event-only crush window.

Rating ladder (single letter in headline.conviction; one-clause label in headline.conviction_label):
- A: Actionable, high conviction (3 of 4 pillars aligned, no missing primary evidence)
- B: Actionable, small size (pillars aligned with one medium conflict, or one primary field missing)
- C: Watchlist (trigger not yet fired, primary thesis present but unconfirmed)
- D: No trade (pillars conflict at this horizon and no clean winner)
- F: Data insufficient (>=2 primary fields missing)

Confidence (headline.score, 0-100 integer; headline.score_scale = 100):
- 85-100: 4 of 4 pillars (market structure, volatility, flow, positioning) aligned, no missing primary fields. Conviction A territory.
- 70-84:  3 of 4 pillars aligned with one medium conflict, or 4 aligned with one primary field missing. Conviction A/B.
- 55-69:  2 of 4 pillars aligned with the dominant pillar winning clearly. Conviction B/C.
- 40-54:  Pillars conflict but a winner can still be named for the 1-2 week swing-hold horizon. Conviction C.
- 20-39:  No clean winner, or 2+ primary fields missing. Conviction D.
- 0-19:   Data insufficient — primary evidence absent. Conviction F.
Set headline.score honestly against this rubric. Do NOT default to 0; if you can name a dominant pillar and a structure, you can score at least 40.

Do not end with vague commentary. Do not repeat any table. Do not use the word "monitor" without a level and a session count."""

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


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce to Decimal or return None. Never silently returns 0 on bad input —
    callers must explicitly opt in via _to_decimal_or_zero when 0 is correct."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:
        _ = repr(exc)  # CI Guardrail 2: surface exception repr even when swallowed.
        return None


def _to_decimal_or_zero(value: Any) -> Decimal:
    """Coerce to Decimal, falling back to Decimal(0) for None / unparseable
    input. Use this AT CALL SITES where the existing semantics treat missing
    data as zero (sums, abs-distance sort keys whose missing-data behavior is
    'rank as small/center'). Documenting the choice at the call site makes
    the silent-zero coercion explicit instead of hidden in the helper."""
    coerced = _to_decimal(value)
    return coerced if coerced is not None else Decimal(0)


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
        key=lambda row: abs(_to_decimal_or_zero(row.get("net_gex"))),
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
        return sorted(points, key=lambda row: _to_decimal_or_zero(row.get("strike")))
    sorted_points = sorted(
        points, key=lambda row: _to_decimal_or_zero(row.get("strike"))
    )
    if limit <= 1:
        return sorted_points[:limit]
    step = (len(sorted_points) - 1) / (limit - 1)
    indexes = sorted({round(i * step) for i in range(limit)})
    return [sorted_points[i] for i in indexes[:limit]]


def _combined_chain_interest(row: dict[str, Any]) -> Decimal:
    keys = ("call_volume", "put_volume", "call_open_interest", "put_open_interest")
    return sum((_to_decimal_or_zero(row.get(key)) for key in keys), Decimal("0"))


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
        key=lambda row: abs(
            _to_decimal_or_zero(row.get("strike")) - _to_decimal_or_zero(spot)
        ),
    )[:20]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*near_spot, *top]:
        by_key[(str(row.get("expiry")), str(row.get("strike")))] = row
    return list(by_key.values())[:limit]


def _prune_strike_exposures(
    rows: list[dict[str, Any]],
    *,
    spot: Any,
    expiry_limit: int = 4,
    strikes_per_side: int = 10,
) -> list[dict[str, Any]]:
    """Cap vanna/charm per-strike rows: keep the front `expiry_limit` expiries
    inside the swing window and, within each expiry, ±`strikes_per_side` around
    spot. Order is preserved by (expiry, strike)."""
    if not rows:
        return []
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_expiry.setdefault(str(row.get("expiry")), []).append(row)
    expiries = sorted(by_expiry.keys())[:expiry_limit]
    if not expiries:
        return []
    spot_dec = _to_decimal_or_zero(spot) if spot is not None else None
    pruned: list[dict[str, Any]] = []
    for expiry in expiries:
        rows_for_expiry = by_expiry[expiry]
        if spot_dec is None:
            kept = rows_for_expiry
        else:
            kept = sorted(
                rows_for_expiry,
                key=lambda row: abs(_to_decimal_or_zero(row.get("strike")) - spot_dec),
            )[: strikes_per_side * 2]
        pruned.extend(
            sorted(kept, key=lambda row: _to_decimal_or_zero(row.get("strike")))
        )
    return pruned


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

    dealer_regime = stock_report_payload.get("dealer_regime") or {}
    exposures_summary = _sorted_front(
        list(stock_report_payload.get("exposures_summary") or []),
        6,
    )
    strike_exposures = _prune_strike_exposures(
        list(stock_report_payload.get("strike_exposures") or []),
        spot=spot,
    )
    if not dealer_regime:
        missing_data.append("tabs.market_structure.dealer_regime is empty")
    if not exposures_summary:
        missing_data.append("tabs.market_structure.exposures_summary is empty")
    # Compact mirror so the Volatility tab consumer can quote regime sub-bars
    # without cross-tab path-walking that has historically caused validator
    # rejections (source_path prefix does not exist...).
    dealer_regime_header = (
        {
            "label": dealer_regime.get("label"),
            "score": dealer_regime.get("score"),
            "gamma_score": dealer_regime.get("gamma_score"),
            "vanna_score": dealer_regime.get("vanna_score"),
            "charm_score": dealer_regime.get("charm_score"),
            "odte_net_gex": dealer_regime.get("odte_net_gex"),
            "odte_share_pct": dealer_regime.get("odte_share_pct"),
            "headline": dealer_regime.get("headline"),
            "subtitle": dealer_regime.get("subtitle"),
        }
        if dealer_regime
        else {}
    )

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
    next_earnings_date = stock_report_payload.get("next_earnings_date")
    event_data_known = next_earnings_date is not None
    if not event_data_known:
        missing_data.append("tabs.positioning.next_earnings_date is empty")

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
                # PR #61: dealer-regime summary (label, gamma/vanna/charm
                # sub-scores, 0DTE GEX, headline narrative). Primary evidence
                # at the 1-2 week swing-hold horizon.
                "dealer_regime": dealer_regime,
                # PR #60: per-expiry vanna + charm derivations. Front 6
                # expiries — caller filters to the swing window when reading.
                "exposures_summary": exposures_summary,
                # PR #60: per-strike call/put vanna+charm. Pruned to front 4
                # expiries × ±10 strikes around spot.
                "strike_exposures": strike_exposures,
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
                # Mirror of dealer_regime so the Vol-regime panel consumer can
                # cite Γ/V/C sub-bars and 0DTE share without crossing tabs.
                "dealer_regime_header": dealer_regime_header,
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
                "next_earnings_date": next_earnings_date,
            },
            "trade_insights": trade_insights_payload,
        },
        "candidate_structures": trade_candidates,
        "required_before_sizing": list(synthesis.get("required_before_sizing") or []),
        "event_data_known": event_data_known,
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
        "Payload key map: ticker <- ticker; as_of <- tabs.trade_insights.as_of or "
        "analysis_produced_at; spot <- underlying_price or "
        "tabs.market_structure.market_structure.spot; market structure <- "
        "tabs.market_structure (primary keys: tabs.market_structure.dealer_regime, "
        "tabs.market_structure.exposures_summary, tabs.market_structure.strike_exposures, "
        "tabs.market_structure.market_structure_levels, tabs.market_structure.strike_gex_curve); "
        "volatility <- tabs.volatility (including tabs.volatility.dealer_regime_header); "
        "flow <- tabs.flow; positioning <- tabs.positioning.\n"
        "Use analysis_produced_at exactly as supplied; do not invent a different production time.\n"
        f"schema_version MUST be exactly the string {PROMPT_VERSION!r} (do not abbreviate or "
        "reformat). This is also stamped as a JSON-schema const.\n"
        "Source-path rule (HARD): every source_path in the outcome must resolve to a key path "
        "that exists in the payload. Do not cite synthetic paths such as "
        "tabs.x.y[-1].field or .header.iv unless that exact key exists. If a value is not "
        "in the payload, leave the field out and add a 'Missing / not provided' note to "
        "missing_data instead of inventing a path.\n"
        "Preserve every candidate status, every risk_flags array, and every deterministic "
        "max_loss/max_profit value exactly as supplied.\n"
        "Horizon enforcement (swing HOLD, not swing expiry): every "
        "candidate_structures row whose preferred entry expiry has DTE < 21 or "
        "DTE > 60 must be rejected as horizon_mismatch in rejected_ideas. The "
        "trade is HELD 5-10 trading sessions; entry expiry must leave enough "
        "premium that the exit is not at peak gamma/theta crush. The "
        "deterministic candidate list is already filtered to the 21-60 DTE "
        "swing-hold window (preferred 28-45) by the upstream assembler; if no "
        "swing-hold candidates exist, set preferred_expression to a no_trade "
        "strategy-family entry rather than recommending an out-of-horizon "
        "candidate.\n"
        "Do not defer solely because a deterministic candidate status is needs_check; give "
        "a research-only recommendation when the swing-hold evidence supports one and "
        "put remaining checks into the trigger, risk, watchlist, or readiness language.\n"
        "Project safety override: do not recommend naked short options or undefined-risk "
        "short-vol structures. If the prompt's strategy list includes one, reject it unless "
        "converted to a defined-risk alternative such as an iron condor.\n"
        "Avoid order placement, position sizing in dollars, personalized financial advice, "
        "and imperative trade instructions.\n"
        "Outcome field mapping: headline + dominant_read <- Call section; section_cards <- "
        "Why paragraph (one card per supporting pillar, max 3); conflicts <- Conflicts table "
        "(cap 2); scenario_cards <- Scenarios table (exactly 3, probabilities sum to 100); "
        "preferred_expression + best_expressions <- Call.preferred_structure / Expiry "
        "Selection; required_checks <- Required Checks table (cap 2); rejected_ideas <- "
        "Rejected Ideas table (min 3, max 5); rendering.disclaimer/final <- research-only "
        "framing only.\n"
        "idea_id rules (HARD): preferred_expression.idea_id, every best_expressions[].idea_id, "
        "and every rejected_ideas[].idea_id MUST be either (a) the idea_id of a row in the "
        "supplied candidate_structures array, or (b) a canonical strategy family id. Never "
        "free text. For preferred_expression and best_expressions at this horizon, the "
        f"strategy-family option is restricted to {sorted(SWING_STRATEGY_FAMILY_IDS)}. "
        "rejected_ideas may reference any canonical strategy id from "
        f"{sorted(STRATEGY_FAMILY_IDS)} so an out-of-horizon family can be explicitly rejected.\n"
        "For strategy-family preferred_expression / best_expressions entries, set "
        "status_observed to 'strategy_review' and risk_flags_observed to [].\n"
        f"headline.conviction MUST be a single letter from {list(FINAL_RATING_VALUES)} "
        "(rating ladder in the prompt above). headline.conviction_label holds the "
        "one-clause explanation. headline.score is the swing-hold confidence "
        "percentage (integer 0-100, scored against the Confidence rubric in the prompt). "
        "headline.score_scale must be 100. Do not leave score=0 unless data is genuinely "
        "insufficient (Conviction F); a real dominant-pillar read scores at least 40.\n"
        "Set guardrails.no_executable_recommendations=true when recommendations remain "
        "research-only, non-imperative, and not order-placement instructions; this flag does "
        "not prohibit research-only recommendations.\n"
        "Keep the markdown output (rendering.markdown if emitted) under ~3 KB / ~400 words. "
        "Do not repeat any table. Do not list more than 2 required_checks or more than 2 "
        "conflicts. Do not emit a Strategy Selection 12-row grid — only rejected_ideas "
        "(min 3, max 5).\n"
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


def trade_insights_ai_output_schema(*, strict: bool = True) -> dict[str, Any]:
    """Produce the JSON schema for TradeInsightAiOutcome.

    `strict=True` (default, used for Codex): forces every nested property to be
    required and `additionalProperties: false` everywhere. Codex's structured
    output mode handles this cleanly.

    `strict=False` (used for Claude): keeps only the required set Pydantic
    naturally declares (i.e. non-Optional fields). Claude's StructuredOutput
    tool silently falls back to freeform JSON when the schema is too strict at
    every level, so we trade some validation surface for adherence.
    """
    raw = TradeInsightAiOutcome.model_json_schema()
    schema = _coerce_strict_schema(raw) if strict else raw
    schema["properties"]["schema_version"]["const"] = PROMPT_VERSION
    schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"]["enum"] = (
        list(FINAL_RATING_VALUES)
    )
    return schema


_HEADLINE_VALID_STANCES = ("bullish", "bearish", "neutral", "mixed", "wait")
_HEADLINE_STANCE_FALLBACK = "mixed"
_CONVICTION_FALLBACK = "F"
_PARTIAL_OUTPUT_NOTE = (
    "Provider produced partial output that did not adhere to the strict schema; "
    "missing required fields were synthesized."
)


def _str_or(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _int_or(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_list(value: Any) -> list[str]:
    return [v for v in (_str_or(item, "") for item in _list_or_empty(value)) if v]


def _coerce_metric_card(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    label = _str_or(raw.get("label"), "")
    value = _str_or(raw.get("value"), "")
    if not label and not value:
        return None
    return {
        "label": label or "(unlabeled)",
        "value": value or "(no value)",
        "tone": _str_or(raw.get("tone"), "neutral"),
        "source_path": raw["source_path"]
        if isinstance(raw.get("source_path"), str)
        else None,
        "note": _str_or(raw.get("note"), ""),
    }


def _coerce_scenario_card(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    case_value = raw.get("case")
    if not isinstance(case_value, str) or not case_value:
        return None
    return {
        "case": case_value,
        "tone": _str_or(raw.get("tone"), "neutral"),
        "title": _str_or(raw.get("title"), case_value),
        "description": _str_or(raw.get("description"), ""),
    }


def _coerce_score_breakdown(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    section = _str_or(raw.get("section"), "")
    if not section:
        return None
    return {
        "section": section,
        "score": _int_or(raw.get("score"), 0),
        "max_score": _int_or(raw.get("max_score"), 0),
        "summary": _str_or(raw.get("summary"), ""),
    }


def _coerce_highlight(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    label = _str_or(raw.get("label"), "")
    value = _str_or(raw.get("value"), "")
    if not label and not value:
        return None
    return {
        "label": label or "(unlabeled)",
        "value": value or "(no value)",
        "source_path": raw["source_path"]
        if isinstance(raw.get("source_path"), str)
        else None,
        "note": _str_or(raw.get("note"), ""),
    }


def _coerce_level(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    price = _str_or(raw.get("price"), "")
    kind = _str_or(raw.get("kind"), "")
    if not price and not kind:
        return None
    return {
        "price": price or "(no price)",
        "kind": kind or "level",
        "value": _str_or(raw.get("value"), ""),
        "importance": _str_or(raw.get("importance"), "normal"),
        "source_path": raw["source_path"]
        if isinstance(raw.get("source_path"), str)
        else None,
        "note": _str_or(raw.get("note"), ""),
    }


def _coerce_section_card(raw: Any, default_title: str) -> dict[str, Any]:
    data = _dict_or_empty(raw)
    return {
        "title": _str_or(data.get("title"), default_title),
        "score": _opt_int(data.get("score")),
        "max_score": _opt_int(data.get("max_score")),
        "summary": _str_or(data.get("summary"), "(no summary produced)"),
        "highlights": [
            item
            for item in (
                _coerce_highlight(h) for h in _list_or_empty(data.get("highlights"))
            )
            if item is not None
        ],
        "levels": [
            item
            for item in (
                _coerce_level(level) for level in _list_or_empty(data.get("levels"))
            )
            if item is not None
        ],
        "data_quality": _str_or(data.get("data_quality"), "unknown"),
    }


def _coerce_best_expression(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    idea_id = _str_or(raw.get("idea_id"), "")
    if not idea_id:
        return None
    return {
        "idea_id": idea_id,
        "structure": _str_or(raw.get("structure"), idea_id),
        "role": _str_or(raw.get("role"), ""),
        "why": _str_or(raw.get("why"), ""),
        "caveats": _str_list(raw.get("caveats")),
        "status_observed": _str_or(raw.get("status_observed"), "strategy_review"),
        "risk_flags_observed": _str_list(raw.get("risk_flags_observed")),
    }


def _coerce_conflict(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    description = _str_or(raw.get("description"), "")
    if not description:
        return None
    return {
        "lens": _str_or(raw.get("lens"), "unspecified"),
        "severity": _str_or(raw.get("severity"), "medium"),
        "description": description,
        "affected_idea_ids": _str_list(raw.get("affected_idea_ids")),
    }


def _coerce_required_check(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    check = _str_or(raw.get("check"), "")
    if not check:
        return None
    return {
        "check": check,
        "reason": _str_or(raw.get("reason"), ""),
        "blocks_sizing": bool(raw.get("blocks_sizing", True)),
        "source": _str_or(raw.get("source"), ""),
    }


def _coerce_rejected_idea(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    idea_id = _str_or(raw.get("idea_id"), "")
    if not idea_id:
        return None
    return {
        "idea_id": idea_id,
        "structure": _str_or(raw.get("structure"), idea_id),
        "reason": _str_or(raw.get("reason"), ""),
    }


def _coerce_preferred_expression(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    idea_id = _str_or(raw.get("idea_id"), "")
    if not idea_id:
        return None
    return {
        "idea_id": idea_id,
        "structure": _str_or(raw.get("structure"), idea_id),
        "title": _str_or(raw.get("title"), idea_id),
        "subtitle": _str_or(raw.get("subtitle"), ""),
        "estimated_entry": _str_or(raw.get("estimated_entry"), ""),
        "max_profit_observed": _str_or(raw.get("max_profit_observed"), ""),
        "max_loss_observed": _str_or(raw.get("max_loss_observed"), ""),
        "reward_risk": _str_or(raw.get("reward_risk"), ""),
        "why": _str_or(raw.get("why"), ""),
        "management_notes": _str_list(raw.get("management_notes")),
        "status_observed": _str_or(raw.get("status_observed"), "strategy_review"),
        "risk_flags_observed": _str_list(raw.get("risk_flags_observed")),
    }


def _coerce_vrp_assessment(item: Any) -> dict[str, Any] | None:
    raw = _dict_or_empty(item)
    title = _str_or(raw.get("title"), "")
    summary = _str_or(raw.get("summary"), "")
    if not title and not summary:
        return None
    return {
        "signal": _str_or(raw.get("signal"), "unspecified"),
        "title": title or "VRP",
        "summary": summary,
        "metrics": [
            item
            for item in (
                _coerce_metric_card(m) for m in _list_or_empty(raw.get("metrics"))
            )
            if item is not None
        ],
        "reason": _str_or(raw.get("reason"), ""),
    }


def _coerce_claude_outcome_dict(
    raw: Any,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    expected_analysis_input_hash: str,
) -> dict[str, Any]:
    """Coerce Claude's free-form JSON into a TradeInsightAiOutcome-shaped dict.

    Claude does not reliably adhere to the strict schema even with
    --json-schema and a JSON-only system prompt — see issue #67. This
    helper synthesizes a structurally-valid outcome from whatever Claude
    actually produced:

    * Identity fields (schema_version, ticker, snapshot.*, analysis_produced_at)
      are overwritten with deterministic worker-known values.
    * Missing required scalars get safe placeholders.
    * Unknown keys at every nesting level are dropped (every model uses
      extra="forbid").
    * Invalid Literal values (stance, conviction) are coerced to fallbacks
      that signal partial output.

    The result MUST round-trip through TradeInsightAiOutcome.model_validate.
    Codex stays on the strict path; this is Claude-only.
    """
    data = raw if isinstance(raw, dict) else {}

    headline_raw = _dict_or_empty(data.get("headline"))
    stance_raw = headline_raw.get("stance")
    stance = (
        stance_raw
        if stance_raw in _HEADLINE_VALID_STANCES
        else _HEADLINE_STANCE_FALLBACK
    )
    conviction_raw = headline_raw.get("conviction")
    conviction = (
        conviction_raw
        if isinstance(conviction_raw, str) and conviction_raw in FINAL_RATING_VALUES
        else _CONVICTION_FALLBACK
    )

    ticker = _str_or(deterministic_payload.get("ticker"), "TICKER")
    headline = {
        "title": _str_or(headline_raw.get("title"), f"{ticker} — partial output"),
        "stance": stance,
        "stance_label": _str_or(headline_raw.get("stance_label"), "Partial output"),
        "score": _int_or(headline_raw.get("score"), 0),
        "score_scale": _int_or(headline_raw.get("score_scale"), 100),
        "conviction": conviction,
        "conviction_label": _str_or(
            headline_raw.get("conviction_label"), "data insufficient"
        ),
        "top_reason": _str_or(headline_raw.get("top_reason"), _PARTIAL_OUTPUT_NOTE),
        "primary_risk": _str_or(
            headline_raw.get("primary_risk"), "provider schema adherence"
        ),
        "watch_trigger": _str_or(headline_raw.get("watch_trigger"), "re-run analysis"),
    }

    snapshot_raw = _dict_or_empty(data.get("snapshot"))
    data_as_of_raw = snapshot_raw.get("data_as_of") or data.get("data_as_of")
    snapshot = {
        "run_id": deterministic_payload.get("run_id"),
        "trade_insights_input_hash": deterministic_payload.get(
            "trade_insights_input_hash"
        ),
        "analysis_input_hash": expected_analysis_input_hash,
        "data_as_of": data_as_of_raw
        if isinstance(data_as_of_raw, str) and data_as_of_raw
        else None,
        "freshness_label": _str_or(snapshot_raw.get("freshness_label"), "unknown"),
        "source_notes": _str_list(snapshot_raw.get("source_notes")),
    }

    section_cards_raw = _dict_or_empty(data.get("section_cards"))
    section_cards = {
        "market_structure": _coerce_section_card(
            section_cards_raw.get("market_structure"), "Market Structure"
        ),
        "volatility": _coerce_section_card(
            section_cards_raw.get("volatility"), "Volatility"
        ),
        "flow_positioning": _coerce_section_card(
            section_cards_raw.get("flow_positioning"), "Flow & Positioning"
        ),
    }

    dominant_read_raw = _dict_or_empty(data.get("dominant_read"))
    dominant_read = {
        "headline": _str_or(dominant_read_raw.get("headline"), headline["title"]),
        "summary": _str_or(dominant_read_raw.get("summary"), headline["top_reason"]),
        "confidence_commentary": _str_or(
            dominant_read_raw.get("confidence_commentary"),
            "Partial output — confidence not reported by provider.",
        ),
        "data_quality_commentary": _str_or(
            dominant_read_raw.get("data_quality_commentary"),
            _PARTIAL_OUTPUT_NOTE,
        ),
    }

    rendering_raw = _dict_or_empty(data.get("rendering"))
    rendering = {
        "disclaimer": _str_or(
            rendering_raw.get("disclaimer"),
            "Research-only — partial output captured; not order-placement instructions.",
        ),
        "card_order": _str_list(rendering_raw.get("card_order")),
    }

    guardrails_raw = _dict_or_empty(data.get("guardrails"))
    guardrails = {
        "statuses_preserved": bool(guardrails_raw.get("statuses_preserved", True)),
        "risk_flags_preserved": bool(guardrails_raw.get("risk_flags_preserved", True)),
        "no_executable_recommendations": bool(
            guardrails_raw.get("no_executable_recommendations", True)
        ),
    }

    missing_data = _str_list(data.get("missing_data"))
    if any(
        value in (None, "", [])
        for value in (
            headline_raw.get("stance"),
            headline_raw.get("title"),
            data.get("snapshot"),
            data.get("section_cards"),
            data.get("dominant_read"),
        )
    ):
        missing_data = [_PARTIAL_OUTPUT_NOTE, *missing_data]

    coerced: dict[str, Any] = {
        "schema_version": PROMPT_VERSION,
        "analysis_produced_at": _iso_z(produced_at),
        "ticker": ticker,
        "underlying_price": data.get("underlying_price")
        if isinstance(data.get("underlying_price"), str)
        else None,
        "snapshot": snapshot,
        "headline": headline,
        "metric_cards": [
            item
            for item in (
                _coerce_metric_card(m) for m in _list_or_empty(data.get("metric_cards"))
            )
            if item is not None
        ],
        "scenario_cards": [
            item
            for item in (
                _coerce_scenario_card(s)
                for s in _list_or_empty(data.get("scenario_cards"))
            )
            if item is not None
        ],
        "score_breakdown": [
            item
            for item in (
                _coerce_score_breakdown(s)
                for s in _list_or_empty(data.get("score_breakdown"))
            )
            if item is not None
        ],
        "section_cards": section_cards,
        "vrp_assessment": _coerce_vrp_assessment(data.get("vrp_assessment")),
        "preferred_expression": _coerce_preferred_expression(
            data.get("preferred_expression")
        ),
        "dominant_read": dominant_read,
        "best_expressions": [
            item
            for item in (
                _coerce_best_expression(b)
                for b in _list_or_empty(data.get("best_expressions"))
            )
            if item is not None
        ],
        "conflicts": [
            item
            for item in (
                _coerce_conflict(c) for c in _list_or_empty(data.get("conflicts"))
            )
            if item is not None
        ],
        "required_checks": [
            item
            for item in (
                _coerce_required_check(r)
                for r in _list_or_empty(data.get("required_checks"))
            )
            if item is not None
        ],
        "rejected_ideas": [
            item
            for item in (
                _coerce_rejected_idea(r)
                for r in _list_or_empty(data.get("rejected_ideas"))
            )
            if item is not None
        ],
        "missing_data": missing_data,
        "rendering": rendering,
        "guardrails": guardrails,
    }
    return coerced


_IMPERATIVE_PHRASES = (
    "buy now",
    "sell now",
    "enter now",
    "execute this trade",
    "place this order",
    "size this position",
)
_IMPERATIVE_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\byou\s+should\s+(?:buy|sell|enter|open|execute)\b",
        r"\bmust\s+(?:buy|sell|enter|open|execute)\b",
        r"\b(?:take|open)\s+this\s+trade\b",
        r"\b(?:place|send)\s+(?:this|the|an?)\s+order\b",
        r"\bgo\s+(?:long|short)\s+now\b",
    )
)


def _candidate_map(deterministic_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("idea_id")): candidate
        for candidate in deterministic_payload.get("candidate_structures") or []
        if candidate.get("idea_id") is not None
    }


def _known_idea_id(idea_id: str, candidates: dict[str, dict[str, Any]]) -> bool:
    return idea_id in candidates or idea_id in STRATEGY_FAMILY_IDS


_PATH_PART_INDEX_RE = re.compile(r"\[-?\d*\]")
_SOURCE_PATH_ALIASES = (
    (
        "tabs.market_structure.market_structure.stock_history.",
        "tabs.market_structure.stock_history.",
    ),
)


def _canonical_source_path(path: str, deterministic_payload: dict[str, Any]) -> str:
    for invalid_prefix, canonical_prefix in _SOURCE_PATH_ALIASES:
        if not path.startswith(invalid_prefix):
            continue
        candidate = f"{canonical_prefix}{path.removeprefix(invalid_prefix)}"
        if _path_family_exists(candidate, deterministic_payload):
            return candidate
    return path


def _path_family_exists(path: str, deterministic_payload: dict[str, Any]) -> bool:
    parts = [_PATH_PART_INDEX_RE.sub("", p) for p in path.split(".") if p]
    if not parts:
        return False
    return _path_parts_exist(deterministic_payload, parts)


def _path_parts_exist(node: Any, parts: list[str]) -> bool:
    if not parts:
        return True
    if isinstance(node, list):
        if not node:
            return False
        return any(_path_parts_exist(item, parts) for item in node)
    part = parts[0]
    if not isinstance(node, dict) or part not in node:
        return False
    return _path_parts_exist(node[part], parts[1:])


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
    # `vanna` and `charm` used to be unavailable in this product; PR #60 made
    # them first-class fields via exposures_summary + strike_exposures. Allow
    # references provided the path family resolves below. `short_interest` is
    # still indirect — only the `short_data` block is forwarded — so it stays
    # gated on a missing-data acknowledgement.
    if "short_interest" in lowered and not _missing_data_mentions(
        outcome, "short_interest"
    ):
        raise ValueError(f"unavailable source field referenced: {source_path}")
    canonical_source_path = _canonical_source_path(source_path, deterministic_payload)
    if canonical_source_path != source_path:
        item.source_path = canonical_source_path
        source_path = canonical_source_path
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
    for pattern in _IMPERATIVE_PATTERNS:
        if pattern.search(free_text):
            raise ValueError("imperative trade instruction rejected")


def validate_trade_insights_ai_outcome(
    outcome: dict[str, Any] | TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    lenient: bool = False,
) -> TradeInsightAiOutcome:
    """Validate model output against immutable deterministic inputs.

    `lenient=True` (Claude only — see issue #67) pre-processes the raw dict
    through `_coerce_claude_outcome_dict` to capture partial/off-schema output,
    then skips the equality checks that require provider-internal consistency
    (idea_id known-ness, status_observed equality, risk_flags equality,
    source_path family). The imperative-text safety check still runs.
    """

    expected_hash = hash_trade_insights_ai_analysis_input(deterministic_payload)
    if lenient and not isinstance(outcome, TradeInsightAiOutcome):
        outcome = _coerce_claude_outcome_dict(
            outcome,
            deterministic_payload,
            produced_at=produced_at,
            expected_analysis_input_hash=expected_hash,
        )

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
    if parsed.snapshot.analysis_input_hash != expected_hash:
        raise ValueError("analysis_input_hash does not match deterministic payload")

    if not lenient:
        candidates = _candidate_map(deterministic_payload)
        for item in [*parsed.best_expressions, *parsed.rejected_ideas]:
            if not _known_idea_id(item.idea_id, candidates):
                raise ValueError(f"unknown idea_id referenced: {item.idea_id}")
        if parsed.preferred_expression is not None and not _known_idea_id(
            parsed.preferred_expression.idea_id, candidates
        ):
            raise ValueError(
                f"unknown idea_id referenced: {parsed.preferred_expression.idea_id}"
            )

        echo_items = list(parsed.best_expressions)
        if parsed.preferred_expression is not None:
            echo_items.append(parsed.preferred_expression)
        for item in echo_items:
            if item.idea_id in STRATEGY_FAMILY_IDS:
                if item.idea_id not in PREFERRED_STRATEGY_FAMILY_IDS:
                    raise ValueError(
                        f"undefined-risk strategy family cannot be preferred: {item.idea_id}"
                    )
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
                raise ValueError(
                    f"risk_flags_observed changed for idea_id {item.idea_id}"
                )

        for conflict in parsed.conflicts:
            for idea_id in conflict.affected_idea_ids:
                if not _known_idea_id(idea_id, candidates):
                    raise ValueError(f"unknown idea_id referenced: {idea_id}")

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

    # `headline.score` is repurposed as a 0-100 confidence percentage. We
    # render it as "Confidence: N/100", and suppress the line when the model
    # left it blank (0/0) — drives the cosmetic v3 follow-up.
    confidence_line: list[str] = []
    if outcome.headline.score or outcome.headline.score_scale:
        confidence_line.append(
            f"Confidence: {outcome.headline.score}/{outcome.headline.score_scale}"
        )
    lines: list[str] = [
        f"# {outcome.ticker} - {outcome.headline.stance_label}",
        outcome.headline.title,
        "",
        f"Produced: {_iso_z(outcome.analysis_produced_at)}",
        *confidence_line,
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
            # Strip trailing period from `check` so the title — reason join
            # doesn't render as "...fires.: Liquidity must support..." (the
            # model frequently terminates the check phrase with punctuation).
            check_text = item.check.rstrip(". ").rstrip()
            lines.append(f"- {check_text} — {item.reason} ({blocker})")

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
