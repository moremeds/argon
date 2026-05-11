from __future__ import annotations

import pandas as pd
import streamlit as st

from uw_scan.config import UwScanConfig
from uw_scan.ingest.planner import SourceCandidate, build_call_plan
from uw_scan.ingest.pipeline import dashboard_for_mode
from uw_scan.models import StockAnalysis
from uw_scan.storage.repository import (
    apply_migrations,
    connect_db,
    list_snapshot_summaries,
    load_dashboard_snapshot,
    save_dashboard_snapshot,
)


def _opportunities_df(dashboard):
    return pd.DataFrame(
        [
            {
                "Ticker": row.ticker,
                "Contract": row.contract_label,
                "Direction": row.direction.value,
                "Score": row.score,
                "Setups": ", ".join(row.setup_types),
                "Sources": ", ".join(row.source_labels),
                "Structure": row.structure_idea.structure_type if row.structure_idea else "",
                "Warnings": ", ".join(row.warnings),
            }
            for row in dashboard.opportunities
        ]
    )


def _flow_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.flow_rows])


def _tracked_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.tracked_items])


def _surface_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.surface_metrics])


def _analysis_df(dashboard):
    return pd.DataFrame(
        [
            {
                "Ticker": row.ticker,
                "Score": row.score,
                "Thesis": " / ".join(row.setup_types),
                "Evidence": " | ".join(row.confirmations),
                "Risk": " | ".join(row.warnings) if row.warnings else "No major warning in current view",
                "Structure Rationale": row.structure_idea.rationale if row.structure_idea else "",
                "Invalidation": row.structure_idea.invalidation if row.structure_idea else "",
            }
            for row in dashboard.opportunities
        ]
    )


def _stock_analysis_options(dashboard) -> list[str]:
    tickers = [analysis.ticker for analysis in dashboard.stock_analyses]
    return tickers or [row.ticker for row in dashboard.opportunities]


def _escape_money_markdown(value: str) -> str:
    return value.replace("$", r"\$")


def _metric_grid(metrics, columns: int = 4):
    for index in range(0, len(metrics), columns):
        row = st.columns(columns)
        for col, metric in zip(row, metrics[index : index + columns], strict=False):
            if isinstance(metric, tuple):
                label, value, note = metric
            else:
                label, value, note = metric.label, metric.value, metric.note
            col.markdown(f"**{_escape_money_markdown(str(label))}**")
            col.markdown(_escape_money_markdown(str(value)))
            if note:
                col.caption(_escape_money_markdown(str(note)))


