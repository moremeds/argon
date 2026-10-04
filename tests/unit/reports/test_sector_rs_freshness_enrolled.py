"""sector_rs_daily (migration 152) must be visible to both table gates.

A new DATE-keyed table needs a REGISTRY row, or
tests/integration/worker/test_data_gap_full_coverage.py fails on it as
unregistered. It also needs a MONITORED_TABLES row, or /api/health never
measures its data date. Its date column is `as_of`, which is absent from
_DATE_COL_PREFERENCE, so the override is mandatory.
"""

from uw_scan.reports.data_freshness import MONITORED_TABLES
from uw_scan.reports.data_gap_registry import REGISTRY


def test_sector_rs_daily_is_monitored():
    entry = next((m for m in MONITORED_TABLES if m.name == "sector_rs_daily"), None)
    assert entry is not None, "sector_rs_daily missing from MONITORED_TABLES"
    assert entry.date_col_override == "as_of"


def test_sector_rs_daily_is_registered_and_not_healer_enrolled():
    entry = next((e for e in REGISTRY if e.table_name == "sector_rs_daily"), None)
    assert entry is not None, "sector_rs_daily missing from REGISTRY"
    # spec §5: the backfill script is the heal; the healer never dispatches it
    assert entry.audit_mode == "excluded"
    assert entry.healer_adapter is None
    assert entry.date_col == "as_of"
    assert entry.ticker_col is None
    assert "sector_rs_backfill.py" in (entry.reason or "")
