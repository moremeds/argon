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