def _mini_metric(label: str, value: str, note: str | None = None):
    st.markdown(
        f"""
        <div class="uw-mini-metric">
          <div class="uw-mini-label">{label}</div>
          <div class="uw-mini-value">{_escape_money_markdown(value)}</div>
          {f'<div class="uw-mini-note">{_escape_money_markdown(note)}</div>' if note else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _inject_analysis_css():
    st.markdown(
        """
        <style>
        .uw-board-header {
            border: 1px solid rgba(49, 51, 63, .18);
            border-radius: 8px;
            padding: 14px 16px;
            margin: 4px 0 14px 0;
            background: #f7f9fc;
        }
        .uw-board-title {
            font-size: 1.25rem;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .uw-board-thesis {
            color: #31333f;
            line-height: 1.35;
            margin: 0;
        }
        .uw-mini-metric {
            border: 1px solid rgba(49, 51, 63, .14);
            border-radius: 8px;
            padding: 9px 10px;
            margin-bottom: 8px;
            background: #fff;
            min-height: 78px;
        }
        .uw-mini-label {
            color: #6b7280;
            font-size: .78rem;
            line-height: 1.1;
        }
        .uw-mini-value {
            font-weight: 700;
            font-size: 1rem;
            line-height: 1.2;
            margin-top: 3px;
            overflow-wrap: anywhere;
        }
        .uw-mini-note {
            color: #6b7280;
            font-size: .76rem;
            margin-top: 3px;
            line-height: 1.15;
        }
        .uw-section-note {
            border-left: 3px solid #4b5563;
            padding: 6px 10px;
            background: #fafafa;
            margin: 6px 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_scenarios(analysis: StockAnalysis):
    tone_prefix = {"bull": "Bull", "base": "Base", "bear": "Bear"}
    for scenario in analysis.scenarios:
        st.markdown(
            f"**{tone_prefix.get(scenario.tone, scenario.tone.title())}:** "
            f"{_escape_money_markdown(scenario.text)}"
        )


def _render_stock_analysis(analysis: StockAnalysis):
    _inject_analysis_css()
    st.subheader("Analysis Board")
    st.markdown(
        f"""
        <div class="uw-board-header">
          <div class="uw-board-title">{analysis.ticker} - {_escape_money_markdown(analysis.live_price)} - {analysis.signal}</div>
          <p class="uw-board-thesis">{_escape_money_markdown(analysis.thesis)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("**Executive Summary**")
    summary_cols = st.columns(6)
    summary_metrics = [
        ("Score", analysis.score, None),
        ("IV Rank", analysis.iv_rank, None),
        ("Net Premium", analysis.net_premium_1d, None),
        ("GEX Flip", analysis.gex_flip, None),
        ("OI Signal", analysis.oi_signal, None),
        ("Data", analysis.data_date, None),
    ]
    for col, (label, value, note) in zip(summary_cols, summary_metrics, strict=False):
        with col:
            _mini_metric(label, value, note)

    summary_left, summary_mid, summary_right = st.columns([1.25, 1, 1])
    with summary_left:
        st.markdown("**Scenarios**")
        _render_scenarios(analysis)
    with summary_mid:
        st.markdown("**Conviction**")
        st.markdown(_escape_money_markdown(analysis.conviction))
        st.markdown("**Risk**")
        st.markdown(_escape_money_markdown(analysis.risk))
    with summary_right:
        st.markdown("**Watch**")
        st.markdown(_escape_money_markdown(analysis.watch))

    section_tabs = st.tabs(["Market Structure", "Volatility", "Flow & Positioning", "VRP", "Trade Plan"])

    with section_tabs[0]:
        left, right = st.columns([1.1, 1])
        with left:
            st.markdown(f"**Market Structure score: {analysis.market_structure.score}**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Strike": level.strike,
                            "Net GEX": level.net_gex,
                            "Level": f"{level.level} *" if level.key else level.level,
                        }
                        for level in analysis.market_structure.levels
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        with right:
            _mini_metric("GEX Flip", analysis.market_structure.gex_flip)
            st.markdown(f"<div class='uw-section-note'>{_escape_money_markdown(analysis.market_structure.dealer_positioning)}</div>", unsafe_allow_html=True)
            _mini_metric("Volume DEX", analysis.market_structure.volume_dex)
            _mini_metric("Charm Bias", analysis.market_structure.charm_bias)
            _mini_metric("Vanna Bias", analysis.market_structure.vanna_bias)

    with section_tabs[1]:
        st.markdown(f"**Volatility score: {analysis.volatility.score}**")
        vol_cols = st.columns(3)
        vol_metrics = [
            ("IV / HV", analysis.volatility.iv_hv, None),
            ("IV Rank", analysis.volatility.iv_rank, None),
            ("VRP", analysis.volatility.vrp, None),
            ("52w IV Range", analysis.volatility.iv_52w_range, None),
            ("52w RV Range", analysis.volatility.rv_52w_range, None),
            ("Skew", analysis.volatility.skew, None),
        ]
        for index, metric in enumerate(vol_metrics):
            with vol_cols[index % 3]:
                _mini_metric(*metric)
        st.markdown("**Term Structure**")
        st.markdown(_escape_money_markdown(analysis.volatility.term_structure))
        st.caption(_escape_money_markdown(analysis.volatility.api_note))

    with section_tabs[2]:
        st.markdown(f"**Flow & Positioning: {analysis.flow_positioning.score} + {analysis.flow_positioning.positioning_score}**")
        flow_cols = st.columns(3)
        flow_metrics = [
            ("Net Premium", analysis.flow_positioning.net_premium, None),
            ("Bull / Bear Prem", analysis.flow_positioning.bull_bear_premium, None),
            ("C/P Ratio", analysis.flow_positioning.call_put_ratio, None),
            ("Dark Pool", analysis.flow_positioning.dark_pool, None),
            ("Short Interest [T+1]", analysis.flow_positioning.short_interest, None),
            ("Squeeze Risk [T+1]", analysis.flow_positioning.squeeze_risk, None),
        ]
        for index, metric in enumerate(flow_metrics):
            with flow_cols[index % 3]:
                _mini_metric(*metric)
        st.markdown("**OI Changes [T+1]**")
        st.dataframe(pd.DataFrame([row.model_dump() for row in analysis.flow_positioning.oi_changes]), width="stretch", hide_index=True)
        st.markdown(f"**Bias:** {_escape_money_markdown(analysis.flow_positioning.oi_bias)}")
        st.caption(_escape_money_markdown(analysis.flow_positioning.data_note))

    with section_tabs[3]:
        st.markdown(f"**VRP Assessment - {analysis.vrp_assessment.signal}**")
        st.markdown(_escape_money_markdown(analysis.vrp_assessment.summary))
        _metric_grid(analysis.vrp_assessment.metrics, columns=3)
        st.markdown(f"**Reason:** {_escape_money_markdown(analysis.vrp_assessment.reason)}")

    with section_tabs[4]:
        st.markdown(f"**{analysis.trade_plan.title}**")
        st.markdown(_escape_money_markdown(analysis.trade_plan.structure))
        _metric_grid(analysis.trade_plan.metrics, columns=5)
        st.markdown("**Reasoning**")
        st.markdown(_escape_money_markdown(analysis.trade_plan.reasoning))
        st.markdown("**Management Plan**")
        for item in analysis.trade_plan.management_plan:
            st.markdown(f"- {_escape_money_markdown(item)}")


def _request_plan_df(dashboard, config: UwScanConfig):
    candidates = [
        SourceCandidate(ticker=row.ticker, option_symbol=row.option_symbol, source_label=row.source_label)
        for row in dashboard.flow_rows
    ]
    for source in dashboard.watchlist_sources:
        candidates.extend(
            SourceCandidate(ticker=symbol, option_symbol=None, source_label=source.source.label)
            for symbol in source.imported_symbols
        )
    plan = build_call_plan(candidates, market_date=str(dashboard.generated_at_utc.date()), config=config)
    return pd.DataFrame([call.__dict__ for call in plan.calls])


def _render_notices(notices):
    for notice in notices:
        if notice.level == "warning":
            st.warning(notice.message)
        elif notice.level == "error":
            st.error(notice.message)
        else:
            st.info(notice.message)


def _default_mode_index(config: UwScanConfig) -> int:
    return 1 if config.api_key else 0


def render_sidebar(config: UwScanConfig):
    st.sidebar.header("Controls")
    mode = st.sidebar.radio("Run mode", ["Fixture", "Live polling", "Snapshot replay"], index=_default_mode_index(config))
    st.sidebar.number_input("Polling interval seconds", min_value=15, max_value=600, value=config.poll_seconds, step=15)
    st.sidebar.text_input("TradingView shared URL", value="https://www.tradingview.com/watchlists/326877343/")
    st.sidebar.number_input("Max requests per cycle", min_value=25, max_value=1000, value=config.max_requests_per_cycle, step=25)
    st.sidebar.caption("UW API key: configured" if config.api_key else "UW API key: not configured")
    actions = {
        "run_scan": st.sidebar.button("Run scan"),
        "save_snapshot": st.sidebar.button("Save snapshot"),
        "load_snapshot": st.sidebar.button("Load snapshot"),
    }
    return mode, actions


def _handle_snapshot_actions(config: UwScanConfig, dashboard, mode: str, actions):
    loaded_dashboard = dashboard
    if actions["save_snapshot"]:
        try:
            with connect_db(config) as conn:
                apply_migrations(conn)
                run_id = save_dashboard_snapshot(conn, dashboard, mode=mode.lower().replace(" ", "_"))
            st.sidebar.success(f"Saved snapshot {run_id}")
        except Exception as exc:
            st.sidebar.error(f"Snapshot save failed: {type(exc).__name__}")
    if actions["load_snapshot"]:
        try:
            with connect_db(config) as conn:
                snapshots = list_snapshot_summaries(conn)
            if snapshots:
                with connect_db(config) as conn:
                    loaded_dashboard = load_dashboard_snapshot(conn, snapshots[0].run_id)
                st.sidebar.success(f"Loaded snapshot {snapshots[0].run_id}")
            else:
                st.sidebar.warning("No saved snapshots found")
        except Exception as exc:
            st.sidebar.error(f"Snapshot load failed: {type(exc).__name__}")
    return loaded_dashboard


def render_app():
    st.set_page_config(page_title="UW Opportunity Scanner", layout="wide")
    config = UwScanConfig.from_env()
    mode, actions = render_sidebar(config)
    dashboard, notices = dashboard_for_mode(mode, config)
    dashboard = _handle_snapshot_actions(config, dashboard, mode, actions)

    st.title("UW Opportunity Scanner")
    st.caption(f"Mode: {mode} | Generated at {dashboard.generated_at_utc.isoformat()}")
    _render_notices(notices)

    budget = dashboard.request_budget
    bullish = sum(1 for row in dashboard.opportunities if row.direction.value == "bullish")
    bearish = sum(1 for row in dashboard.opportunities if row.direction.value == "bearish")
    cols = st.columns(6)
    cols[0].metric("Estimated requests", budget.total_estimated_requests)
    cols[1].metric("Flow rows", budget.flow_rows)
    cols[2].metric("Watchlist symbols", budget.watchlist_symbols)
    cols[3].metric("Deep surface capped", "Yes" if budget.capped else "No")
    cols[4].metric("Bullish / bearish", f"{bullish} / {bearish}")
    cols[5].metric("Tracked items", len(dashboard.tracked_items))

    tabs = st.tabs(
        [
            "Top Opportunities",
            "UW Flow Feed",
            "TradingView Watchlists",
            "Tracked Contracts",
            "Surface Explorer",
            "Snapshots",
        ]
    )

    with tabs[0]:
        st.subheader("Top Opportunities")
        st.dataframe(_opportunities_df(dashboard), width="stretch", hide_index=True)
        selected_ticker = st.selectbox("Analysis ticker", _stock_analysis_options(dashboard))
        selected_analysis = next(
            (row for row in dashboard.stock_analyses if row.ticker == selected_ticker),
            None,
        )
        if selected_analysis:
            _render_stock_analysis(selected_analysis)
        else:
            st.warning("No enriched single-stock analysis is available for this ticker yet.")
            st.subheader("Analysis Detail")
            st.dataframe(_analysis_df(dashboard), width="stretch", hide_index=True)

    with tabs[1]:
        st.subheader("UW Flow Feed")
        st.dataframe(_flow_df(dashboard), width="stretch", hide_index=True)
        st.subheader("Request Plan")
        st.dataframe(_request_plan_df(dashboard, config), width="stretch", hide_index=True)

    with tabs[2]:
        st.subheader("TradingView Watchlists")
        for source in dashboard.watchlist_sources:
            st.markdown(f"**{source.source.label}**")
            st.caption(f"{source.source.url} | status: {source.source.status}")
            st.write(", ".join(source.imported_symbols))

    with tabs[3]:
        st.subheader("Tracked Contracts")
        st.dataframe(_tracked_df(dashboard), width="stretch", hide_index=True)

    with tabs[4]:
        st.subheader("Surface Explorer")
        st.dataframe(_surface_df(dashboard), width="stretch", hide_index=True)

    with tabs[5]:
        st.subheader("Snapshots")
        st.dataframe(pd.DataFrame([row.model_dump() for row in dashboard.snapshots]), width="stretch", hide_index=True)


if __name__ == "__main__":
    render_app()
