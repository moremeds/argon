"""End-to-end deriver: GreekExposureRow list -> ExposuresSummaryRow per expiry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import ExposuresSummaryRow, GreekExposureRow


def _r(strike: str, expiry: str, **kw) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        dte=kw.get("dte"),
        call_vanna=Decimal(kw["cv"]) if "cv" in kw else None,
        put_vanna=Decimal(kw["pv"]) if "pv" in kw else None,
        call_charm=Decimal(kw["cc"]) if "cc" in kw else None,
        put_charm=Decimal(kw["pc"]) if "pc" in kw else None,
    )


def test_build_summary_rows_groups_by_expiry():
    rows = [
        _r("100", "2026-05-30", dte=9, cv="100", pv="-50", cc="-2000", pc="500"),
        _r("110", "2026-05-30", dte=9, cv="200", pv="-80", cc="-3000", pc="600"),
        _r("100", "2026-06-20", dte=30, cv="10", pv="-5", cc="-200", pc="50"),
    ]
    out = build_summary_rows(rows, spot=Decimal("105"))
    assert len(out) == 2

    by_expiry = {r.expiry: r for r in out}
    near = by_expiry[date.fromisoformat("2026-05-30")]
    far = by_expiry[date.fromisoformat("2026-06-20")]

    assert isinstance(near, ExposuresSummaryRow)
    assert near.dte == 9
    assert near.spot == Decimal("105")

    assert near.net_vanna == Decimal("170")
    assert near.net_charm == Decimal("-3900")
    assert near.vanna_headline
    assert near.charm_headline

    assert far.net_vanna == Decimal("5")


def test_build_summary_rows_empty_returns_empty_list():
    assert build_summary_rows([], spot=Decimal("100")) == []


def test_build_summary_rows_spot_none_still_produces_rows():
    """Charm imbalance returns (0,0,None) when spot is None — must not crash."""
    rows = [_r("100", "2026-05-30", dte=9, cv="50", pv="50", cc="-1000", pc="500")]
    out = build_summary_rows(rows, spot=None)
    assert len(out) == 1
    assert out[0].spot is None
    assert out[0].charm_imbalance_pct is None


def test_build_summary_rows_mixed_dte_same_expiry_collapses_to_one_row():
    """Multiple dte values for the same expiry must NOT produce duplicate PK rows
    (table PK is (run_id, ticker, expiry)). The builder picks min non-null dte."""
    rows = [
        _r("100", "2026-05-30", dte=9, cv="100", pv="-50", cc="-1000", pc="500"),
        _r("110", "2026-05-30", dte=10, cv="80", pv="-30", cc="-2000", pc="800"),
        _r("105", "2026-05-30", dte=None, cv="50", pv="-20", cc="-500", pc="100"),
    ]
    out = build_summary_rows(rows, spot=Decimal("105"))
    assert len(out) == 1
    assert out[0].dte == 9
    assert out[0].net_vanna == Decimal("130")
