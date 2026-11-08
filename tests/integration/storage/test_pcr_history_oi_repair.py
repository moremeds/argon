"""Repository.repair_pcr_history_oi rewrites the pre-fix volume-ratio rows from
options_volume_daily OI, leaves post-cutover rows alone, and is idempotent."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.models import OptionsDailyRow
from uw_scan.storage.repository import Repository

T = "ZZPCR"
T2 = "ZZPC2"  # second ticker: the per-ticker join and the zero-call-OI arm
BEFORE = date(2026, 11, 9)


def _seed(repo: Repository) -> None:
    repo.upsert_options_volume_daily(
        T,
        [
            OptionsDailyRow(date=date(2026, 11, 5), call_open_interest=1000, put_open_interest=800),
            OptionsDailyRow(date=date(2026, 11, 6), call_open_interest=2000, put_open_interest=500),
        ],
    )
    # Old rows carry the bug signature: pcr_oi == pcr_vol.
    for d, vol in [
        (date(2026, 11, 5), "1.2000"),  # weekday, exact session
        (date(2026, 11, 7), "0.9000"),  # Saturday (ad hoc weekend rescan)
        (date(2026, 10, 1), "1.1000"),  # no session within the lag window
    ]:
        repo.append_pcr_history(ticker=T, snapshot_date=d, pcr_oi=Decimal(vol), pcr_vol=Decimal(vol))
    # T2's 10/01 session must not leak into T's 10/01 row; its 11/05 session
    # has zero call OI, so that row becomes NULL.
    repo.upsert_options_volume_daily(
        T2,
        [
            OptionsDailyRow(date=date(2026, 10, 1), call_open_interest=400, put_open_interest=100),
            OptionsDailyRow(date=date(2026, 11, 5), call_open_interest=0, put_open_interest=300),
        ],
    )
    for d, vol in [(date(2026, 10, 1), "1.5000"), (date(2026, 11, 5), "0.5000")]:
        repo.append_pcr_history(ticker=T2, snapshot_date=d, pcr_oi=Decimal(vol), pcr_vol=Decimal(vol))
    # A post-fix row the scan already wrote correctly must not be touched.
    repo.append_pcr_history(
        ticker=T, snapshot_date=BEFORE, pcr_oi=Decimal("0.3333"), pcr_vol=Decimal("2.0000")
    )


def _oi(repo: Repository, d: date, ticker: str = T) -> Decimal | None:
    row = repo.get_pcr_history_row(ticker, d)
    assert row is not None
    return row.pcr_oi


def test_repair_dry_run_then_apply_then_idempotent(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo)

    dry = repo.repair_pcr_history_oi(before=BEFORE)
    assert dry == {"rows_in_scope": 5, "rows_with_oi_source": 3, "rows_changed": 5, "rows_set_null": 2}
    assert _oi(repo, date(2026, 11, 5)) == Decimal("1.2000")  # rolled back

    applied = repo.repair_pcr_history_oi(before=BEFORE, apply=True)
    assert applied == dry
    assert _oi(repo, date(2026, 11, 5)) == Decimal("0.8000")
    assert _oi(repo, date(2026, 11, 7)) == Decimal("0.2500")  # takes Friday's session
    assert _oi(repo, date(2026, 10, 1)) is None
    assert _oi(repo, BEFORE) == Decimal("0.3333")
    assert _oi(repo, date(2026, 10, 1), T2) == Decimal("0.2500")
    assert _oi(repo, date(2026, 11, 5), T2) is None  # zero call OI
    assert repo.get_pcr_history_row(T, date(2026, 11, 5)).pcr_vol == Decimal("1.2000")

    again = repo.repair_pcr_history_oi(before=BEFORE, apply=True)
    assert again["rows_changed"] == 0


def test_repair_rejects_negative_lag(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo)
    with pytest.raises(ValueError):
        repo.repair_pcr_history_oi(before=BEFORE, max_lag_days=-1, apply=True)
    assert _oi(repo, date(2026, 11, 5)) == Decimal("1.2000")
