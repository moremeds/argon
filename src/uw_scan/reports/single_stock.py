"""Assemble a SingleStockReport from persisted run data.

Pure function: reads from Repository (already-persisted tables), never the live API.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from datetime import date as _date
from decimal import Decimal

from ..cards.gex import compute_market_structure_levels
from ..models import (
    FlowAlert,
    FlowSnapshot,
    MarketStructure,
    MaxPainRow,
    OiChangeRow,
    ShortDataRow,
    SingleStockReport,
    StrikeGexBucket,
    TradePlan,
    TradePlanLeg,
    VolatilityProfile,
    VRPAssessment,
)
from ..storage.repository import Repository


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _safe_get(d: dict | None, key: str):
    if d is None:
        return None
    return d.get(key)


def _build_flow_snapshot(ticker: str, flow_rows: list[dict]) -> FlowSnapshot:
    bull_premium = Decimal("0")
    bear_premium = Decimal("0")
    ask_side = Decimal("0")
    bid_side = Decimal("0")
    alerts: list[FlowAlert] = []

    for r in flow_rows:
        prem = _to_decimal(r.get("total_premium")) or Decimal("0")
        opt_type = (r.get("option_type") or "").lower()
        if opt_type == "call":
            bull_premium += prem
        elif opt_type == "put":
            bear_premium += prem
        ask_side += _to_decimal(r.get("total_ask_side_prem")) or Decimal("0")
        bid_side += _to_decimal(r.get("total_bid_side_prem")) or Decimal("0")

        alerts.append(
            FlowAlert(
                id=r["alert_id"],
                ticker=r["ticker"],
                option_chain=r.get("option_chain"),
                type=opt_type or None,
                expiry=r.get("expiry"),
                strike=_to_decimal(r.get("strike")),
                price=_to_decimal(r.get("price")),
                underlying_price=_to_decimal(r.get("underlying_price")),
                total_size=r.get("total_size"),
                total_premium=prem,
                total_ask_side_prem=_to_decimal(r.get("total_ask_side_prem")),
                total_bid_side_prem=_to_decimal(r.get("total_bid_side_prem")),
                volume=r.get("volume"),
                open_interest=r.get("open_interest"),
                volume_oi_ratio=_to_decimal(r.get("volume_oi_ratio")),
                has_sweep=r.get("has_sweep"),
                has_floor=r.get("has_floor"),
                has_multileg=r.get("has_multileg"),
                all_opening_trades=r.get("all_opening_trades"),
                iv_start=_to_decimal(r.get("iv_start")),
                iv_end=_to_decimal(r.get("iv_end")),
                alert_rule=r.get("alert_rule"),
                rule_id=r.get("rule_id"),
                sector=r.get("sector"),
                issue_type=r.get("issue_type"),
                next_earnings_date=r.get("next_earnings_date"),
                created_at=r.get("created_at"),
            )
        )

    net_premium = bull_premium - bear_premium
    return FlowSnapshot(
        ticker=ticker,
        flow_count=len(flow_rows),
        net_premium=net_premium,
        bull_premium=bull_premium,
        bear_premium=bear_premium,
        ask_side_premium=ask_side,
        bid_side_premium=bid_side,
        top_alerts=alerts[:10],
    )


def _build_market_structure(
    repo: Repository, run_id: int, ticker: str, max_pain_rows: list[MaxPainRow]
) -> MarketStructure:
    exposures = repo.fetch_exposures_summary(run_id, ticker) or {}
    total_call_gex = _to_decimal(exposures.get("total_call_gex"))
    total_put_gex = _to_decimal(exposures.get("total_put_gex"))
    net_gex = None
    if total_call_gex is not None and total_put_gex is not None:
        net_gex = total_call_gex + total_put_gex

    top_calls, top_puts = repo.fetch_top_oi_strikes(ticker, limit=5)
    nearest_expiry: _date | None = None
    max_pain_val: Decimal | None = None
    if max_pain_rows:
        nearest = min(max_pain_rows, key=lambda r: r.expiry)
        nearest_expiry = nearest.expiry
        max_pain_val = nearest.max_pain

    # Spot from realized_vol latest price as fallback; from max_pain close otherwise
    spot = None
    rv = repo.fetch_realized_vol_latest(ticker)
    if rv and rv.get("price") is not None:
        spot = _to_decimal(rv["price"])
    elif max_pain_rows and max_pain_rows[0].close is not None:
        spot = max_pain_rows[0].close

    return MarketStructure(
        spot=spot,
        nearest_expiry=nearest_expiry,
        total_call_gex=total_call_gex,
        total_put_gex=total_put_gex,
        net_gex=net_gex,
        total_call_dex_oi=_to_decimal(exposures.get("total_call_dex")),
        total_put_dex_oi=_to_decimal(exposures.get("total_put_dex")),
        max_pain=max_pain_val,
        top_call_oi_strikes=top_calls,
        top_put_oi_strikes=top_puts,
    )


def _build_volatility_profile(
    repo: Repository, run_id: int, ticker: str
) -> VolatilityProfile:
    iv_rank_row = repo.fetch_iv_rank_latest(ticker) or {}
    vol_stats = repo.fetch_volatility_stats_latest(ticker) or {}
    realized = repo.fetch_realized_vol_latest(ticker) or {}
    interp = repo.fetch_interpolated_iv_30d(run_id, ticker) or {}
    skew = repo.fetch_skew_latest(ticker) or {}
    term = repo.fetch_iv_term_rows(run_id, ticker)

    term_pairs: list[tuple[int, Decimal]] = []
    for row in term:
        dte = row.get("dte")
        vol = _to_decimal(row.get("volatility"))
        if dte is not None and vol is not None:
            term_pairs.append((int(dte), vol))

    return VolatilityProfile(
        iv=_to_decimal(vol_stats.get("iv")),
        iv_rank=_to_decimal(vol_stats.get("iv_rank")),
        iv_low_52w=_to_decimal(vol_stats.get("iv_low")),
        iv_high_52w=_to_decimal(vol_stats.get("iv_high")),
        rv=_to_decimal(vol_stats.get("rv"))
        or _to_decimal(realized.get("realized_volatility")),
        rv_low_52w=_to_decimal(vol_stats.get("rv_low")),
        rv_high_52w=_to_decimal(vol_stats.get("rv_high")),
        iv_rank_1y=_to_decimal(iv_rank_row.get("iv_rank_1y")),
        iv_percentile_30d=_to_decimal(interp.get("percentile")),
        implied_move_30d_perc=_to_decimal(interp.get("implied_move_perc")),
        skew_25d=_to_decimal(skew.get("risk_reversal")),
        term_dte_to_iv=term_pairs,
    )


def _build_vrp(vol: VolatilityProfile) -> VRPAssessment:
    if vol.iv is None or vol.rv is None:
        return VRPAssessment(vrp=None, signal="unknown", note="IV or RV unavailable")
    vrp = vol.iv - vol.rv
    if vrp > Decimal("0.05"):
        signal = "rich"
        note = "IV materially above RV — vol-selling structures favored."
    elif vrp < Decimal("-0.05"):
        signal = "cheap"
        note = "IV materially below RV — long-vol structures favored."
    else:
        signal = "neutral"
        note = "IV ≈ RV — directional structures over vol bets."
    return VRPAssessment(vrp=vrp, signal=signal, note=note)


def _build_oi_change_models(rows: list[dict]) -> list[OiChangeRow]:
    out: list[OiChangeRow] = []
    for r in rows:
        out.append(
            OiChangeRow(
                underlying_symbol=r["underlying_symbol"],
                option_symbol=r["option_symbol"],
                curr_date=r.get("curr_date"),
                last_date=r.get("last_date"),
                curr_oi=r.get("curr_oi"),
                last_oi=r.get("last_oi"),
                oi_diff_plain=r.get("oi_diff_plain"),
                oi_change=_to_decimal(r.get("oi_change")),
                volume=r.get("volume"),
                trades=r.get("trades"),
                avg_price=_to_decimal(r.get("avg_price")),
                last_fill=_to_decimal(r.get("last_fill")),
                days_of_oi_increases=r.get("days_of_oi_increases"),
                days_of_vol_greater_than_oi=r.get("days_of_vol_greater_than_oi"),
                percentage_of_total=_to_decimal(r.get("percentage_of_total")),
                rnk=r.get("rnk"),
            )
        )
    return out


def _build_short_data_model(d: dict | None) -> ShortDataRow | None:
    if not d:
        return None
    return ShortDataRow(
        symbol=d["ticker"],
        timestamp=d["snapshot_at"] or datetime.now(UTC),
        name=d.get("name"),
        short_shares_available=d.get("short_shares_available"),
        fee_rate=_to_decimal(d.get("fee_rate")),
        rebate_rate=_to_decimal(d.get("rebate_rate")),
    )


def _build_trade_plan(
    direction: str, contracts: list[dict], spot: Decimal | None
) -> TradePlan | None:
    """Sketch a vertical spread aligned with direction.

    Uses option_contract_snapshots rows. Picks two strikes bracketing spot for the
    setup direction. Bull → bull call spread (buy lower strike, sell upper strike).
    Bear → bear put spread (buy upper strike, sell lower strike).
    """
    if spot is None or not contracts:
        return None

    calls = [c for c in contracts if "C" in c["option_symbol"]]
    puts = [c for c in contracts if "P" in c["option_symbol"]]

    def _strike_from_symbol(sym: str) -> Decimal | None:
        # OCC: TSLA260511C00440000 → last 8 digits = strike * 1000
        try:
            return Decimal(sym[-8:]) / Decimal("1000")
        except (ValueError, ArithmeticError) as exc:
            logging.getLogger(__name__).debug(
                "strike parse failed for %r: %s", sym, repr(exc)
            )
            return None

    def _expiry_from_symbol(sym: str) -> _date | None:
        # OCC: TSLA + YYMMDD + [CP] + strike
        try:
            base = sym.rstrip("0123456789")
            base = base[:-1]  # drop C/P
            ymd = base[-6:]
            yy = 2000 + int(ymd[:2])
            mm = int(ymd[2:4])
            dd = int(ymd[4:6])
            return _date(yy, mm, dd)
        except (ValueError, IndexError) as exc:
            logging.getLogger(__name__).debug(
                "expiry parse failed for %r: %s", sym, repr(exc)
            )
            return None

    if direction == "bull":
        if not calls:
            return None
        sorted_calls = sorted(
            calls,
            key=lambda c: abs(
                (_strike_from_symbol(c["option_symbol"]) or Decimal("0")) - spot
            ),
        )
        if len(sorted_calls) < 2:
            return None
        long_leg = sorted_calls[0]
        upper_candidates = [
            c
            for c in sorted_calls[1:]
            if (_strike_from_symbol(c["option_symbol"]) or Decimal("0"))
            > (_strike_from_symbol(long_leg["option_symbol"]) or Decimal("0"))
        ]
        if not upper_candidates:
            return None
        short_leg = upper_candidates[0]
        legs = [
            TradePlanLeg(
                option_symbol=long_leg["option_symbol"],
                side="buy",
                strike=_strike_from_symbol(long_leg["option_symbol"]) or Decimal("0"),
                expiry=_expiry_from_symbol(long_leg["option_symbol"]) or _date.today(),
                mid=_to_decimal(long_leg.get("last_price")),
            ),
            TradePlanLeg(
                option_symbol=short_leg["option_symbol"],
                side="sell",
                strike=_strike_from_symbol(short_leg["option_symbol"]) or Decimal("0"),
                expiry=_expiry_from_symbol(short_leg["option_symbol"]) or _date.today(),
                mid=_to_decimal(short_leg.get("last_price")),
            ),
        ]
        return TradePlan(
            structure="bull_call_spread",
            direction="bull",
            legs=legs,
            rationale="Buy ATM call, sell OTM call — defined-risk bullish exposure.",
        )

    # bear
    if not puts:
        return None
    sorted_puts = sorted(
        puts,
        key=lambda c: abs(
            (_strike_from_symbol(c["option_symbol"]) or Decimal("0")) - spot
        ),
    )
    if len(sorted_puts) < 2:
        return None
    long_leg = sorted_puts[0]
    lower_candidates = [
        c
        for c in sorted_puts[1:]
        if (_strike_from_symbol(c["option_symbol"]) or Decimal("0"))
        < (_strike_from_symbol(long_leg["option_symbol"]) or Decimal("0"))
    ]
    if not lower_candidates:
        return None
    short_leg = lower_candidates[0]
    legs = [
        TradePlanLeg(
            option_symbol=long_leg["option_symbol"],
            side="buy",
            strike=_strike_from_symbol(long_leg["option_symbol"]) or Decimal("0"),
            expiry=_expiry_from_symbol(long_leg["option_symbol"]) or _date.today(),
            mid=_to_decimal(long_leg.get("last_price")),
        ),
        TradePlanLeg(
            option_symbol=short_leg["option_symbol"],
            side="sell",
            strike=_strike_from_symbol(short_leg["option_symbol"]) or Decimal("0"),
            expiry=_expiry_from_symbol(short_leg["option_symbol"]) or _date.today(),
            mid=_to_decimal(short_leg.get("last_price")),
        ),
    ]
    return TradePlan(
        structure="bear_put_spread",
        direction="bear",
        legs=legs,
        rationale="Buy ATM put, sell OTM put — defined-risk bearish exposure.",
    )


def assemble_single_stock_report(
    ticker: str, run_id: int, repo: Repository
) -> SingleStockReport:
    """Build a SingleStockReport from persisted run data."""
    ticker = ticker.upper()
    flow_rows = repo.fetch_flow_alerts_for_ticker(run_id, ticker)
    flow = _build_flow_snapshot(ticker, flow_rows)

    max_pain_rows_raw = repo.fetch_max_pain_rows(run_id, ticker)
    max_pain_rows: list[MaxPainRow] = []
    for r in max_pain_rows_raw:
        max_pain_rows.append(
            MaxPainRow(
                expiry=r["expiry"],
                max_pain=_to_decimal(r.get("max_pain")),
                close=_to_decimal(r.get("close")),
                open=_to_decimal(r.get("open")),
                next_upper_strike=_to_decimal(r.get("next_upper_strike")),
                next_lower_strike=_to_decimal(r.get("next_lower_strike")),
            )
        )

    market_structure = _build_market_structure(repo, run_id, ticker, max_pain_rows)
    vol = _build_volatility_profile(repo, run_id, ticker)
    vrp = _build_vrp(vol)

    dp_count, dp_notional = repo.fetch_dark_pool_summary(run_id)
    short_data = _build_short_data_model(repo.fetch_short_interest_snapshot(run_id))
    oi_change_top = _build_oi_change_models(repo.fetch_oi_change_top(run_id, limit=10))

    curve_raw = repo.get_strike_gex_curve(run_id)
    strike_gex_curve = [
        StrikeGexBucket(
            strike=Decimal(str(row["strike"])),
            expiry=_date.fromisoformat(row["expiry"]),
            net_gex=Decimal(str(row["net_gex"]))
            if row.get("net_gex") is not None
            else None,
            call_gex=Decimal(str(row["call_gex"]))
            if row.get("call_gex") is not None
            else None,
            put_gex=Decimal(str(row["put_gex"]))
            if row.get("put_gex") is not None
            else None,
        )
        for row in curve_raw
    ]
    aggregates = repo.get_aggregates(run_id)

    market_structure_levels = compute_market_structure_levels(
        strike_gex_curve, market_structure.spot
    )

    return SingleStockReport(
        run_id=run_id,
        ticker=ticker,
        generated_at=datetime.now(UTC),
        market_structure=market_structure,
        volatility=vol,
        flow=flow,
        vrp=vrp,
        setup=None,
        trade_plan=None,
        dark_pool_notional=dp_notional,
        dark_pool_print_count=dp_count,
        short_data=short_data,
        max_pain_rows=max_pain_rows,
        oi_change_top=oi_change_top,
        strike_gex_curve=strike_gex_curve,
        aggregates=aggregates,
        market_structure_levels=market_structure_levels,
    )


def build_trade_plan_for_report(
    report: SingleStockReport, contracts: list[dict]
) -> TradePlan | None:
    """Build trade plan after setup classification."""
    if report.setup is None:
        return None
    return _build_trade_plan(
        report.setup.direction, contracts, report.market_structure.spot
    )
