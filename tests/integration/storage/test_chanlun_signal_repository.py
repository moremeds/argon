from __future__ import annotations

from datetime import date, datetime, timezone

from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository


def test_upsert_is_idempotent_and_preserves_first_entered_at(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    t0 = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 8, 9, 15, tzinfo=timezone.utc)
    kw = dict(
        ticker="AAPL",
        category="vertex",
        kind="bottom",
        extreme_date=date(2026, 7, 1),
        extreme_price=195.5,
        state="pending",
        reason=None,
        details={"w": "x"},
    )
    assert (
        r.upsert_transition(as_of=date(2026, 7, 1), first_entered_at=t0, **kw) is True
    )  # first insert
    # Same mark_id + state, DIFFERENT first_entered_at and as_of: the conflict
    # must DO NOTHING — no row inserted, original first_entered_at untouched.
    assert (
        r.upsert_transition(as_of=date(2026, 7, 8), first_entered_at=t1, **kw) is False
    )
    states = r.current_states("AAPL")
    assert len(states) == 1  # non-vacuity
    assert states[0]["state"] == "pending"
    assert states[0]["first_entered_at"] == t0  # preserved, not overwritten to t1
    assert states[0]["as_of"] == date(2026, 7, 1)  # original row wholly intact


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


def test_terminal_tie_break_uses_as_of_not_insert_order(seeded_db_empty_cards):
    # A mark can hold at most ONE row per state (unique key includes state), so
    # "invalidated at D1 then re-invalidated at D3" is unrepresentable on one
    # mark — the D3 insert would be a DO-NOTHING conflict. The as_of tie-break
    # semantics are pinned on two sibling marks instead:
    #   mark A: out-of-order backfill of an OLDER invalidation must NOT win;
    #   mark B: a chronologically-LATER invalidation must win —
    # in both cases regardless of insert order.
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    d1, d2, d3 = date(2026, 6, 18), date(2026, 6, 25), date(2026, 7, 2)
    mark_a = dict(
        ticker="TSLA",
        category="point",
        kind="3B",
        extreme_date=date(2026, 6, 10),
        extreme_price=310.0,
        details={},
    )
    # Mark A: confirmation (as_of=D2) inserted FIRST, then an out-of-order
    # backfill of an OLDER invalidation (as_of=D1). Business time must win
    # over insert order: current state stays confirmed_native.
    r.upsert_transition(state="confirmed_native", reason=None, as_of=d2, **mark_a)
    r.upsert_transition(state="invalidated", reason="breach", as_of=d1, **mark_a)
    states = r.current_states("TSLA")
    assert len(states) == 1
    assert states[0]["state"] == "confirmed_native"  # D2 > D1, insert order irrelevant
    assert states[0]["as_of"] == d2

    # Mark B (sibling mark, same ticker): a LATER invalidation (as_of=D3)
    # beats the earlier confirmation (as_of=D2) at equal rank — again with the
    # inserts in reverse chronological order so insert order alone cannot pass.
    mark_b = dict(
        ticker="TSLA",
        category="point",
        kind="2B",
        extreme_date=date(2026, 5, 28),
        extreme_price=295.0,
        details={},
    )
    r.upsert_transition(state="invalidated", reason="superseded", as_of=d3, **mark_b)
    r.upsert_transition(state="confirmed_native", reason=None, as_of=d2, **mark_b)
    by_kind = {s["kind"]: s for s in r.current_states("TSLA")}
    assert len(by_kind) == 2
    assert by_kind["3B"]["state"] == "confirmed_native"
    assert by_kind["2B"]["state"] == "invalidated"
    assert by_kind["2B"]["as_of"] == d3
