"""Auto-caveat bookkeeping must never abort a heal run.

Found in production 2026-08-16: `count_recent_no_data` was missing from the
deployed repository, so the first `no_data` raised AttributeError out of
`_verify_and_mark` and killed both wide backfill runs -- ~27,000 queued items
stopped because an OPTIONAL optimisation failed. The caveat exists to avoid
re-trying dead scopes; it is not worth one row of repair work.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from uw_scan.worker.jobs import data_gap_adapters as A


class _Gap:
    """Gap repo whose caveat bookkeeping is broken, as the deployed one was."""

    def __init__(self, boom_on="count"):
        self.boom_on = boom_on
        self.marked: list = []

    def mark_item_no_data(self, item_id, reason=None, actual_requests=0):
        self.marked.append((item_id, reason))

    def mark_item_healed(self, item_id, actual_requests=0):
        self.marked.append((item_id, "healed"))

    def count_recent_no_data(self, dataset, ticker, data_date, *, runs):
        if self.boom_on == "count":
            raise AttributeError(
                "'DataGapHealerRepository' object has no attribute 'count_recent_no_data'"
            )
        return runs

    def upsert_caveat(self, caveat):
        if self.boom_on == "upsert":
            raise RuntimeError("caveat write failed")


def _ctx(gap):
    return A.HealContext(
        repo=MagicMock(),
        gap=gap,
        schema="uw_scan",
        today=date(2026, 8, 16),
        budget=A.RequestBudget(uw_cap=None),
        settings=type("S", (), {"data_gap_healer_no_data_caveat_after": 3})(),
    )


@pytest.mark.parametrize("boom_on", ["count", "upsert"])
def test_broken_caveat_bookkeeping_does_not_abort(monkeypatch, boom_on):
    gap = _Gap(boom_on)
    ctx = _ctx(gap)
    entry = MagicMock(table_name="oi_by_strike", audit_mode="strict_ticker_date")
    spec = MagicMock(est_per_item=2)
    item = {"id": 1, "ticker": "AAPL", "data_date": date(2026, 6, 15)}
    outcome = {"healed": 0, "no_data": 0, "auto_caveated": 0}

    monkeypatch.setattr(A, "_verify_covered", lambda *a, **k: False)

    # must not raise
    A._verify_and_mark(ctx, entry, spec, item, outcome)

    assert outcome["no_data"] == 1, "the item must still be recorded"
    assert gap.marked == [(1, "provider_no_data")]
    assert outcome["auto_caveated"] == 0, "the caveat failed, so it must not be counted"
