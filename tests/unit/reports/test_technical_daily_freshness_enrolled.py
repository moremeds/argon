"""technical_daily must be enrolled in MONITORED_TABLES.

It was in the gap-healer REGISTRY but not in MONITORED_TABLES, so nothing
measured its data date. On 2026-08-23 that let MSTR sit frozen at 2026-07-15
(26 sessions) and APLD/CCJ hold zero rows, all invisible on /api/health.
Its date column is `as_of`, which is NOT in _DATE_COL_PREFERENCE — without the
explicit override the row renders date_col='?' and measures nothing at all.
"""

from uw_scan.reports.data_freshness import MONITORED_TABLES


def test_technical_daily_is_monitored():
    entry = next((m for m in MONITORED_TABLES if m.name == "technical_daily"), None)
    assert entry is not None, "technical_daily missing from MONITORED_TABLES"
    assert entry.date_col_override == "as_of", (
        "technical_daily keys on as_of, absent from _DATE_COL_PREFERENCE — "
        "without the override the freshness row measures nothing"
    )
    assert entry.scope == "watchlist"  # per-ticker coverage, not freshness-only
