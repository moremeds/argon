"""Integration tests for Volatility Tab v2 repo helpers (spec 2026-05-13)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models import GreeksRow, RealizedVolRow, VolStatsRow
from uw_scan.sources.ohlc import OhlcBar


def test_upsert_and_fetch_index_ohlc(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    bars = [
        OhlcBar(
            ticker="SPY",
            date=date(2026, 5, 11),
            open=Decimal("500"),
            high=Decimal("502"),
            low=Decimal("499"),
            close=Decimal("501"),
            volume=10_000_000,
        ),
        OhlcBar(
            ticker="SPY",
            date=date(2026, 5, 12),
            open=Decimal("501"),
            high=Decimal("504"),
            low=Decimal("500"),
            close=Decimal("503"),
            volume=11_000_000,
        ),
    ]
    n = repo.upsert_index_ohlc_rows(bars)
    assert n == 2
    repo.conn.commit()

    series = repo.fetch_index_ohlc_series(
        "SPY", start=date(2026, 5, 11), end=date(2026, 5, 12)
    )
    assert len(series) == 2
    assert series[0]["close"] == Decimal("501")
    assert series[1]["close"] == Decimal("503")

    # Idempotent update.
    repo.upsert_index_ohlc_rows(
        [
            OhlcBar(
                ticker="SPY",
                date=date(2026, 5, 11),
                open=None,
                high=None,
                low=None,
                close=Decimal("500.50"),
                volume=None,
            )
        ]
    )
    repo.conn.commit()
    again = repo.fetch_index_ohlc_series(
        "SPY", start=date(2026, 5, 11), end=date(2026, 5, 11)
    )
    assert again[0]["close"] == Decimal("500.50")


def test_upsert_and_fetch_iv_smile(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    rows = [
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 13),
            "expiry": date(2026, 5, 15),
            "strike": Decimal("400"),
            "iv": Decimal("0.72"),
        },
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 13),
            "expiry": date(2026, 5, 15),
            "strike": Decimal("405"),
            "iv": Decimal("0.65"),
        },
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 13),
            "expiry": date(2026, 5, 22),
            "strike": Decimal("405"),
            "iv": Decimal("0.55"),
        },
    ]
    repo.upsert_iv_smile_rows(rows)
    repo.conn.commit()

    latest = repo.fetch_iv_smile_latest("TSLA")
    assert len(latest) == 3
    assert latest[0]["expiry"] == date(2026, 5, 15)
    assert latest[0]["strike"] == Decimal("400")
    assert latest[-1]["expiry"] == date(2026, 5, 22)


def test_upsert_and_fetch_vrp_daily(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    rows = [
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 11),
            "iv": Decimal("0.50"),
            "rv": Decimal("0.42"),
            "vrp": Decimal("0.08"),
            "vrp_z_20": Decimal("0.4"),
        },
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 12),
            "iv": Decimal("0.51"),
            "rv": Decimal("0.41"),
            "vrp": Decimal("0.10"),
            "vrp_z_20": Decimal("0.6"),
        },
    ]
    repo.upsert_vrp_daily_rows(rows)
    repo.conn.commit()
    series = repo.fetch_vrp_daily_series("TSLA", limit=10)
    assert series[0]["market_date"] == date(2026, 5, 12)
    assert series[0]["vrp"] == Decimal("0.10")
    assert series[1]["market_date"] == date(2026, 5, 11)


def test_upsert_and_fetch_stock_analytics(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    rows = [
        {
            "ticker": "TSLA",
            "market_date": date(2026, 5, 12),
            "rvol_21": Decimal("0.40"),
            "rvol_pctile": Decimal("50"),
            "spy_corr_21": Decimal("0.30"),
            "iv_of_iv_20": Decimal("0.05"),
        },
    ]
    repo.upsert_stock_analytics_rows(rows)
    repo.conn.commit()
    out = repo.fetch_stock_analytics_series("TSLA", limit=10)
    assert len(out) == 1
    assert out[0]["spy_corr_21"] == Decimal("0.30")


def test_fetch_greeks_rows_for_smile(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 5, 13)
    run_id = repo.insert_scan_run(ticker="TSLA")
    repo.insert_greeks_rows(
        run_id,
        "TSLA",
        [
            GreeksRow(
                date=today,
                expiry=date(2026, 5, 15),
                strike=Decimal("400"),
                call_volatility=Decimal("0.70"),
                put_volatility=Decimal("0.74"),
            ),
            GreeksRow(
                date=today,
                expiry=date(2026, 5, 15),
                strike=Decimal("405"),
                call_volatility=Decimal("0.66"),
                put_volatility=Decimal("0.68"),
            ),
            GreeksRow(
                date=today,
                expiry=date(2026, 5, 22),
                strike=Decimal("400"),
                call_volatility=Decimal("0.55"),
                put_volatility=Decimal("0.57"),
            ),
        ],
    )
    repo.conn.commit()
    out = repo.fetch_greeks_rows_for_smile(
        ticker="TSLA", market_date=today, expiry=date(2026, 5, 15)
    )
    assert len(out) == 2
    assert out[0]["strike"] == Decimal("400")
    assert out[1]["strike"] == Decimal("405")
    assert out[0]["call_volatility"] == Decimal("0.70")


def test_history_reads(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_realized_vol_rows(
        "TSLA",
        [
            RealizedVolRow(
                date=date.today(),
                price=Decimal("400"),
                implied_volatility=Decimal("0.5"),
                realized_volatility=Decimal("0.4"),
            ),
        ],
    )
    repo.upsert_volatility_stats_rows(
        [
            VolStatsRow(
                ticker="TSLA",
                date=date.today(),
                iv=Decimal("0.51"),
                iv_low=Decimal("0.17"),
                iv_high=Decimal("0.55"),
                iv_rank=Decimal("41"),
                rv=Decimal("0.41"),
                rv_low=Decimal("0.09"),
                rv_high=Decimal("0.37"),
            ),
        ]
    )
    repo.conn.commit()
    assert repo.count_realized_vol_history("TSLA", days=365) == 1

    rv_rows = repo.fetch_realized_vol_history("TSLA", days=365)
    assert len(rv_rows) == 1

    stats = repo.fetch_volatility_stats_history("TSLA", days=365)
    assert len(stats) == 1
    assert stats[0]["iv_rank"] == Decimal("41")


def test_backfill_status_state_machine(seeded_db_empty_cards):
    from datetime import datetime, timezone

    repo = seeded_db_empty_cards
    assert repo.get_volatility_backfill_status("TSLA") is None

    now = datetime.now(timezone.utc)
    repo.upsert_volatility_backfill_status(
        ticker="TSLA", status="running", started_at=now
    )
    repo.conn.commit()
    row = repo.get_volatility_backfill_status("TSLA")
    assert row["status"] == "running"
    assert row["started_at"] is not None

    repo.upsert_volatility_backfill_status(
        ticker="TSLA",
        status="ready",
        finished_at=now,
    )
    repo.conn.commit()
    row = repo.get_volatility_backfill_status("TSLA")
    assert row["status"] == "ready"
    # started_at should be preserved through the COALESCE clause.
    assert row["started_at"] is not None
