from __future__ import annotations

from datetime import date

from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository


def test_upsert_is_idempotent_and_preserves_first_entered_at(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    kw = dict(
        ticker="AAPL",
        category="vertex",
        kind="bottom",
        extreme_date=date(2026, 7, 1),
        extreme_price=195.5,
        state="pending",
        reason=None,
        as_of=date(2026, 7, 1),
        details={"w": "x"},
    )
    assert r.upsert_transition(**kw) is True  # first insert
    assert r.upsert_transition(**kw) is False  # ON CONFLICT DO NOTHING
    states = r.current_states("AAPL")
    assert len(states) == 1  # non-vacuity
    assert states[0]["state"] == "pending"


def test_current_state_precedence_terminal_beats_sublevel_beats_pending(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    base = dict(
        ticker="NVDA",
        category="divergence",
        kind="bottom",
        extreme_date=date(2026, 6, 15),
        extreme_price=1200.0,
        as_of=date(2026, 6, 20),
        details={},
    )
    r.upsert_transition(state="pending", reason=None, **base)
    r.upsert_transition(state="confirmed_sublevel", reason=None, **base)
    r.upsert_transition(state="confirmed_native", reason=None, **base)
    states = r.current_states("NVDA")
    assert len(states) == 1
    assert states[0]["state"] == "confirmed_native"
    assert r.list_non_terminal("NVDA") == []  # no longer promotable-in-flight
