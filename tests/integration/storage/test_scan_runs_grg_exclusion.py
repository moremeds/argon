"""latest_run_id ignores grg_scan side-channel runs.

Now enforced via the aggregates-presence property (grg_scan writes no
aggregates) rather than a named denylist entry — see
test_scan_runs_canonical_selection.py for the general guard.
"""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import MarketAggregates


def test_latest_run_id_ignores_grg_scan(seeded_db_empty_cards):
    db = seeded_db_empty_cards
    # A real SPY full-scan persists its aggregates...
    full = db.insert_scan_run("SPY", notes="")
    db.set_aggregates(full, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30")))
    db.finish_scan_run(full, status="ok")
    # ...then a later GRG audit row (synthetic ticker) that writes no aggregates.
    grg = db.insert_scan_run("GRG", notes="grg_scan")
    db.finish_scan_run(grg, status="ok")
    # SPY resolves to the real full-scan, not the GRG row.
    assert db.latest_run_id("SPY") == full
    # The synthetic GRG ticker has no renderable run of its own.
    assert db.latest_run_id("GRG") == 0
