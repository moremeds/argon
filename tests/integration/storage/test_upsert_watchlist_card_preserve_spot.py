"""Phase 6, Task 6.2 — preserve_spot flag on upsert_watchlist_card.

When WS owns the spot triple, full_scan / rescan_tick must not overwrite
the spot price (or its derived intraday returns) with their snapshot
values. The flag gates only the spot triple + return triple — all
analytical fields (IV, GEX, etc.) still upsert as normal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def test_upsert_with_preserve_spot_does_not_overwrite_spot(seeded_db_with_cards):
    repo = seeded_db_with_cards
    ws_ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    repo.bulk_upsert_watchlist_card_spots(
        [("TSLA", Decimal("450.00"), ws_ts, "massive.com_ws")]
    )
    repo._conn.commit()

    existing = repo.get_watchlist_card("TSLA")
    full_scan_ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=full_scan_ts,
        spot=Decimal("999.99"),
        spot_quoted_at=full_scan_ts,
        spot_source="uw_scan",
        preserve_spot=True,
    )

    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    assert card.spot_source == "massive.com_ws"
    assert card.spot_quoted_at == ws_ts


def test_upsert_with_preserve_spot_also_preserves_returns(seeded_db_with_cards):
    """A13: when WS owns spot, it also owns the intraday return triple.
    full_scan computing returns against its snapshot would drift the
    dashboard return numbers away from the WS spot."""
    repo = seeded_db_with_cards
    ws_ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    # Use bulk_upsert_watchlist_card_quotes (the WS writer's path) so the
    # returns columns get populated alongside the spot triple.
    repo.bulk_upsert_watchlist_card_quotes(
        [
            (
                "TSLA",
                Decimal("450.00"),
                ws_ts,
                "massive.com_ws",
                Decimal("0.02"),
                Decimal("0.05"),
                Decimal("0.10"),
            )
        ]
    )
    repo._conn.commit()

    existing = repo.get_watchlist_card("TSLA")
    full_scan_ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=full_scan_ts,
        spot=Decimal("999.99"),
        spot_quoted_at=full_scan_ts,
        spot_source="uw_scan",
        ret_1d=Decimal("0.99"),
        ret_1w=Decimal("0.99"),
        ret_30d=Decimal("0.99"),
        preserve_spot=True,
    )

    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    assert card.ret_1d == Decimal("0.02")
    assert card.ret_1w == Decimal("0.05")
    assert card.ret_30d == Decimal("0.10")


def test_upsert_without_preserve_spot_overwrites(seeded_db_with_cards):
    """Backward-compat — without the flag the existing path still overwrites."""
    repo = seeded_db_with_cards
    existing = repo.get_watchlist_card("TSLA")
    ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=ts,
        spot=Decimal("999.99"),
        spot_quoted_at=ts,
        spot_source="uw_scan",
    )

    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("999.99")
    assert card.spot_source == "uw_scan"


def test_upsert_with_preserve_spot_still_upserts_analytical_fields(
    seeded_db_with_cards,
):
    """Non-spot fields (iv_atm, iv_rank, etc.) still take the new value."""
    repo = seeded_db_with_cards
    existing = repo.get_watchlist_card("TSLA")
    ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=ts,
        spot=Decimal("999.99"),
        spot_quoted_at=ts,
        spot_source="uw_scan",
        iv_atm=Decimal("0.42"),
        iv_rank=Decimal("88.0"),
        preserve_spot=True,
    )
    card = repo.get_watchlist_card("TSLA")
    # spot was preserved from the seed (445.12)
    assert card.spot == Decimal("445.12")
    # analytics were updated
    assert card.iv_atm == Decimal("0.42")
    assert card.iv_rank == Decimal("88.0")
