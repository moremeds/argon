from pathlib import Path


MIGRATION = Path("src/uw_scan/storage/migrations/002_expand_v1_tables.sql")


def test_v1_expansion_creates_missing_design_tables():
    sql = MIGRATION.read_text()
    for table in [
        "flow_events",
        "option_surface_snapshots",
        "exposures_by_expiry_strike",
        "oi_by_strike",
        "oi_change_events",
        "iv_rank_history",
        "iv_term_snapshots",
        "interpolated_iv_snapshots",
        "realized_volatility_history",
        "risk_reversal_skew_history",
        "max_pain_by_expiry",
        "dark_pool_events",
        "short_interest_snapshots",
        "tracked_items",
        "tracking_observations",
        "structure_ideas",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS uw_scan.{table}" in sql


def test_v1_expansion_records_schema_version():
    assert "002_expand_v1_tables" in MIGRATION.read_text()


def test_flow_events_preserves_contract_fields_for_snapshot_replay():
    sql = MIGRATION.read_text()

    assert "expiry DATE" in sql
    assert "strike NUMERIC" in sql
    assert "option_type TEXT" in sql
    assert "dte INTEGER" in sql
    assert "ALTER TABLE uw_scan.flow_events ADD COLUMN IF NOT EXISTS expiry DATE" in sql
