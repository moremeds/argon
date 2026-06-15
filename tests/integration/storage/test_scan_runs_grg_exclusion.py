"""latest_run_id must ignore grg_scan side-channel runs (defense-in-depth)."""

from __future__ import annotations


def test_latest_run_id_ignores_grg_scan(seeded_db_empty_cards):
    db = seeded_db_empty_cards
    # A real SPY full-scan, then a later GRG audit row (synthetic ticker).
    full = db.insert_scan_run("SPY", notes="")
    db.finish_scan_run(full, status="ok")
    grg = db.insert_scan_run("GRG", notes="grg_scan")
    db.finish_scan_run(grg, status="ok")
    # SPY resolves to the real full-scan, not the GRG row.
    assert db.latest_run_id("SPY") == full
    # The synthetic GRG ticker is also excluded for its own ticker.
    assert db.latest_run_id("GRG") == 0
