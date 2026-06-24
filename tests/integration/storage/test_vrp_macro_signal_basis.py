"""basis-column coexistence for vrp_macro_signal_daily (migration 084).

Live (intraday) and eod (nightly) rows share (name, snapshot_date) but differ by
basis — they must coexist and be fetchable independently. Reuses the SPX_SKIP
fixture row from the sibling storage test."""

from __future__ import annotations

from datetime import date

from tests.integration.storage.test_vrp_macro_signal_storage import SPX_SKIP

_SNAP = date(2026, 6, 24)
_TRADE = {**SPX_SKIP, "action": "TRADE", "weight": 1.0}


def test_live_and_eod_rows_coexist(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_signal(snapshot_date=_SNAP, basis="eod", **SPX_SKIP)
    repo.upsert_vrp_macro_signal(snapshot_date=_SNAP, basis="live", **_TRADE)

    eod = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
    live = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="live")

    assert len(eod) == 1 and eod[0]["action"] == "SKIP" and eod[0]["basis"] == "eod"
    assert (
        len(live) == 1 and live[0]["action"] == "TRADE" and live[0]["basis"] == "live"
    )


def test_live_row_overwrites_in_place(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_signal(snapshot_date=_SNAP, basis="live", **_TRADE)
    repo.upsert_vrp_macro_signal(snapshot_date=_SNAP, basis="live", **SPX_SKIP)
    live = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="live")
    assert len(live) == 1 and live[0]["action"] == "SKIP"


def test_default_fetch_excludes_live_rows(seeded_db_empty_cards) -> None:
    """The existing eod endpoint path (no basis arg → 'eod') must not see live rows."""
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_signal(snapshot_date=_SNAP, basis="live", **_TRADE)
    assert repo.fetch_latest_vrp_macro_signals(["SPX"]) == []  # defaults to basis='eod'
