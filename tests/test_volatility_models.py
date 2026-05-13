"""Unit tests for Volatility Tab v2 Pydantic models (spec 2026-05-13)."""

from datetime import date
from decimal import Decimal

from uw_scan.models import (
    DivergencePoint,
    IvHvPoint,
    RegimeQuadrantLatest,
    RegimeQuadrantPoint,
    SmileExpiryCurve,
    SmilePoint,
    TermStructureExpiryRow,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VrpDailyPoint,
)


def test_volatility_series_response_minimal():
    resp = VolatilitySeriesResponse(
        ticker="TSLA",
        as_of=date(2026, 5, 13),
        backfill_status="ready",
        header=VolHeaderBlock(
            iv=Decimal("0.53"),
            vrp_signal="BUY_VOL",
            vrp_note="IV rich vs RV",
        ),
    )
    assert resp.ticker == "TSLA"
    assert resp.backfill_status == "ready"
    assert resp.term_structure == []
    assert resp.smile == []
    assert resp.hv_iv_history == []
    assert resp.iv_of_iv == []
    assert resp.rv_spy_corr == []
    assert resp.divergence == []
    assert resp.vrp_spread == []
    # Default empty objects, not None — frontend dereferences directly.
    assert resp.regime_quadrant.points == []
    assert resp.iv_percentile_distribution.bins == []


def test_smile_expiry_curve():
    curve = SmileExpiryCurve(
        expiry=date(2026, 5, 15),
        points=[SmilePoint(strike=Decimal("400"), iv=Decimal("0.6"))],
    )
    assert curve.expiry == date(2026, 5, 15)
    assert len(curve.points) == 1


def test_term_structure_row_with_strike_map():
    row = TermStructureExpiryRow(
        expiry=date(2026, 5, 15),
        dte=2,
        by_strike={"ATM": Decimal("0.58"), "ATM+1": Decimal("0.54")},
    )
    assert row.by_strike["ATM"] == Decimal("0.58")


def test_iv_hv_and_vrp_and_regime_points():
    IvHvPoint(date=date(2026, 5, 13), iv=Decimal("0.5"), rv=Decimal("0.4"))
    VrpDailyPoint(date=date(2026, 5, 13), vrp=Decimal("0.1"), vrp_z_20=Decimal("0.5"))
    RegimeQuadrantPoint(
        date=date(2026, 5, 13),
        rvol_pctile=Decimal("45"),
        spy_corr_21=Decimal("0.3"),
    )
    RegimeQuadrantLatest(
        date=date(2026, 5, 13),
        rvol_pctile=Decimal("50"),
        spy_corr_21=Decimal("0.28"),
        state="GOLDILOCKS",
    )
    DivergencePoint(date=date(2026, 5, 13), iv_z=Decimal("0.6"), rv_z=Decimal("-0.4"))
