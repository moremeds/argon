"""Build the deterministic prompt payload and JSON Schema for Trade Insights AI.

The trade_blast lane reuses the shared trade_insights_ai build pipeline
(`build_trade_insights_ai_analysis_input`, prompt assembly, hashing, and
schema generation) and layers on only its M6 deltas: the framework-view
payload sections (positioning / fundamentals / macro / flow_series / tape),
the embedded TRADE FRAMEWORK KNOWLEDGE reference, the framework decision-
stack directive, the qualitative scenario mapping, the two extra volatile
hash keys, and the trade-blast prompt version.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from uw_scan.cards.framework_tape import derive_framework_tape
from uw_scan.reports._shared_validation.util import _iso_z  # noqa: F401
from uw_scan.reports.trade_insights_ai.analysis_input import (
    _to_decimal,  # noqa: F401  # re-export for tests/test_trade_insights_ai.py
    build_trade_insights_ai_analysis_input as _base_build_analysis_input,
    build_trade_insights_ai_prompt as _base_build_prompt,
    build_trade_insights_ai_prompt_payload as _base_build_prompt_payload,
    hash_trade_insights_ai_analysis_input as _base_hash_analysis_input,
    trade_insights_ai_output_schema as _base_output_schema,
)

from .prompt_text import (
    CONTRACT_PROMPT,  # noqa: F401
    DIRECTIONAL_SWING_STRUCTURES,  # noqa: F401
    FINAL_RATING_VALUES,  # noqa: F401
    FRAMEWORK_DIRECTIVE,
    MARKET_INTELLIGENCE_PROMPT,
    PROMPT_VERSION,
    RANGE_INCOME_STRUCTURES,  # noqa: F401
    STRATEGY_FAMILY_IDS,  # noqa: F401
    TRADE_FRAMEWORK_KNOWLEDGE,
)

logger = logging.getLogger(__name__)

# Framework-view freshness fields are wall-clock-derived: exclude them so
# the analysis_input_hash stays stable when the underlying data vintage
# (snapshot_date / period_end) is unchanged. Without this, the cache-reuse
# key would bust every calendar day.
_EXTRA_VOLATILE_HASH_KEYS = frozenset({"age_days", "stale"})


# --------------------------------------------------------------------------- #
# Framework view (M6) — na-tolerant payload sections. Each returns an explicit
# availability flag and, where a freshness TTL applies, a stale flag + age_days
# computed from the stored snapshot/period date. Absent inputs degrade to
# {"available": False} — never omitted, never fabricated.
# --------------------------------------------------------------------------- #
def _age_days_from(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError as exc:
            logger.debug("unparseable date %r: %s", value, repr(exc))
            return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return (datetime.now(timezone.utc).date() - value).days
    return None


def _framework_positioning_section(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    age = _age_days_from(payload.get("snapshot_date"))
    out: dict[str, Any] = {
        "available": True,
        "stale": age is not None and age > 7,  # ~5 trading days
        "age_days": age,
        "snapshot_date": payload.get("snapshot_date"),
    }
    for key in (
        "si_pct_float",
        "si_short_interest",
        "si_days_to_cover",
        "analyst_buy",
        "analyst_hold",
        "analyst_sell",
        "analyst_target_avg",
        "analyst_target_hi",
        "analyst_target_lo",
        "inst_holder_count",
        "inst_total_value",
        "insider_buy_volume",
        "insider_sell_volume",
        "insider_net_flow",
        "earn_reactions_positive",
        "earn_reactions_total",
        "next_er_date",
    ):
        out[key] = payload.get(key)
    return out


def _framework_fundamentals_section(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    age = _age_days_from(payload.get("period_end"))
    out: dict[str, Any] = {
        "available": True,
        "stale": age is not None and age > 100,
        "age_days": age,
        "period_end": payload.get("period_end"),
        "fiscal_period": payload.get("fiscal_period"),
    }
    for key in (
        "revenue",
        "gross_margin",
        "op_margin",
        "net_margin",
        "fcf",
        "total_debt",
        "shareholders_equity",
        "diluted_shares",
        "share_count_delta",
        "latest_dividend_amount",
        "last_split_ratio",
    ):
        out[key] = payload.get(key)
    return out


def _framework_macro_section(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    age = _age_days_from(payload.get("as_of"))
    out: dict[str, Any] = {
        "available": True,
        "stale": age is not None and age > 1,
        "age_days": age,
    }
    out.update({k: v for k, v in payload.items() if k != "available"})
    return out


def _framework_flow_series_section(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    return {"available": True, **{k: v for k, v in payload.items() if k != "available"}}


def build_trade_insights_ai_analysis_input(
    ticker: str,
    run_id: int,
    trade_insights_input_hash: str,
    trade_insights_payload: dict[str, Any],
    stock_report_payload: dict[str, Any],
    stock_history_payload: dict[str, Any],
    volatility_series_payload: dict[str, Any],
    positioning_payload: dict[str, Any] | None = None,
    fundamentals_payload: dict[str, Any] | None = None,
    macro_payload: dict[str, Any] | None = None,
    flow_series_payload: dict[str, Any] | None = None,
    ohlcv_rows: list[Any] | None = None,
    next_er_date: date | None = None,
) -> dict[str, Any]:
    """Build the bounded deterministic payload captured at POST time,
    plus the blast lane's framework-view sections."""
    analysis_input = _base_build_analysis_input(
        ticker=ticker,
        run_id=run_id,
        trade_insights_input_hash=trade_insights_input_hash,
        trade_insights_payload=trade_insights_payload,
        stock_report_payload=stock_report_payload,
        stock_history_payload=stock_history_payload,
        volatility_series_payload=volatility_series_payload,
        prompt_version=PROMPT_VERSION,
    )

    # Framework view (M6): na-tolerant sections. Each degrades to
    # {"available": False} when its input is absent — never omitted, never
    # fabricated. next_er_date falls back to the positioning snapshot.
    positioning_section = _framework_positioning_section(positioning_payload)
    fundamentals_section = _framework_fundamentals_section(fundamentals_payload)
    macro_section = _framework_macro_section(macro_payload)
    flow_series_section = _framework_flow_series_section(flow_series_payload)
    effective_er_date = next_er_date or (
        positioning_payload.get("next_er_date") if positioning_payload else None
    )
    tape_section = derive_framework_tape(
        ohlcv_rows or [], next_earnings_date=effective_er_date
    )

    # The model reads these for the positioning / fundamentals / macro /
    # flow / price-action axes. Always present; each carries an explicit
    # availability flag.
    analysis_input.update(
        {
            "positioning": positioning_section,
            "fundamentals": fundamentals_section,
            "macro": macro_section,
            "flow_series": flow_series_section,
            "tape": tape_section,
        }
    )
    analysis_input["analysis_input_hash"] = hash_trade_insights_ai_analysis_input(
        analysis_input
    )
    return analysis_input


