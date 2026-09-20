from __future__ import annotations

from datetime import date
from decimal import Decimal


def _row(strike: str, civ: str, piv: str) -> dict:
    return {
        "expiry": date(2026, 7, 17),
        "strike": Decimal(strike),
        "call_iv": Decimal(civ),
        "put_iv": Decimal(piv),
    }


def test_grid_upsert_accumulates_across_days_and_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d1, d2 = date(2026, 6, 18), date(2026, 6, 19)

    assert (
        repo.upsert_option_surface_grid(
            "TSLA", d1, Decimal("250"), [_row("250", "0.50", "0.52")]
        )
        == 1
    )
    assert (
        repo.upsert_option_surface_grid(
            "TSLA", d2, Decimal("255"), [_row("255", "0.48", "0.50")]
        )
        == 1
    )
    # Re-run day 1 with an updated IV — must update in place, not duplicate.
    repo.upsert_option_surface_grid(
        "TSLA", d1, Decimal("250"), [_row("250", "0.49", "0.52")]
    )
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(distinct market_date) "
            "FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'"
        )
        assert cur.fetchone() == (2, 2)  # day-1 survived day-2 write; no dup on re-run
        cur.execute(
            "SELECT call_iv FROM uw_scan.option_surface_grid_daily "
            "WHERE ticker='TSLA' AND market_date=%s",
            (d1,),
        )
        assert cur.fetchone()[0] == Decimal("0.49")  # updated in place


def test_fetch_atm_strike_returns_nearest(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d = date(2026, 6, 19)
    repo.upsert_option_surface_grid(
        "TSLA",
        d,
        Decimal("252"),
        [
            _row("245", "0.55", "0.57"),
            _row("250", "0.50", "0.52"),
            _row("260", "0.45", "0.47"),
        ],
    )
    repo.conn.commit()
    atm = repo.fetch_option_surface_atm_strike(
        "TSLA", d, date(2026, 7, 17), Decimal("252")
    )
    assert atm is not None and atm["strike"] == Decimal("250")
    assert atm["call_iv"] == Decimal("0.50")


def _put_row(strike: str, expiry: date, piv: str, pdelta: str) -> dict:
    return {
        "expiry": expiry,
        "strike": Decimal(strike),
        "put_iv": Decimal(piv),
        "put_delta": Decimal(pdelta),
    }


def test_fetch_put_chain_near_dte_picks_closest_expiry_and_walks_back(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    captured = date(2026, 6, 24)
    near_expiry = date(2026, 8, 7)  # 44 calendar days out — closer to target 45
    far_expiry = date(2026, 9, 18)  # 86 days out
    repo.upsert_option_surface_grid(
        "TSLA",
        captured,
        Decimal("382.35"),
        [
            _put_row("350", near_expiry, "0.473", "-0.25"),
            _put_row("310", near_expiry, "0.55", "-0.125"),
            _put_row("300", far_expiry, "0.60", "-0.10"),
        ],
    )
    repo.conn.commit()

    # as_of two days after the capture (no capture ran on that date) → walks back.
    chain = repo.fetch_put_chain_near_dte("TSLA", date(2026, 6, 26), 45)
    assert chain is not None
    assert chain["captured_on"] == captured
    assert chain["expiry"] == near_expiry
    assert chain["spot"] == Decimal("382.35")
    strikes = {leg["strike"] for leg in chain["legs"]}
    assert strikes == {Decimal("350"), Decimal("310")}  # far_expiry row excluded


def test_fetch_put_chain_near_dte_none_when_capture_is_stale(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    captured = date(2026, 6, 24)
    repo.upsert_option_surface_grid(
        "TSLA",
        captured,
        Decimal("382.35"),
        [
            _put_row("350", date(2026, 8, 7), "0.473", "-0.25"),
            _put_row("310", date(2026, 8, 7), "0.55", "-0.125"),
        ],
    )
    repo.conn.commit()

    # 10 days past the capture — beyond the 4-day staleness bound.
    assert repo.fetch_put_chain_near_dte("TSLA", date(2026, 7, 4), 45) is None


def test_fetch_put_chain_near_dte_none_when_only_expired_expiries(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    captured = date(2026, 6, 24)
    expired = date(2026, 6, 26)  # on/before the as_of below
    repo.upsert_option_surface_grid(
        "TSLA",
        captured,
        Decimal("382.35"),
        [
            _put_row("350", expired, "0.473", "-0.25"),
            _put_row("310", expired, "0.55", "-0.125"),
        ],
    )
    repo.conn.commit()

    assert repo.fetch_put_chain_near_dte("TSLA", date(2026, 6, 26), 45) is None


def test_fetch_put_chain_near_dte_none_when_nothing_captured(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert repo.fetch_put_chain_near_dte("NOSUCHTICK", date(2026, 6, 24), 45) is None
