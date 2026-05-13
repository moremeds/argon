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
    except (ValueError, ArithmeticError):
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


def _build_source_reconciliation(repo, run_id: int, ticker: str) -> SourceReconciliation:
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
                read="Front elevated" if dte is not None and dte <= 7 else "Back expiry",
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


def _build_candidates(contracts: list[dict], spot: Decimal | None) -> list[CandidateStructure]:
    if spot is None:
        return []
    calls = sorted(
        [c for c in contracts if c["parsed"].right == "C" and c.get("mid") is not None],
        key=lambda c: abs(c["parsed"].strike - spot),
    )
    puts = sorted(
        [c for c in contracts if c["parsed"].right == "P" and c.get("mid") is not None],
        key=lambda c: abs(c["parsed"].strike - spot),
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
        if call_spread and put_spread and call_spread.net_credit_debit and put_spread.net_credit_debit:
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

    front_expiry = min((c["parsed"].expiry for c in contracts), default=None)
    if front_expiry is not None:
        front_calls = [c for c in calls if c["parsed"].expiry == front_expiry]
        front_puts = [p for p in puts if p["parsed"].expiry == front_expiry]
        if front_calls and front_puts:
            call = front_calls[0]
            put = min(front_puts, key=lambda p: abs(p["parsed"].strike - call["parsed"].strike))
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

    calendar_pairs = [
        (near, far)
        for near in calls
        for far in calls
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
    term_rows = _build_term_rows(repo.fetch_iv_term_rows(run_id, ticker), contracts, spot)
    candidates = _build_candidates(contracts, spot)
    # V1 intentionally hardcodes event_data_known=False so every candidate ends
    # as `needs_check` and `preferred_idea_id` stays None. The earnings/dividend
    # plumbing exists upstream (flow_events.next_earnings_date,
    # SingleStockReport.next_earnings_date) but is not wired through to this
    # assembler in V1. A follow-up patch should read those fields and flip the
    # gate when both are present and outside all candidate expiries.
    event_data_known = False
    liquidity_ready = bool(contracts) and all(c.max_loss is not None for c in candidates)

    badges: list[InsightBadge] = [InsightBadge(code="DEFINED_RISK_ONLY", label="Defined-risk only")]
    if not contracts:
        badges.append(InsightBadge(code="NO_CHAIN", label="No option chain", severity="warning"))
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
            evidence=["Use Volatility tab IV-RV spread proxy; true model-free VRP not computed."],
        ),
        InsightSignalRow(
            lens="FLOW",
            read="CALL_DEMAND" if any((r.call_put_volume_ratio or 0) > 1 for r in flow_rows) else "MIXED",
            evidence=[f"{len(flow_rows)} strike rows available"],
        ),
        InsightSignalRow(
            lens="TERM",
            read="TERM_ROWS_AVAILABLE" if term_rows else "MISSING",
            evidence=[f"{len(term_rows)} expiries available"],
        ),
    ]

    can_prefer = (
        bool(candidates)
        and event_data_known
        and liquidity_ready
        and source_reconciliation.status != "UNKNOWN"
    )
    if not can_prefer:
        for candidate in candidates:
            candidate.status = "needs_check"
    preferred = candidates[0].idea_id if can_prefer else None
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
            dominant_story="Deterministic research-grade ideas built from current chain, flow, and term data."
            if candidates
            else "Insufficient option-chain data for structure generation.",
            preferred_idea_id=preferred,
            best_risk_reward_idea_id=preferred,
            avoid=["Naked short options", "Executable recommendation language"],
            required_before_sizing=[
                "Confirm event calendar through all expiries",
                "Confirm bid/ask width and open interest",
                "Confirm next-day OI for volume > OI flags",
                "Run out-of-sample validation before automation",
            ],
        ),
    )
