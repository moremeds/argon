"""Pins the semantics of the two cockpit lookups rewritten for migration 155's
indexes: the per-table-max source date and the loose-index-scan flow lookback."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import FlowAlert, GreekExposureRow, GreeksRow, InterpolatedIvRow


def _flow(id_: str, ticker: str, day: date, premium: int) -> FlowAlert:
    return FlowAlert(
        id=id_,
        ticker=ticker,
        type="call",
        total_premium=Decimal(premium),
        created_at=datetime(day.year, day.month, day.day, 15, tzinfo=timezone.utc),
    )


def test_flow_lookback_takes_latest_n_event_days_up_to_market_date(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("SPY", notes="flow lookback")
    # Powers of two: the summed premium names exactly which events counted.
    repo.insert_flow_events(
        run_id,
        "SPY",
        [
            _flow("d11", "SPY", date(2026, 5, 11), 1),  # 4th event day — out
            _flow("d12a", "SPY", date(2026, 5, 12), 2),
            _flow("d12b", "SPY", date(2026, 5, 12), 4),  # same day, both count
            _flow("d14", "SPY", date(2026, 5, 14), 8),  # 5/13 has no events
            _flow("d15", "SPY", date(2026, 5, 15), 16),
            _flow("d18", "SPY", date(2026, 5, 18), 32),  # after market_date — out
        ],
    )
    other = repo.insert_scan_run("QQQ", notes="flow lookback other")
    repo.insert_flow_events(other, "QQQ", [_flow("q15", "QQQ", date(2026, 5, 15), 64)])
    repo.conn.commit()

    got = repo._flow_color_lookback(ticker="spy", market_date=date(2026, 5, 15))
    assert got["call_premium"] == Decimal(2 + 4 + 8 + 16)
    assert got["color"] == "call_heavy"

    none = repo._flow_color_lookback(ticker="SPY", market_date=date(2026, 5, 10))
    assert none == {
        "color": None,
        "put_premium": None,
        "call_premium": None,
        "directional_imbalance": None,
    }


def test_latest_source_market_date_is_max_across_tables(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("SPY", notes="source date")
    repo.insert_greeks_rows(
        run_id,
        "SPY",
        [
            GreeksRow(
                date=date(2026, 5, 10), expiry=date(2026, 5, 16), strike=Decimal("500")
            )
        ],
    )
    repo.insert_greek_exposure_rows(
        run_id,
        "SPY",
        [
            GreekExposureRow(
                date=date(2026, 5, 12), expiry=date(2026, 5, 16), strike=Decimal("500")
            )
        ],
    )
    repo.insert_interpolated_iv_rows(
        run_id,
        "SPY",
        [InterpolatedIvRow(date=date(2026, 5, 14), days=30, volatility=Decimal("0.2"))],
    )
    other = repo.insert_scan_run("QQQ", notes="source date other")
    repo.insert_greeks_rows(
        other,
        "QQQ",
        [
            GreeksRow(
                date=date(2026, 5, 20), expiry=date(2026, 5, 22), strike=Decimal("400")
            )
        ],
    )
    repo.conn.commit()

    assert repo.fetch_latest_cockpit_source_market_date(ticker="SPY") == date(
        2026, 5, 14
    )
    assert repo.fetch_latest_cockpit_source_market_date(ticker="IWM") is None
