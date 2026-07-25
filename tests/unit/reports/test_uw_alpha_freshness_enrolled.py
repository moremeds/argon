"""MONITORED_TABLES is a SEPARATE list from the healer REGISTRY — registering a
table for heal does NOT enroll it in the freshness alert. Without this guard a
table healed but forgotten in MONITORED_TABLES would pass every healer gate while
its freshness alert never fires.
"""

from __future__ import annotations

from uw_scan.reports.data_freshness import MONITORED_TABLES

_UW_ALPHA_TABLES = (
    "uw_gex_levels_daily",
    "uw_volatility_signal_daily",
    "uw_short_pressure_daily",
    "uw_dark_lit_flow_prints",
    "uw_intraday_option_flow_bars",
)


def test_uw_alpha_tables_are_freshness_monitored():
    names = {m.name for m in MONITORED_TABLES}
    for t in _UW_ALPHA_TABLES:
        assert t in names, f"{t} missing from MONITORED_TABLES (freshness won't fire)"
