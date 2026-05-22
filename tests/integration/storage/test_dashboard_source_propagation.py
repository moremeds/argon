"""R7: dashboard SQL must propagate intraday_quote.source rather than the
legacy hardcoded "massive.com_intraday" label. Without this, WS-written
ticks would show up in the dashboard with the wrong source string."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def test_dashboard_shows_ws_source_when_ws_writes(seeded_db_with_cards):
    """When intraday_quote.source='massive.com_ws' and quoted_at is newer
    than the card's spot_quoted_at, the dashboard row surfaces the WS
    source label."""
    repo = seeded_db_with_cards
    ts = datetime.now(timezone.utc)
    repo.upsert_intraday_quote("TSLA", Decimal("450.00"), ts, source="massive.com_ws")

    rows, _ = repo.list_watchlist_cards_with_queue_summary()
    tsla = next(r for r in rows if r.ticker == "TSLA")
    assert tsla.spot == Decimal("450.00")
    assert tsla.spot_source == "massive.com_ws"


def test_dashboard_shows_card_source_when_card_is_newer(seeded_db_with_cards):
    """When the card's spot_quoted_at is newer (e.g., full_scan wrote
    spot recently and no WS tick has arrived since), the dashboard
    surfaces c.spot_source, not q.source."""
    repo = seeded_db_with_cards
    older = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 5, 21, 11, 0, tzinfo=timezone.utc)

    # Intraday quote is OLDER
    repo.upsert_intraday_quote(
        "TSLA", Decimal("400.00"), older, source="massive.com_ws"
    )
    # Card's spot_quoted_at is NEWER (manually set; mirrors full_scan path
    # when WS is disabled)
    existing = repo.get_watchlist_card("TSLA")
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=newer,
        spot=Decimal("480.00"),
        spot_quoted_at=newer,
        spot_source="uw_scan",
    )

    rows, _ = repo.list_watchlist_cards_with_queue_summary()
    tsla = next(r for r in rows if r.ticker == "TSLA")
    assert tsla.spot == Decimal("480.00")
    assert tsla.spot_source == "uw_scan"


def test_get_intraday_quote_includes_source(seeded_db_empty_cards):
    """Direct repo read also surfaces the source for the API layer
    (used by /api/stock/{ticker}._with_latest_spot)."""
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    repo.upsert_intraday_quote("TSLA", Decimal("450.00"), ts, source="massive.com_ws")

    quote = repo.get_intraday_quote("TSLA")
    assert quote is not None
    assert quote.source == "massive.com_ws"