def hash_trade_insights_ai_analysis_input(analysis_input: dict[str, Any]) -> str:
    """Stable hash over deterministic input, excluding execution metadata
    (and the blast lane's wall-clock freshness fields)."""

    return _base_hash_analysis_input(
        analysis_input, extra_volatile_keys=_EXTRA_VOLATILE_HASH_KEYS
    )


def build_trade_insights_ai_prompt_payload(
    analysis_input: dict[str, Any],
    *,
    produced_at: datetime,
) -> dict[str, Any]:
    return _base_build_prompt_payload(
        analysis_input,
        produced_at=produced_at,
        extra_volatile_keys=_EXTRA_VOLATILE_HASH_KEYS,
    )


# M6 blast deltas spliced into the shared prompt assembly: the embedded
# TRADE FRAMEWORK KNOWLEDGE reference block, the qualitative-likelihood
# scenario_cards mapping clause, and the framework decision-stack directive.
_EMBEDDED_REFERENCE = (
    "═══════════════════════════════════════════════════════════════════════════\n"
    "TRADE FRAMEWORK KNOWLEDGE (embedded reference — apply the methodology below)\n"
    "═══════════════════════════════════════════════════════════════════════════\n"
    f"{TRADE_FRAMEWORK_KNOWLEDGE}"
)

_SCENARIO_MAPPING = (
    "(exactly 3 rows with likelihood in {primary, plausible, tail}; "
    "exactly one primary matching directional_bias; no numeric "
    "percentages)"
)


def build_trade_insights_ai_prompt(prompt_payload: dict[str, Any]) -> str:
    return _base_build_prompt(
        prompt_payload,
        prompt_version=PROMPT_VERSION,
        market_intelligence=MARKET_INTELLIGENCE_PROMPT,
        embedded_reference=_EMBEDDED_REFERENCE,
        scenario_mapping=_SCENARIO_MAPPING,
        framework_directive=FRAMEWORK_DIRECTIVE,
    )


def trade_insights_ai_output_schema(
    *,
    strict: bool = True,
    strip_lookaround_regex: bool | None = None,
) -> dict[str, Any]:
    """Produce the JSON schema for TradeInsightAiOutcome stamped with the
    blast prompt version — see the shared implementation for the
    strict/lax and lookaround-strip semantics."""
    return _base_output_schema(
        strict=strict,
        strip_lookaround_regex=strip_lookaround_regex,
        prompt_version=PROMPT_VERSION,
    )
