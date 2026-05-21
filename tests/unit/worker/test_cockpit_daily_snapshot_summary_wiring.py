"""Unit wiring test: the per-expiry loop helper must call
upsert_exposures_summary whenever fetch_greek_exposure returns rows. Guards
against silent regression of the Slice 3 wiring."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock


def _ge_row(expiry: str, strike: str):
    from uw_scan.models import GreekExposureRow

    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        dte=9,
        call_vanna=Decimal("100"),
        put_vanna=Decimal("-30"),
        call_charm=Decimal("-2000"),
        put_charm=Decimal("500"),
    )


def test_per_expiry_loop_persists_exposures_summary(monkeypatch):
    """The per-expiry loop helper must call upsert_exposures_summary once per
    expiry whenever fetch_greek_exposure returned rows."""
    from uw_scan.worker.jobs import cockpit_daily_snapshot as job

    fake_repo = MagicMock()
    fake_repo._schema = "uw_scan"
    fake_repo.insert_greeks_rows.return_value = 0
    fake_repo.insert_greek_exposure_rows.return_value = 2
    fake_repo.upsert_skew_rows.return_value = 0

    monkeypatch.setattr(
        job,
        "fetch_greek_exposure",
        lambda *_a, **_k: [
            _ge_row("2026-05-30", "100"),
            _ge_row("2026-05-30", "110"),
        ],
    )
    monkeypatch.setattr(job, "fetch_greeks", lambda *_a, **_k: [])
    monkeypatch.setattr(job, "fetch_skew", lambda *_a, **_k: [])

    job._persist_greeks_per_expiry(
        client=MagicMock(),
        repo=fake_repo,
        run_id=999,
        ticker="TSLA",
        market_date=date.fromisoformat("2026-05-21"),
        expiries=[date.fromisoformat("2026-05-30")],
        spot_for_derive=Decimal("100"),
    )

    assert fake_repo.upsert_exposures_summary.called, (
        "Wiring failure: per-expiry loop did not call upsert_exposures_summary "
        "after insert_greek_exposure_rows. Re-check Slice 3 wiring."
    )
    assert fake_repo.upsert_exposures_summary.call_count >= 1
