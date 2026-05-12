"""Streamlit view: render a ScanReport.

Header card → ranked dataframe → "Top Pick deep-dive" pivot. No unsafe_allow_html.
The deep-dive button delegates back to the single-stock pipeline via the supplied
callback so this view does not own any DB / API state.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pandas as pd
import streamlit as st

from uw_scan.models import ScanReport


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def _fmt_dec(value: Decimal | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def render(
    report: ScanReport,
    on_deep_dive: Callable[[str], None] | None = None,
) -> None:
    """Render a ScanReport. `on_deep_dive(ticker)` is invoked if user clicks the
    Top Pick deep-dive button.
    """
    st.subheader("UW Scanner — Full Scan Report (S2)")

    classified = [r for r in report.results if r.setup_type is not None]
    f_count = sum(1 for r in report.results if r.setup_type == "F")
    c_count = sum(1 for r in report.results if r.setup_type == "C")

    h1, h2, h3, h4, h5 = st.columns(5)
    h1.metric("Run ID", str(report.run_id))
    h2.metric("Universe size", str(report.universe_size))
    h3.metric("Returned", str(report.universe_returned))
    h4.metric("Classified", str(len(classified)))
    h5.metric("Top Pick", report.top_pick or "—")

    s1, s2, s3 = st.columns(3)
    s1.metric("Type F (Multi-Signal)", str(f_count))
    s2.metric("Type C (Deep Conviction)", str(c_count))
    s3.metric(
        "Scan date",
        report.scan_date.isoformat() if report.scan_date else "—",
    )

    if report.dropped_tickers:
        st.caption(
            f"Dropped (not in screener response): {', '.join(report.dropped_tickers)}"
        )

    st.markdown("**Ranked results** (sorted by score descending)")
    if not report.results:
        st.info("No results to display.")
        return

    df_rows = []
    for r in report.results:
        df_rows.append(
            {
                "ticker": r.ticker,
                "setup": r.setup_type or "—",
                "direction": r.direction or "—",
                "score": float(r.score),
                "net_premium": float(r.net_premium)
                if r.net_premium is not None
                else None,
                "iv_rank": float(r.iv_rank) if r.iv_rank is not None else None,
                "rel_vol": float(r.relative_volume)
                if r.relative_volume is not None
                else None,
                "gex_net_chg": float(r.gex_net_change)
                if r.gex_net_change is not None
                else None,
                "vrp": float(r.variance_risk_premium)
                if r.variance_risk_premium is not None
                else None,
                "oi": r.total_open_interest,
                "sector": r.sector or "—",
                "signals": ", ".join(r.signals_present) if r.signals_present else "",
            }
        )
    df = pd.DataFrame(df_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**Top Pick Deep-Dive**")

    if report.top_pick is None:
        st.info("No top pick — no rows ranked.")
        return

    top = report.results[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Top Pick", top.ticker)
    c2.metric("Setup", top.setup_type or "—")
    c3.metric("Score", _fmt_dec(top.score, 2))
    c4.metric("Net premium", _fmt_money(top.net_premium))

    if top.confirmations:
        st.write("Confirmations:")
        for c in top.confirmations:
            st.write(f"- {c}")
    if top.warnings:
        st.warning("Warnings: " + ", ".join(top.warnings))

    if on_deep_dive is not None:
        clicked = st.button(
            f"Run S1 deep-dive on {report.top_pick}",
            key=f"deep_dive_{report.run_id}_{report.top_pick}",
            type="primary",
        )
        if clicked:
            on_deep_dive(report.top_pick)
    else:
        st.caption("Deep-dive callback not wired in this view context.")
