"""Build the deterministic prompt payload and JSON Schema for Trade Insights AI.

`build_trade_insights_ai_analysis_input` prunes the heavy per-ticker payload
down to the bounded slice the model sees, `hash_trade_insights_ai_analysis_input`
gives a stable content hash for caching/idempotency, and
`trade_insights_ai_output_schema` produces the JSON Schema (strict or lax)
that pins the model output contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from uw_scan.models import TradeInsightAiOutcome

from .prompt_text import (
    CONTRACT_PROMPT,
    DIRECTIONAL_SWING_STRUCTURES,
    FINAL_RATING_VALUES,
    MARKET_INTELLIGENCE_PROMPT,
    PROMPT_VERSION,
    RANGE_INCOME_STRUCTURES,
    STRATEGY_FAMILY_IDS,
)

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


from uw_scan.reports._shared_validation.util import _iso_z  # noqa: F401


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
        f"{CONTRACT_PROMPT}\n\n"
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
        "Horizon enforcement: every candidate_structures row whose preferred entry "
        "expiry has DTE < 14 or DTE > 75 must be rejected as horizon_mismatch in "
        "rejected_ideas. The trade is HELD 5-10 trading sessions; entry expiry "
        "must leave enough premium that the exit is not at peak gamma/theta crush. "
        "The deterministic candidate list is filtered to the 14-75 DTE swing window "
        "by the upstream assembler and tagged with dte_band (momentum=14-30, "
        "standard=31-44, trend=45-75) plus expression_delta (long_delta / "
        "short_delta / neutral) so you can pattern-match candidates to the "
        "directional_bias + dte_band chosen at decision Steps 2 and 5.\n"
        "Anti-pin quality (HARD, v5.1): the anti-pin reclassification "
        "(wall=target, not cap) fires ONLY when AT LEAST 3 of 4 hold — "
        "(1) 3+ consecutive sessions of OI increase at/within one strike of "
        "the relevant wall, (2) net premium tilt > 2x in the directional "
        "direction, (3) repeated ask-side/ascending-fill alerts clustered "
        "near the wall, (4) spot within 1.5% of the wall AND no two-session "
        "failed close. In headline.top_reason or dominant_read.summary, cite "
        "which sub-conditions hold (e.g. 'anti-pin satisfied 3/4 — OI build, "
        "premium tilt, spot proximity; alert cluster absent'). If only 2 of "
        "4 hold, cap headline.conviction at C.\n"
        "Anti-pin SCOPE (HARD, v5.2): the conviction cap and the wall=target "
        "reclassification apply ONLY when anti_pin.invoked=true (anti-pin is "
        "the primary thesis). For structural-break theses (price already "
        "closed through the wall) or trend-continuation theses, anti-pin "
        "scoring is informational — set anti_pin.invoked=false and do NOT "
        "use a low score as a reason to cap conviction.\n"
        "Thesis archetype (HARD, v5.2): headline.thesis_archetype MUST be "
        "one of ['resistance_rejection','support_breakdown','breakout_"
        "continuation','pin_no_trade','data_insufficient']. The archetype "
        "must agree with underlying_path: resistance_rejection ↔ "
        "bearish_rejection, support_breakdown ↔ downside_break, "
        "breakout_continuation ↔ bullish_continuation, pin_no_trade ↔ "
        "pinned_no_directional_entry, data_insufficient ↔ data_insufficient. "
        "In top_reason, cite the specific completed daily close session "
        "that justifies the archetype.\n"
        "ACTIVE trigger evidence (HARD, v5.2): headline.entry_state=ACTIVE "
        "is allowed ONLY when the payload contains a COMPLETED daily close "
        "that satisfies the trigger. Populate the trigger_evidence block "
        "with the proving close. If the latest completed close does NOT "
        "satisfy the trigger, you MUST emit entry_state=CONDITIONAL — "
        "intraday spot is NOT sufficient. The validator will reject "
        "entry_state=ACTIVE when trigger_evidence.trigger_fired=false.\n"
        "Trigger components (HARD, v5.3): emit thesis_trigger, "
        "entry_trigger, and invalidation as TOP-LEVEL TriggerComponent "
        "blocks on the outcome. Each has {level, meaning, fired, "
        "evidence_close, evidence_date, source_path}. thesis_trigger is "
        "the level that validates the spatial archetype (broken put_wall "
        "for support_breakdown, broken call_wall for "
        "breakout_continuation). entry_trigger is the level that signals "
        "the actual trade entry — often the long-leg strike. "
        "invalidation is the level that kills the thesis (reclaim of "
        "broken support for SHORT_DELTA, close back below the breakout "
        "base for LONG_DELTA). For thesis/entry, fired=true requires a "
        "COMPLETED daily close from tabs.market_structure.stock_history "
        "that crossed `level` in the relevant direction; intraday spot "
        "is NOT sufficient. The two triggers MAY share the same level "
        "(e.g. NVDA's 220 acts as both broken-wall and entry-confirm) "
        "but their `meaning` strings MUST differ.\n"
        "ENTRY_STATE derivation (HARD, v5.3; mechanical): entry_state = "
        "ACTIVE iff thesis_trigger.fired AND entry_trigger.fired AND NOT "
        "invalidation.fired. entry_state = CONDITIONAL iff "
        "thesis_trigger.fired AND NOT entry_trigger.fired (or neither "
        "fired but the setup is otherwise valid). entry_state = "
        "NO_ENTRY iff invalidation.fired OR directional_bias=WAIT. The "
        "validator enforces this truth table — emitting ACTIVE without "
        "both triggers fired is rejected.\n"
        "Explicit option legs (HARD, v5.3): preferred_expression.legs is "
        "an array of option legs each {option_type:'call'|'put', "
        "side:'long'|'short', strike:numeric, expiry:'YYYY-MM-DD'}. "
        "bear_put_spread / put_debit_spread = 2 legs (long put + short "
        "put, long_strike > short_strike, same expiry); bull_call_spread "
        "/ call_debit_spread = 2 legs (long call + short call, "
        "long_strike < short_strike, same expiry); put_credit_spread = "
        "2 legs (short put + long protective put, defined-risk only); "
        "call_credit_spread = mirror; long_call / long_put = 1 leg. "
        "NO NAKED SHORTS — every credit-spread family MUST include the "
        "protective long leg. no_trade / strategy_review may have "
        "legs=[].\n"
        "Legs align with triggers (HARD, v5.3): the long leg's strike "
        "MUST be within 2% of entry_trigger.level OR thesis_trigger.level. "
        "This binds the proposed spread to the trigger state machine.\n"
        "strike_role level type (HARD, v5.2): trigger_level, target_level, "
        "and invalid_level must be NUMERIC price strings ('215', '215.00') "
        "or numbers — NOT dict objects pasted from the payload. The "
        "Pydantic schema will reject anything else.\n"
        "Headline title (v5.2): headline.title must be 10-20 words, naming "
        "directional_bias + structure + trigger level + dte_band. Example: "
        "'NVDA SHORT_DELTA bear_put_spread fires on daily close below 215, "
        "35 DTE standard band.' Do NOT emit 'NVDA AI Analysis' or other "
        "page-title strings — that's a v5.1 failure mode.\n"
        "Minimum reward/risk under CONDITIONAL conviction ≤ C (v5.2): when "
        "entry_state=CONDITIONAL AND headline.conviction in {C, D, F}, "
        "preferred_expression.reward_risk should be >= 1.5 for the trade "
        "to be worth the conditional setup risk. Lower R:R with these "
        "conviction levels often has poor expected value given conditional "
        "setups historically hit-rate below 50%.\n"
        "Project safety override: do not recommend naked short options or "
        "undefined-risk short-vol structures. risk_reversal is excluded from "
        "the directional_swing whitelist because its short put leg is naked; "
        "cite it in rejected_ideas if it would otherwise be a fit.\n"
        "Avoid order placement, position sizing in dollars, personalized financial advice, "
        "and imperative trade instructions.\n"
        "Outcome field mapping: headline (directional_bias, entry_state, "
        "trade_intent, underlying_path, dte_band, stance, conviction, score) + "
        "dominant_read <- Call section; section_cards <- Why paragraph (one card "
        "per pillar — market_structure, volatility, flow_positioning); conflicts "
        "<- Conflicts table (cap 2); scenario_cards <- Scenarios table (exactly "
        "3, probabilities sum to 100); preferred_expression + best_expressions "
        "<- Call.preferred_structure / Expiry Selection; required_checks <- "
        "Required Checks table (cap 2); rejected_ideas <- Rejected Ideas table "
        "(min 3, max 5); rendering.disclaimer/final <- research-only framing only.\n"
        "Derive headline.stance from headline.directional_bias for "
        "UI/markdown display: LONG_DELTA -> 'bullish', SHORT_DELTA -> 'bearish', "
        "WAIT -> 'wait'. (stance is the legacy display Literal; directional_bias "
        "is the actual gate.)\n"
        "idea_id rules (HARD): preferred_expression.idea_id, every "
        "best_expressions[].idea_id, and every rejected_ideas[].idea_id MUST be "
        "either (a) the idea_id of a row in the supplied candidate_structures "
        "array, or (b) a canonical strategy family id. Never free text. For "
        "preferred_expression and best_expressions when trade_intent="
        "directional_swing, the strategy-family option is restricted to "
        f"{sorted(DIRECTIONAL_SWING_STRUCTURES)}. When trade_intent=range_income, "
        f"strategy-family option is restricted to {sorted(RANGE_INCOME_STRUCTURES)}. "
        "rejected_ideas may reference any canonical strategy id from "
        f"{sorted(STRATEGY_FAMILY_IDS)} so an out-of-mode family can be "
        "explicitly rejected.\n"
        "For strategy-family preferred_expression / best_expressions entries, set "
        "status_observed to 'strategy_review' and risk_flags_observed to [].\n"
        f"headline.conviction MUST be a single letter from {list(FINAL_RATING_VALUES)} "
        "(rating ladder in the prompt above). headline.conviction_label holds the "
        "one-clause explanation. headline.score is the 5-10 session confidence "
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


def _strip_openai_unsupported_patterns(node: Any) -> Any:
    """Strip regex 'pattern' constraints that OpenAI's structured-output
    validator rejects.

    Pydantic v2 emits a Decimal string serialization that includes a
    negative-lookahead regex (e.g. ``(?!^[-+.]*$)``). OpenAI's
    ``--output-schema`` validator does not support lookarounds and
    returns ``invalid_json_schema`` 400 errors. Decimal | None fields
    are still validated for type at the Pydantic layer when we
    deserialize the model's response — dropping the schema-side regex
    only relaxes what we tell the model, not what we enforce.

    The Codex/OpenAI structured output requires us to comply; the
    Anthropic/Claude path is more permissive and accepts the pattern,
    so this stripper runs only in the strict-mode path."""
    if isinstance(node, dict):
        cleaned = {
            key: _strip_openai_unsupported_patterns(value)
            for key, value in node.items()
        }
        # If this dict has a 'pattern' field containing a lookaround,
        # drop the pattern. Keep the rest of the type constraints intact.
        pattern = cleaned.get("pattern")
        if isinstance(pattern, str) and ("(?!" in pattern or "(?=" in pattern):
            cleaned = {k: v for k, v in cleaned.items() if k != "pattern"}
        return cleaned
    if isinstance(node, list):
        return [_strip_openai_unsupported_patterns(item) for item in node]
    return node


def trade_insights_ai_output_schema(
    *,
    strict: bool = True,
    strip_lookaround_regex: bool | None = None,
) -> dict[str, Any]:
    """Produce the JSON schema for TradeInsightAiOutcome.

    Two orthogonal axes:

    - `strict`: if True, every nested property is required and
      `additionalProperties: false` is enforced everywhere. Required by
      OpenAI/Codex structured output and by DeepSeek function-calling with
      `strict: true`. Claude's StructuredOutput tool silently drops to
      freeform JSON when the schema is too strict at every level, so the
      Claude path passes False.

    - `strip_lookaround_regex`: if True, drop Pydantic's negative-lookahead
      regex patterns from Decimal-string serialization. OpenAI's structured-
      output validator and DeepSeek's strict-mode function-calling validator
      both reject lookarounds; Anthropic's accepts them. Defaults to `strict`
      when None (preserves the historical coupling for callers that haven't
      migrated to the orthogonal API).
    """
    if strip_lookaround_regex is None:
        strip_lookaround_regex = strict
    raw = TradeInsightAiOutcome.model_json_schema()
    schema = _coerce_strict_schema(raw) if strict else raw
    if strip_lookaround_regex:
        schema = _strip_openai_unsupported_patterns(schema)
    schema["properties"]["schema_version"]["const"] = PROMPT_VERSION
    schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"]["enum"] = (
        list(FINAL_RATING_VALUES)
    )
    return schema
