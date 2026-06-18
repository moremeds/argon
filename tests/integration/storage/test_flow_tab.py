"""Integration tests for Flow Tab Merge repository helpers (spec 2026-05-13)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models import MarketAggregates, OptionChainPerStrikeRow, OptionsDailyRow


def test_options_volume_daily_round_trip(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_options_volume_daily(
        "GOOGL",
        [
            OptionsDailyRow(
                date=date.today(),
                call_volume=1_000,
                put_volume=400,
                avg_30_day_call_volume=Decimal("950.5"),
            )
        ],
    )
    repo.conn.commit()
    rows = repo.get_options_timeline("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 1_000
    assert rows[0].avg_30_day_call_volume == Decimal("950.5")


def test_options_volume_daily_idempotent(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    today = date.today()
    repo.upsert_options_volume_daily(
        "GOOGL", [OptionsDailyRow(date=today, call_volume=1_000)]
    )
    repo.upsert_options_volume_daily(
        "GOOGL", [OptionsDailyRow(date=today, call_volume=2_222)]
    )
    repo.conn.commit()
    rows = repo.get_options_timeline("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 2_222


def test_option_chain_per_strike_round_trip(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    snap = date.today()
    repo.upsert_option_chain_per_strike(
        "GOOGL",
        snap,
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                call_volume=500,
                put_volume=300,
                call_oi=10_000,
                put_oi=8_000,
            )
        ],
    )
    repo.conn.commit()
    rows = repo.get_option_chain_per_strike("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 500
    assert rows[0].put_oi == 8_000


def test_latest_run_id_skips_flow_data_refresh_runs(seeded_db_empty_cards) -> None:
    """flow_data_refresh writes a scan_runs row that must NOT shadow the real
    full-scan run the report assembler relies on for flow_alerts / GEX / vol.
    """
    repo = seeded_db_empty_cards
    full_run = repo.insert_scan_run("GOOGL", notes="full_scan")
    repo.set_aggregates(
        full_run, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
    repo.finish_scan_run(full_run, status="ok")
    refresh_run = repo.insert_scan_run("GOOGL", notes="flow_data_refresh")
    repo.finish_scan_run(refresh_run, status="ok")
    repo.conn.commit()

    assert refresh_run > full_run  # sanity: refresh would otherwise win on run_id
    assert repo.latest_run_id("GOOGL") == full_run


def test_latest_run_id_skips_failed_runs(seeded_db_empty_cards) -> None:
    """A failed full-scan (e.g. UW HTTP 429 daily-quota hit) commits a
    scan_runs row with ``status`` set to ``failed: …`` but leaves the
    per-run exposures / aggregates / gex_curve unwritten. Without the
    status filter, ``latest_run_id`` would return the failed run and the
    report assembler would join on a run_id with no detail rows, producing
    an empty stock detail page.
    """
    repo = seeded_db_empty_cards
    full_run = repo.insert_scan_run("GOOGL", notes="full_scan")
    repo.set_aggregates(
        full_run, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
    repo.finish_scan_run(full_run, status="ok")
    failed_run = repo.insert_scan_run("GOOGL", notes="full_scan")
    repo.finish_scan_run(failed_run, status="failed: UwHTTPError('UW HTTP 429')")
    repo.conn.commit()

    assert failed_run > full_run  # sanity: failed run would otherwise win
    assert repo.latest_run_id("GOOGL") == full_run


def test_latest_run_id_skips_side_channel_refresh_runs(seeded_db_empty_cards) -> None:
    """positioning_refresh / intraday_refresh / cockpit_daily_snapshot each
    insert a scan_runs row that populates only a narrow slice of tables
    (uw_positioning, option_chain_oi, cockpit greeks respectively) and must
    NOT shadow the real full-scan run the report assembler reads from.
    """
    repo = seeded_db_empty_cards
    full_run = repo.insert_scan_run("GOOGL", notes="full_scan")
    repo.set_aggregates(
        full_run, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
    repo.finish_scan_run(full_run, status="ok")
    for note in ("positioning_refresh", "intraday_refresh", "cockpit_daily_snapshot"):
        shadow = repo.insert_scan_run("GOOGL", notes=note)
        repo.finish_scan_run(shadow, status="ok")
        repo.conn.commit()
        assert shadow > full_run, f"{note} sanity: shadow would otherwise win"
        assert repo.latest_run_id("GOOGL") == full_run, (
            f"{note} shadow was not excluded"
        )


def test_option_chain_per_strike_returns_only_latest_snapshot(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    older = date(2026, 5, 1)
    newer = date(2026, 5, 13)
    repo.upsert_option_chain_per_strike(
        "GOOGL",
        older,
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                call_volume=100,
            )
        ],
    )
    repo.upsert_option_chain_per_strike(
        "GOOGL",
        newer,
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                call_volume=999,
            )
        ],
    )
    repo.conn.commit()
    rows = repo.get_option_chain_per_strike("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 999
