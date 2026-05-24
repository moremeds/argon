"""Deterministic Trade Insights assembler.

V1 is intentionally rule-based. Codex/LLM commentary is a later optional layer
that consumes this structured output but does not alter status or risk checks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from uw_scan.models import (
    CandidateStructure,
    ChainFlowReadRow,
    InsightBadge,
    InsightLeg,
    InsightSignalRow,
    InsightsSynthesis,
    SourceReconciliation,
    SourceReconciliationRow,
    TermMoveRow,
    TradeInsightsHeader,
    TradeInsightsResponse,
)

ASSEMBLER_VERSION = "trade-insights-v1"


@dataclass(frozen=True)
class ParsedOptionSymbol:
    root: str
    expiry: date
    right: str
    strike: Decimal


def parse_option_symbol(symbol: str) -> ParsedOptionSymbol | None:
    """Parse OCC/OSI-style compact symbols like TSLA260515C00430000."""
    if len(symbol) < 15:
        return None
    right_index = max(symbol.rfind("C"), symbol.rfind("P"))
    if right_index < 6:
        return None
    right = symbol[right_index]
    ymd = symbol[right_index - 6 : right_index]
    strike_raw = symbol[right_index + 1 :]
    root = symbol[: right_index - 6]
    if not root or len(ymd) != 6 or len(strike_raw) != 8:
        return None
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        strike = Decimal(str(int(strike_raw))) / Decimal("1000")
    except (ValueError, ArithmeticError) as exc:
        _parse_error = repr(exc)
        return None
    return ParsedOptionSymbol(root=root, expiry=expiry, right=right, strike=strike)


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _mid(contract: dict) -> Decimal | None:
    bid = _dec(contract.get("nbbo_bid"))
    ask = _dec(contract.get("nbbo_ask"))
    if bid is not None and ask is not None and bid >= 0 and ask >= bid:
        return (bid + ask) / Decimal("2")
    return _dec(contract.get("last_price"))


def _credit_spread_math(
    *, short_mid: Decimal, long_mid: Decimal, width: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    net_credit = short_mid - long_mid
    max_profit = net_credit
    max_loss = width - net_credit
    return net_credit, max_loss, max_profit


def _stable_payload_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalized_contracts(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in raw:
        parsed = parse_option_symbol(str(row.get("option_symbol", "")))
        if parsed is None:
            continue
        item = dict(row)
        item["parsed"] = parsed
        item["mid"] = _mid(row)
        out.append(item)
    return out


def _build_flow_table(contracts: list[dict]) -> list[ChainFlowReadRow]:
    by_strike: dict[Decimal, dict[str, dict]] = {}
    for c in contracts:
        parsed: ParsedOptionSymbol = c["parsed"]
        by_strike.setdefault(parsed.strike, {})[parsed.right] = c

    rows: list[ChainFlowReadRow] = []
    for strike in sorted(by_strike):
        call = by_strike[strike].get("C", {})
        put = by_strike[strike].get("P", {})
        call_volume = call.get("volume")
        put_volume = put.get("volume")
        call_oi = call.get("open_interest")
        put_oi = put.get("open_interest")
        ratio = None
        if call_volume is not None and put_volume not in (None, 0):
            ratio = Decimal(str(call_volume)) / Decimal(str(put_volume))
        requires_t1 = bool(
            (call_volume is not None and call_oi is not None and call_volume > call_oi)
            or (put_volume is not None and put_oi is not None and put_volume > put_oi)
        )
        rows.append(
            ChainFlowReadRow(
                strike=strike,
                call_volume=call_volume,
                call_open_interest=call_oi,
                put_volume=put_volume,
                put_open_interest=put_oi,
                call_put_volume_ratio=ratio,
                volume_oi_note="Volume > OI; confirm with next-day OI"
                if requires_t1
                else "No volume/OI anomaly",
                read="Call demand concentrated"
                if ratio is not None and ratio > Decimal("1.5")
                else "Mixed flow",
                requires_t1_oi_confirmation=requires_t1,
            )
        )
    return rows


def _build_source_reconciliation(
    repo, run_id: int, ticker: str
) -> SourceReconciliation:
    fetch = getattr(repo, "fetch_source_reconciliation_rows", None)
    rows = fetch(run_id, ticker) if fetch is not None else []
    if not rows:
        return SourceReconciliation(
            status="UNKNOWN",
            headline="No external IV source reconciliation stored for this run",
            decision="Use chain-derived values for contract math; do not make absolute-IV trust claims.",
        )
    return SourceReconciliation(
        status="MIXED" if any(r.get("iv_diff") for r in rows) else "READY",
        headline="Source reconciliation rows available",
        rows=[SourceReconciliationRow(**r) for r in rows],
        decision="Prefer chain-derived IV for absolute cheap/rich decisions when vendor IV disagrees.",
    )


def _atm_straddles_by_expiry(
    contracts: list[dict], spot: Decimal | None
) -> dict[date, Decimal]:
    if spot is None:
        return {}
    out: dict[date, Decimal] = {}
    expiries = sorted({c["parsed"].expiry for c in contracts})
    for expiry in expiries:
        same_expiry = [
            c
            for c in contracts
            if c["parsed"].expiry == expiry and c.get("mid") is not None
        ]
        calls = [c for c in same_expiry if c["parsed"].right == "C"]
        puts = [c for c in same_expiry if c["parsed"].right == "P"]
        if not calls or not puts:
            continue
        call = min(calls, key=lambda c: abs(c["parsed"].strike - spot))
        put = min(puts, key=lambda c: abs(c["parsed"].strike - spot))
        if call["parsed"].strike == put["parsed"].strike:
            out[expiry] = call["mid"] + put["mid"]
    return out


def _build_term_rows(
    raw: list[dict], contracts: list[dict], spot: Decimal | None
) -> list[TermMoveRow]:
    atm_by_expiry = _atm_straddles_by_expiry(contracts, spot)
    rows: list[TermMoveRow] = []
    for r in raw:
        dte = r.get("dte")
        move = _dec(r.get("implied_move_perc"))
        daily = None
        if dte and move is not None and dte > 0:
            daily = move / Decimal(str(dte))
        rows.append(
            TermMoveRow(
                expiry=r["expiry"],
                dte=dte,
                atm_straddle=atm_by_expiry.get(r["expiry"]),
                implied_move_perc=move,
                daily_implied_move_perc=daily,
                read="Front elevated"
                if dte is not None and dte <= 7
                else "Back expiry",
            )
        )
    return rows


def _leg(side: str, c: dict) -> InsightLeg:
    parsed: ParsedOptionSymbol = c["parsed"]
    return InsightLeg(
        side=side,
        option_symbol=c["option_symbol"],
        option_right=parsed.right,
        expiry=parsed.expiry,
        strike=parsed.strike,
        mid=c.get("mid"),
    )


# v5 expression_delta values (mirror the directional_bias enum so the AI
# prompt can pattern-match candidates to the chosen bias):
#   "long_delta"  — net positive delta (long_call, call_debit_spread,
#                   bull_call_spread, put_credit_spread)
#   "short_delta" — net negative delta (long_put, put_debit_spread,
#                   bear_put_spread, call_credit_spread)
#   "neutral"     — delta-neutral or directionally agnostic (iron_condor,
#                   long_straddle, calendar_spread)
_EXPRESSION_DELTA_BY_STRUCTURE: dict[str, str] = {
    "call_credit_spread": "short_delta",
    "put_credit_spread": "long_delta",
    "iron_condor": "neutral",
    "long_straddle": "neutral",
    "calendar_spread": "neutral",
    "bull_call_spread": "long_delta",
    "bear_put_spread": "short_delta",
    "call_debit_spread": "long_delta",
    "put_debit_spread": "short_delta",
    "long_call": "long_delta",
    "long_put": "short_delta",
}


def _first_leg_dte(legs: list[InsightLeg], as_of_date: date | None) -> int | None:
    """Return the DTE of the candidate's first leg.

    Used to derive `dte_band` for the candidate. `as_of_date` may be None
    when the assembler is called without a reference date (rare path); in
    that case dte_band tagging is skipped and the candidate gets the
    default empty string.
    """
    if as_of_date is None or not legs:
        return None
    return (legs[0].expiry - as_of_date).days


# Swing-HOLD DTE window. The trade is HELD 5-10 trading sessions (1-2 weeks).
#
# v5 widens the window to 14-75 DTE and SPLITS it into two bands so the AI can
# pick the band that matches the trade thesis (per the prompt's DTE-band rule
# in M3):
#
#   momentum (14-30 DTE): high gamma per $ premium. Used when the directional
#     trigger has ALREADY fired (entry_state=ACTIVE) and we want to capture a
#     fast breakout. Closer to the 0-7 DTE theta-crush zone on exit, accepted
#     because the move is the thesis.
#
#   standard (31-44 DTE): the legacy v4 sweet spot. Useful for the conservative
#     middle ground when neither full momentum nor full trend applies.
#
#   trend (45-75 DTE): lower gamma decay, more theta protection. Used when
#     entry_state=CONDITIONAL and we expect a multi-week trend continuation
#     rather than an immediate breakout.
#
# Calendar spreads relax the upper bound on the far leg (see below).
SWING_DTE_MIN = 14
SWING_DTE_MAX = 75
SWING_DTE_MOMENTUM_MAX = 30  # momentum band: SWING_DTE_MIN..SWING_DTE_MOMENTUM_MAX
SWING_DTE_TREND_MIN = 45  # trend band: SWING_DTE_TREND_MIN..SWING_DTE_MAX
SWING_DTE_PREFERRED_MIN = 28  # legacy preferred-band lower (drives _expiry_rank)
SWING_DTE_PREFERRED_MAX = 45  # legacy preferred-band upper
SWING_CALENDAR_FAR_DTE_MAX = 90


def _dte_band(dte: int) -> str:
    """Return the v5 dte_band label for a given DTE integer.

    momentum  (14-30)  -> high gamma per $ premium, used for active breakouts
    standard  (31-44)  -> legacy v4 sweet spot
    trend     (45-75)  -> theta-protected trend-continuation entries
    """
    if dte <= SWING_DTE_MOMENTUM_MAX:
        return "momentum"
    if dte >= SWING_DTE_TREND_MIN:
        return "trend"
    return "standard"


def _expiry_rank(dte: int) -> int:
    """Lower is preferred. v5 widens the window to 14-75 DTE but keeps the
    30-38 sweet spot at the top of the rank — it's still the textbook
    swing-hold band. The new 14-20 momentum tail and 61-75 trend tail rank
    LAST in the unified preference so they are only picked when the prompt
    explicitly asks for that band (M3 + downstream); their presence is to
    populate the candidate menu, not to win by default sort."""
    if 30 <= dte <= 38:
        return 0
    if SWING_DTE_PREFERRED_MIN <= dte <= SWING_DTE_PREFERRED_MAX:
        return 1
    if 46 <= dte <= 60:
        return 2
    if 21 <= dte <= 27:
        return 3
    if 14 <= dte <= 20:
        return 4  # momentum tail — explicit ask only
    if 61 <= dte <= SWING_DTE_MAX:
        return 5  # trend tail — explicit ask only
    return 6  # outside window; should be filtered before sorting


def _build_candidates(
    contracts: list[dict],
    spot: Decimal | None,
    *,
    as_of: datetime | None = None,
    dte_min: int = SWING_DTE_MIN,
    dte_max: int = SWING_DTE_MAX,
    calendar_far_dte_max: int = SWING_CALENDAR_FAR_DTE_MAX,
) -> list[CandidateStructure]:
    if spot is None:
        return []
    # Filter to the swing-HOLD entry window (21-60 DTE by default; preferred
    # 28-45). Directional structures (verticals, condor, straddle) only
    # consider contracts inside the window; calendars treat the window as the
    # *near*-leg constraint and allow the far leg to extend out to
    # calendar_far_dte_max (default 90 DTE) so the back leg still has premium
    # remaining after the 1-2 week hold consumes the front.
    if as_of is not None:
        as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of

        def _dte_of(contract: dict) -> int:
            return (contract["parsed"].expiry - as_of_date).days

        in_swing = [c for c in contracts if dte_min <= _dte_of(c) <= dte_max]
        in_swing_or_far = [
            c for c in contracts if dte_min <= _dte_of(c) <= calendar_far_dte_max
        ]

        # Sort by (expiry preference, strike distance) so candidates land in
        # the 28-45 DTE band when liquidity allows, falling back to 46-60 or
        # 21-27 only when nothing closer to the preferred window exists.
        # Without this, the closest-to-spot strike wins regardless of expiry —
        # and the chain's most-liquid ATM strike is usually on the weekly
        # closest to today, dragging candidates toward the lower DTE bound
        # where the 1-2 week hold would land in the theta-crush zone.
        def _sort_key(c: dict) -> tuple[int, Decimal]:
            return (_expiry_rank(_dte_of(c)), abs(c["parsed"].strike - spot))

    else:
        in_swing = list(contracts)
        in_swing_or_far = list(contracts)

        def _sort_key(c: dict) -> tuple[int, Decimal]:
            return (0, abs(c["parsed"].strike - spot))

    calls = sorted(
        [c for c in in_swing if c["parsed"].right == "C" and c.get("mid") is not None],
        key=_sort_key,
    )
    puts = sorted(
        [c for c in in_swing if c["parsed"].right == "P" and c.get("mid") is not None],
        key=_sort_key,
    )
    candidates: list[CandidateStructure] = []

    if len(calls) >= 2:
        short_call = calls[0]
        long_call = next(
            (c for c in calls[1:] if c["parsed"].strike > short_call["parsed"].strike),
            None,
        )
        if long_call is not None:
            width = long_call["parsed"].strike - short_call["parsed"].strike
            credit, max_loss, max_profit = _credit_spread_math(
                short_mid=short_call["mid"], long_mid=long_call["mid"], width=width
            )
            candidates.append(
                CandidateStructure(
                    idea_id="A",
                    structure="call_credit_spread",
                    thesis="Defined-risk short-call premium candidate.",
                    expression_type="SHORT_VOL",
                    legs=[_leg("sell", short_call), _leg("buy", long_call)],
                    net_credit_debit=credit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    profit_zone=f"Underlying below {short_call['parsed'].strike}",
                    edge_source="IV-RV spread / theta",
                    risk_flags=["bullish_flow_can_break_call_side"],
                    rank=1,
                    status="candidate",
                )
            )

    if len(puts) >= 2:
        short_put = puts[0]
        long_put = next(
            (p for p in puts[1:] if p["parsed"].strike < short_put["parsed"].strike),
            None,
        )
        if long_put is not None:
            width = short_put["parsed"].strike - long_put["parsed"].strike
            credit, max_loss, max_profit = _credit_spread_math(
                short_mid=short_put["mid"], long_mid=long_put["mid"], width=width
            )
            candidates.append(
                CandidateStructure(
                    idea_id="B",
                    structure="put_credit_spread",
                    thesis="Defined-risk short-put premium candidate.",
                    expression_type="DIRECTIONAL_THETA",
                    legs=[_leg("sell", short_put), _leg("buy", long_put)],
                    net_credit_debit=credit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    profit_zone=f"Underlying above {short_put['parsed'].strike}",
                    edge_source="theta / bullish flow",
                    risk_flags=["gap_down_risk"],
                    rank=2,
                    status="candidate",
                )
            )

    if len(candidates) >= 2:
        call_spread = next(
            (c for c in candidates if c.structure == "call_credit_spread"), None
        )
        put_spread = next(
            (c for c in candidates if c.structure == "put_credit_spread"), None
        )
        if (
            call_spread
            and put_spread
            and call_spread.net_credit_debit
            and put_spread.net_credit_debit
        ):
            # Iron condor math: max loss equals the wider wing's width minus the
            # TOTAL credit collected from both verticals. Only one wing can be
            # breached at expiry, so the loss on that wing is (width - credit),
            # not the sum of the two wing losses. Using max(call_spread.max_loss,
            # put_spread.max_loss) double-counts the credit on the unused wing
            # and understates the actual max loss whenever credit > 0.
            call_short_strike = call_spread.legs[0].strike
            call_long_strike = call_spread.legs[1].strike
            put_short_strike = put_spread.legs[0].strike
            put_long_strike = put_spread.legs[1].strike
            call_width = abs(call_long_strike - call_short_strike)
            put_width = abs(put_short_strike - put_long_strike)
            credit = call_spread.net_credit_debit + put_spread.net_credit_debit
            max_loss = max(call_width, put_width) - credit
            candidates.append(
                CandidateStructure(
                    idea_id="C",
                    structure="iron_condor",
                    thesis="Defined-risk range candidate built from both short verticals.",
                    expression_type="SHORT_VOL_RANGE",
                    legs=[*put_spread.legs, *call_spread.legs],
                    net_credit_debit=credit,
                    max_profit=credit,
                    max_loss=max_loss,
                    profit_zone=f"{put_spread.profit_zone}; {call_spread.profit_zone}",
                    edge_source="term structure / IV-RV spread / range structure",
                    risk_flags=["breakout_risk", "event_check_required"],
                    rank=3,
                    status="candidate",
                )
            )

    # Straddle expiry follows the same preference rank as the verticals so a
    # 14-DTE straddle outranks a 7-DTE one. Theta decay punishes long-vol
    # structures hardest at sub-10-DTE, so a swing straddle must not land at
    # the absolute front of the swing window when a preferred-band expiry
    # exists. The `calls`/`puts` lists are already preference-sorted; pick the
    # expiry of the first call that also has a matching put.
    if as_of is not None and (calls or puts):
        as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
        put_expiries = {p["parsed"].expiry for p in puts}
        swing_front_expiry = next(
            (c["parsed"].expiry for c in calls if c["parsed"].expiry in put_expiries),
            None,
        )
    else:
        swing_front_expiry = min((c["parsed"].expiry for c in in_swing), default=None)
    if swing_front_expiry is not None:
        front_calls = [c for c in calls if c["parsed"].expiry == swing_front_expiry]
        front_puts = [p for p in puts if p["parsed"].expiry == swing_front_expiry]
        if front_calls and front_puts:
            call = front_calls[0]
            put = min(
                front_puts,
                key=lambda p: abs(p["parsed"].strike - call["parsed"].strike),
            )
            debit = call["mid"] + put["mid"]
            strike = call["parsed"].strike
            candidates.append(
                CandidateStructure(
                    idea_id="D",
                    structure="long_straddle",
                    thesis="Long-vol candidate for cheap-vol or realized-move expansion setups.",
                    expression_type="LONG_VOL",
                    legs=[_leg("buy", call), _leg("buy", put)],
                    net_credit_debit=-debit,
                    max_loss=debit,
                    max_profit=None,
                    breakevens=[strike - debit, strike + debit]
                    if call["parsed"].strike == put["parsed"].strike
                    else [],
                    edge_source="realized-vol expansion / cheap IV",
                    risk_flags=["theta_decay", "requires_realized_move"],
                    rank=4,
                    status="candidate",
                )
            )

    # Calendar near-leg lives in the swing window; the far leg is allowed
    # out to calendar_far_dte_max so the term-structure dislocation is real.
    # Far-leg sort is plain strike-distance — the far-leg expiry is implicitly
    # selected by the calendar_pairs loop preferring the earliest matching
    # near→far pair off `calls`, which is already swing-preference sorted.
    far_calls = sorted(
        [
            c
            for c in in_swing_or_far
            if c["parsed"].right == "C" and c.get("mid") is not None
        ],
        key=lambda c: abs(c["parsed"].strike - spot),
    )
    calendar_pairs = [
        (near, far)
        for near in calls
        for far in far_calls
        if near["parsed"].strike == far["parsed"].strike
        and near["parsed"].expiry < far["parsed"].expiry
    ]
    if calendar_pairs:
        near, far = calendar_pairs[0]
        debit = far["mid"] - near["mid"]
        # Calendar spread: max loss is bounded by the initial net debit only if
        # the position is held to expiration of the far leg. Earlier exit (the
        # normal exit, around the front expiry) has path-dependent P&L driven by
        # term-structure shifts and changes in far-leg IV; theoretical max loss
        # at the front expiry can exceed the debit if the far leg's IV collapses.
        # V1 reports the "held-to-far-expiry" bound as max_loss and flags the
        # path-dependence in risk_flags so users do not treat it as a hard cap.
        # If the near leg is more expensive than the far leg (backwardation),
        # this becomes a credit calendar; we skip the candidate rather than
        # report a negative debit, because that scenario needs different math.
        if debit <= Decimal("0"):
            pass
        else:
            candidates.append(
                CandidateStructure(
                    idea_id="E",
                    structure="calendar_spread",
                    thesis="Term-structure candidate: sell front volatility, buy later expiry.",
                    expression_type="TERM_STRUCTURE",
                    legs=[_leg("sell", near), _leg("buy", far)],
                    net_credit_debit=-debit,
                    max_loss=debit,
                    max_profit=None,
                    profit_zone=f"Near {near['parsed'].strike} through front expiry",
                    edge_source="front/back implied-vol dislocation",
                    risk_flags=[
                        "event_check_required",
                        "assignment_ex_dividend_check",
                        "path_dependent_far_iv_collapse",
                    ],
                    rank=5,
                    status="candidate",
                )
            )

    # ─────────────────────────────────────────────────────────────────────
    # v5 directional debit structures (F-I). The legacy v4 menu only emitted
    # credit spreads / iron condor / straddle / calendar — all vol-selling or
    # delta-neutral. A directional 1-2 week swing trader needs DEBIT structures
    # whose net delta MATCHES the directional_bias chosen by the AI at decision
    # Step 2. Without these in the candidate pool, even a perfect v5 prompt
    # would fall back to "strategy_family" picks instead of a concrete trade.
    # ─────────────────────────────────────────────────────────────────────

    # F: bull_call_spread — long lower call + short higher call. Net DEBIT.
    #    Max profit = width - debit, max loss = debit. LONG_DELTA expression.
    if len(calls) >= 2:
        long_low_call = calls[0]
        short_high_call = next(
            (
                c
                for c in calls[1:]
                if c["parsed"].strike > long_low_call["parsed"].strike
            ),
            None,
        )
        if short_high_call is not None:
            width = short_high_call["parsed"].strike - long_low_call["parsed"].strike
            net_debit = long_low_call["mid"] - short_high_call["mid"]
            if net_debit > Decimal("0"):
                max_profit = width - net_debit
                candidates.append(
                    CandidateStructure(
                        idea_id="F",
                        structure="bull_call_spread",
                        thesis="Defined-risk long-delta directional candidate (call debit spread).",
                        expression_type="LONG_DELTA",
                        legs=[
                            _leg("buy", long_low_call),
                            _leg("sell", short_high_call),
                        ],
                        net_credit_debit=-net_debit,
                        max_profit=max_profit,
                        max_loss=net_debit,
                        profit_zone=(
                            f"Underlying above {long_low_call['parsed'].strike} at expiry"
                        ),
                        edge_source="directional long-delta expression",
                        risk_flags=["theta_drag", "needs_directional_move"],
                        rank=6,
                        status="candidate",
                    )
                )

    # G: bear_put_spread — long higher put + short lower put. Net DEBIT.
    #    Max profit = width - debit, max loss = debit. SHORT_DELTA expression.
    if len(puts) >= 2:
        long_high_put = puts[0]
        short_low_put = next(
            (
                p
                for p in puts[1:]
                if p["parsed"].strike < long_high_put["parsed"].strike
            ),
            None,
        )
        if short_low_put is not None:
            width = long_high_put["parsed"].strike - short_low_put["parsed"].strike
            net_debit = long_high_put["mid"] - short_low_put["mid"]
            if net_debit > Decimal("0"):
                max_profit = width - net_debit
                candidates.append(
                    CandidateStructure(
                        idea_id="G",
                        structure="bear_put_spread",
                        thesis="Defined-risk short-delta directional candidate (put debit spread).",
                        expression_type="SHORT_DELTA",
                        legs=[_leg("buy", long_high_put), _leg("sell", short_low_put)],
                        net_credit_debit=-net_debit,
                        max_profit=max_profit,
                        max_loss=net_debit,
                        profit_zone=(
                            f"Underlying below {long_high_put['parsed'].strike} at expiry"
                        ),
                        edge_source="directional short-delta expression",
                        risk_flags=["theta_drag", "needs_directional_move"],
                        rank=7,
                        status="candidate",
                    )
                )

    # H: long_call — single ATM/slight-OTM call. Net DEBIT.
    #    Max profit = unbounded (upside), max loss = premium. LONG_DELTA.
    if calls:
        atm_call = calls[0]
        if atm_call.get("mid") and atm_call["mid"] > Decimal("0"):
            candidates.append(
                CandidateStructure(
                    idea_id="H",
                    structure="long_call",
                    thesis="Unbounded-upside long-delta candidate (single long call).",
                    expression_type="LONG_DELTA",
                    legs=[_leg("buy", atm_call)],
                    net_credit_debit=-atm_call["mid"],
                    max_profit=None,
                    max_loss=atm_call["mid"],
                    breakevens=[atm_call["parsed"].strike + atm_call["mid"]],
                    profit_zone=(
                        f"Underlying above {atm_call['parsed'].strike + atm_call['mid']}"
                    ),
                    edge_source="directional long-delta expression",
                    risk_flags=["theta_decay", "iv_crush_risk"],
                    rank=8,
                    status="candidate",
                )
            )

    # I: long_put — single ATM/slight-OTM put. Net DEBIT.
    #    Max profit = strike - premium (bounded), max loss = premium. SHORT_DELTA.
    if puts:
        atm_put = puts[0]
        if atm_put.get("mid") and atm_put["mid"] > Decimal("0"):
            bounded_max_profit = atm_put["parsed"].strike - atm_put["mid"]
            candidates.append(
                CandidateStructure(
                    idea_id="I",
                    structure="long_put",
                    thesis="Bounded-downside short-delta candidate (single long put).",
                    expression_type="SHORT_DELTA",
                    legs=[_leg("buy", atm_put)],
                    net_credit_debit=-atm_put["mid"],
                    max_profit=bounded_max_profit,
                    max_loss=atm_put["mid"],
                    breakevens=[atm_put["parsed"].strike - atm_put["mid"]],
                    profit_zone=(
                        f"Underlying below {atm_put['parsed'].strike - atm_put['mid']}"
                    ),
                    edge_source="directional short-delta expression",
                    risk_flags=["theta_decay", "iv_crush_risk"],
                    rank=9,
                    status="candidate",
                )
            )

    # ─────────────────────────────────────────────────────────────────────
    # Tag every candidate with dte_band + expression_delta so the v5 AI
    # prompt can match candidates to (directional_bias, dte_band) chosen in
    # decision Steps 2 and 5. We do this in one pass at the end rather than
    # threading the metadata through each constructor — keeps the
    # individual structure-builders focused on the math.
    # ─────────────────────────────────────────────────────────────────────
    as_of_date_for_tag = (
        (as_of.date() if isinstance(as_of, datetime) else as_of)
        if as_of is not None
        else None
    )
    for cand in candidates:
        dte = _first_leg_dte(cand.legs, as_of_date_for_tag)
        if dte is not None:
            cand.dte_band = _dte_band(dte)
        cand.expression_delta = _EXPRESSION_DELTA_BY_STRUCTURE.get(cand.structure, "")

    return candidates


def assemble_trade_insights(
    *,
    ticker: str,
    run_id: int,
    repo,
    as_of: datetime | None,
    spot: Decimal | None,
) -> TradeInsightsResponse:
    contracts = _normalized_contracts(repo.fetch_option_contracts_rich(run_id, ticker))
    source_reconciliation = _build_source_reconciliation(repo, run_id, ticker)
    flow_rows = _build_flow_table(contracts)
    term_rows = _build_term_rows(
        repo.fetch_iv_term_rows(run_id, ticker), contracts, spot
    )
    candidates = _build_candidates(contracts, spot, as_of=as_of)
    # Event data is still not wired through this assembler, so it stays visible
    # as a required pre-sizing check. It should not suppress the research read
    # or erase the best defined-risk candidate.
    event_data_known = False
    liquidity_ready = bool(contracts) and all(
        c.max_loss is not None for c in candidates
    )

    badges: list[InsightBadge] = [
        InsightBadge(code="DEFINED_RISK_ONLY", label="Defined-risk only")
    ]
    if not contracts:
        badges.append(
            InsightBadge(code="NO_CHAIN", label="No option chain", severity="warning")
        )
    if source_reconciliation.status in {"UNKNOWN", "MIXED"}:
        badges.append(
            InsightBadge(
                code="SOURCE_RECONCILIATION_REQUIRED",
                label="Source reconciliation incomplete",
                severity="warning",
            )
        )
    if not event_data_known:
        badges.append(
            InsightBadge(
                code="EVENT_CHECK_REQUIRED",
                label="Event check required",
                severity="warning",
            )
        )
    if any(r.requires_t1_oi_confirmation for r in flow_rows):
        badges.append(
            InsightBadge(
                code="T1_OI_CONFIRMATION",
                label="Volume > OI needs next-day OI confirmation",
                severity="warning",
            )
        )

    signal_stack = [
        InsightSignalRow(
            lens="VOL_LEVEL",
            read="IV_RV_PROXY_AVAILABLE",
            evidence=[
                "Use Volatility tab IV-RV spread proxy; true model-free VRP not computed."
            ],
        ),
        InsightSignalRow(
            lens="FLOW",
            read="CALL_DEMAND"
            if any((r.call_put_volume_ratio or 0) > 1 for r in flow_rows)
            else "MIXED",
            evidence=[f"{len(flow_rows)} strike rows available"],
        ),
        InsightSignalRow(
            lens="TERM",
            read="TERM_ROWS_AVAILABLE" if term_rows else "MISSING",
            evidence=[f"{len(term_rows)} expiries available"],
        ),
    ]

    can_prefer = bool(candidates) and liquidity_ready
    preferred = candidates[0].idea_id if can_prefer else None
    for candidate in candidates:
        candidate.status = (
            "preferred" if candidate.idea_id == preferred else "candidate"
        )
    return TradeInsightsResponse(
        ticker=ticker,
        as_of=as_of,
        header=TradeInsightsHeader(
            dominant_bias="NEUTRAL_SHORT_VOL" if candidates else "NEUTRAL",
            primary_setup="TRADE_INSIGHTS_RESEARCH",
            confidence_label="MEDIUM" if contracts and candidates else "LOW",
            data_quality_label="MIXED" if contracts else "INSUFFICIENT",
            idea_count=len(candidates),
            preferred_idea_id=preferred,
            badges=badges,
        ),
        source_reconciliation=source_reconciliation,
        signal_stack=signal_stack,
        flow_table=flow_rows,
        term_structure_table=term_rows,
        candidate_structures=candidates,
        synthesis=InsightsSynthesis(
            dominant_story=(
                f"Research-grade setup favors candidate {preferred}; event, source, and "
                "liquidity checks remain pre-sizing controls."
            )
            if preferred
            else "Deterministic research-grade ideas built from current chain, flow, and term data."
            if candidates
            else "Insufficient option-chain data for structure generation.",
            preferred_idea_id=preferred,
            best_risk_reward_idea_id=preferred,
            avoid=["Naked short options", "Undefined-risk short-vol structures"],
            required_before_sizing=[
                "Confirm event calendar through all expiries",
                "Confirm bid/ask width and open interest",
                "Confirm next-day OI for volume > OI flags",
                "Run out-of-sample validation before automation",
            ],
        ),
    )
