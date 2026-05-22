"""Integration tests for bulk_upsert_watchlist_card_spots (Phase 1, Task 1.3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def test_bulk_upsert_watchlist_card_spots(seeded_db_with_cards):
    """Update only spot/spot_quoted_at/spot_source on existing cards; rows
    without a card are silently skipped (the WS consumer doesn't create cards).

    `seeded_db_with_cards` provides one TSLA card by default. We use TSLA
    (real card) + a synthetic "NOTACARD" ticker (no row → must be skipped).
    """
    repo = seeded_db_with_cards
    ts = datetime.now(timezone.utc)
    rows = [
        ("TSLA", Decimal("450.00"), ts, "massive.com_ws"),
        ("NOTACARD", Decimal("1.00"), ts, "massive.com_ws"),  # no row in watchlist_card
    ]
    repo.bulk_upsert_watchlist_card_spots(rows)
    repo._conn.commit()
    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    assert card.spot_quoted_at == ts
    assert card.spot_source == "massive.com_ws"
    # NOTACARD silently skipped — no row was created
    assert repo.get_watchlist_card("NOTACARD") is None


def test_bulk_upsert_watchlist_card_spots_empty_is_noop(seeded_db_with_cards):
    repo = seeded_db_with_cards
    repo.bulk_upsert_watchlist_card_spots([])
    # No exception.


def test_bulk_upsert_watchlist_card_spots_preserves_other_fields(seeded_db_with_cards):
    """Spot triple updates must not clobber iv_atm, iv_rank, etc."""
    repo = seeded_db_with_cards
    before = repo.get_watchlist_card("TSLA")
    iv_atm_before = before.iv_atm
    iv_rank_before = before.iv_rank

    ts = datetime.now(timezone.utc)
    repo.bulk_upsert_watchlist_card_spots(
        [("TSLA", Decimal("999.99"), ts, "massive.com_ws")]
    )
    repo._conn.commit()

    after = repo.get_watchlist_card("TSLA")
    assert after.spot == Decimal("999.99")
    assert after.iv_atm == iv_atm_before
    assert after.iv_rank == iv_rank_before
