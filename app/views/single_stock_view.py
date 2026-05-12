"""Streamlit view: render a SingleStockReport.

No `unsafe_allow_html`. Uses st.metric / st.columns / st.tabs / st.dataframe.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from uw_scan.models import SingleStockReport


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def _fmt_dec(value: Decimal | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _fmt_pct(value: Decimal | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * Decimal('100'):.{digits}f}%"


def render(report: SingleStockReport) -> None:
    # ----------------------- Header
    st.subheader(f"{report.ticker} — Single-Stock Analysis Card")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Spot", _fmt_dec(report.market_structure.spot))
    h2.metric("Run ID", str(report.run_id))
    h3.metric("Generated (UTC)", report.generated_at.strftime("%Y-%m-%d %H:%M:%S"))
    h4.metric(
        "Setup",
        f"{report.setup.setup_type} ({report.setup.direction})"
        if report.setup
        else "—",
    )

    st.caption(f"Short Int %: {report.short_int_note}")

    tabs = st.tabs(
        ["Market Structure", "Volatility", "Flow", "VRP", "Trade Plan", "Tables"]
    )

    # ----------------------- Market Structure
    with tabs[0]:
        st.markdown("**Market Structure**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Net GEX", _fmt_dec(report.market_structure.net_gex, 0))
        c2.metric("Call GEX", _fmt_dec(report.market_structure.total_call_gex, 0))
        c3.metric("Put GEX", _fmt_dec(report.market_structure.total_put_gex, 0))
        c4.metric(
            "Max Pain (nearest exp.)",
            _fmt_dec(report.market_structure.max_pain),
        )
        c5, c6 = st.columns(2)
        c5.metric(
            "Call DEX (OI)",
            _fmt_dec(report.market_structure.total_call_dex_oi, 0),
        )
        c6.metric(
            "Put DEX (OI)",
            _fmt_dec(report.market_structure.total_put_dex_oi, 0),
        )
        st.write(
            "Top Call OI strikes:",
            [str(s) for s in report.market_structure.top_call_oi_strikes],
        )
        st.write(
            "Top Put OI strikes:",
            [str(s) for s in report.market_structure.top_put_oi_strikes],
        )
        if report.max_pain_rows:
            df = pd.DataFrame(
                [
                    {
                        "expiry": r.expiry,
                        "max_pain": float(r.max_pain)
                        if r.max_pain is not None
                        else None,
                        "close": float(r.close) if r.close is not None else None,
                        "upper_strike": float(r.next_upper_strike)
                        if r.next_upper_strike is not None
                        else None,
                        "lower_strike": float(r.next_lower_strike)
                        if r.next_lower_strike is not None
                        else None,
                    }
                    for r in report.max_pain_rows
                ]
            )
            st.dataframe(df, use_container_width=True)

    # ----------------------- Volatility
    with tabs[1]:
        st.markdown("**Volatility Profile**")
        v = report.volatility
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("IV", _fmt_dec(v.iv, 4))
        c2.metric("RV", _fmt_dec(v.rv, 4))
        c3.metric("IV Rank", _fmt_dec(v.iv_rank, 2))
        c4.metric("IV Rank (1y)", _fmt_dec(v.iv_rank_1y, 2))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("IV 52w low", _fmt_dec(v.iv_low_52w, 4))
        c6.metric("IV 52w high", _fmt_dec(v.iv_high_52w, 4))
        c7.metric("RV 52w low", _fmt_dec(v.rv_low_52w, 4))
        c8.metric("RV 52w high", _fmt_dec(v.rv_high_52w, 4))

        c9, c10, c11 = st.columns(3)
        c9.metric("IV %ile @30d", _fmt_dec(v.iv_percentile_30d, 3))
        c10.metric("Implied move @30d", _fmt_pct(v.implied_move_30d_perc))
        c11.metric("Skew (25Δ RR)", _fmt_dec(v.skew_25d, 4))

        if v.term_dte_to_iv:
            term_df = pd.DataFrame(
                [{"dte": d, "iv": float(iv)} for d, iv in v.term_dte_to_iv]
            ).sort_values("dte")
            st.line_chart(term_df.set_index("dte"))

    # ----------------------- Flow
    with tabs[2]:
        st.markdown("**Flow Snapshot**")
        f = report.flow
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Flow rows", str(f.flow_count))
        c2.metric("Net premium", _fmt_money(f.net_premium))
        c3.metric("Bull premium", _fmt_money(f.bull_premium))
        c4.metric("Bear premium", _fmt_money(f.bear_premium))
        c5, c6 = st.columns(2)
        c5.metric("Ask-side premium", _fmt_money(f.ask_side_premium))
        c6.metric("Bid-side premium", _fmt_money(f.bid_side_premium))

        if f.top_alerts:
            alerts_df = pd.DataFrame(
                [
                    {
                        "id": a.id[:8],
                        "type": a.type,
                        "expiry": a.expiry,
                        "strike": float(a.strike) if a.strike is not None else None,
                        "price": float(a.price) if a.price is not None else None,
                        "total_size": a.total_size,
                        "total_premium": float(a.total_premium)
                        if a.total_premium is not None
                        else None,
                        "vol_oi": float(a.volume_oi_ratio)
                        if a.volume_oi_ratio is not None
                        else None,
                        "rule": a.alert_rule,
                    }
                    for a in f.top_alerts
                ]
            )
            st.dataframe(alerts_df, use_container_width=True)

    # ----------------------- VRP
    with tabs[3]:
        st.markdown("**Volatility Risk Premium**")
        v = report.vrp
        c1, c2 = st.columns(2)
        c1.metric("VRP (IV - RV)", _fmt_dec(v.vrp, 4))
        c2.metric("Signal", v.signal)
        st.info(v.note)

    # ----------------------- Trade Plan
    with tabs[4]:
        st.markdown("**Trade Plan**")
        if report.setup:
            st.write(
                f"Setup **{report.setup.setup_type}** — {report.setup.label} "
                f"(direction: {report.setup.direction}, score: {report.setup.score})"
            )
            if report.setup.confirmations:
                st.write("Confirmations:")
                for c in report.setup.confirmations:
                    st.write(f"- {c}")
            if report.setup.warnings:
                st.warning("Warnings: " + ", ".join(report.setup.warnings))
        else:
            st.write("No Type C classification on this run.")

        if report.trade_plan:
            tp = report.trade_plan
            st.write(f"Structure: **{tp.structure}** — {tp.rationale}")
            legs_df = pd.DataFrame(
                [
                    {
                        "side": leg.side,
                        "symbol": leg.option_symbol,
                        "strike": float(leg.strike),
                        "expiry": leg.expiry,
                        "mid": float(leg.mid) if leg.mid is not None else None,
                    }
                    for leg in tp.legs
                ]
            )
            st.dataframe(legs_df, use_container_width=True)
        else:
            st.write("No trade plan available (criteria not met).")

    # ----------------------- Supporting tables
    with tabs[5]:
        st.markdown("**OI Change top movers**")
        if report.oi_change_top:
            oi_df = pd.DataFrame(
                [
                    {
                        "symbol": r.option_symbol,
                        "curr_oi": r.curr_oi,
                        "oi_diff": r.oi_diff_plain,
                        "oi_change": float(r.oi_change)
                        if r.oi_change is not None
                        else None,
                        "volume": r.volume,
                        "rnk": r.rnk,
                    }
                    for r in report.oi_change_top
                ]
            )
            st.dataframe(oi_df, use_container_width=True)

        st.markdown("**Dark pool**")
        c1, c2 = st.columns(2)
        c1.metric("Print count", str(report.dark_pool_print_count))
        c2.metric("Notional", _fmt_money(report.dark_pool_notional))

        st.markdown("**Short data snapshot**")
        if report.short_data:
            sd = report.short_data
            c1, c2, c3 = st.columns(3)
            c1.metric("Shares available", str(sd.short_shares_available))
            c2.metric("Fee rate", _fmt_dec(sd.fee_rate, 4))
            c3.metric("Rebate rate", _fmt_dec(sd.rebate_rate, 4))
            st.caption(f"Snapshot at {sd.timestamp}")
        else:
            st.write("No short data snapshot persisted for this run.")
