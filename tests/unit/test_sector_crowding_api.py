"""Endpoint shape for /api/regime/sector-crowding."""

from datetime import date

from uw_scan.api.models.sector_crowding import (
    SectorCrowdingLeg,
    SectorCrowdingResponse,
    SectorCrowdingRow,
    SectorCrowdingSeriesPoint,
)


def test_response_serializes_a_full_row():
    resp = SectorCrowdingResponse(
        as_of=date(2026, 7, 24),
        benchmark="SPY",
        rows=[
            SectorCrowdingRow(
                ticker="SOXX",
                price=SectorCrowdingLeg(
                    name="price", raw=53.69, score=97.0, band="CROWDED"
                ),
                flow=SectorCrowdingLeg(
                    name="flow", raw=26.47, score=100.0, band="CROWDED"
                ),
                premium=SectorCrowdingLeg(
                    name="premium", raw=64.23, score=100.0, band="CROWDED"
                ),
                score=98.33,
                state="CROWDED",
                binding_leg="price",
                series=[
                    SectorCrowdingSeriesPoint(
                        obs_date=date(2026, 7, 24),
                        etf_cum_return=25.59,
                        bench_cum_return=4.98,
                        flow_aum_pct=26.47,
                    )
                ],
            )
        ],
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["rows"][0]["state"] == "CROWDED"
    assert dumped["rows"][0]["binding_leg"] == "price"
    assert dumped["rows"][0]["series"][0]["obs_date"] == "2026-07-24"


def test_empty_response_is_valid():
    resp = SectorCrowdingResponse(as_of=None, benchmark="SPY", rows=[])
    assert resp.model_dump(mode="json")["rows"] == []


def test_absent_leg_serializes_as_nulls():
    leg = SectorCrowdingLeg(name="premium", raw=None, score=None, band=None)
    assert leg.model_dump(mode="json") == {
        "name": "premium",
        "raw": None,
        "score": None,
        "band": None,
    }


def test_route_maps_build_output_onto_the_response():
    """The three model tests above never execute the route body, so a typo in
    the `_leg` mapping (swapping `raw` and `score`, dropping `binding_leg`)
    ships green. Drive the real route with `build_sector_crowding` patched --
    a fake repo, no Postgres -- and assert the JSON the browser would get.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from uw_scan.api.deps import get_repo
    from uw_scan.api.server import create_app
    from uw_scan.reports.sector_crowding import (
        CrowdingLeg,
        CrowdingRow,
        CrowdingSeriesPoint,
    )

    row = CrowdingRow(
        ticker="SOXX",
        price=CrowdingLeg("price", 53.69, 97.0, "CROWDED"),
        flow=CrowdingLeg("flow", 26.47, 100.0, "CROWDED"),
        premium=CrowdingLeg("premium", 64.23, 100.0, "CROWDED"),
        score=98.33,
        state="CROWDED",
        binding_leg="price",
        series=[
            CrowdingSeriesPoint(
                obs_date=date(2026, 7, 24),
                etf_cum_return=25.59,
                bench_cum_return=4.98,
                flow_aum_pct=26.47,
            )
        ],
    )

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: object()
    try:
        with patch(
            "uw_scan.reports.sector_crowding.build_sector_crowding",
            return_value=(date(2026, 7, 24), [row]),
        ):
            body = TestClient(app).get("/api/regime/sector-crowding").json()
    finally:
        app.dependency_overrides.clear()

    assert body["as_of"] == "2026-07-24"
    assert body["benchmark"] == "SPY"
    (got,) = body["rows"]
    assert got["ticker"] == "SOXX"
    assert got["state"] == "CROWDED"
    assert got["binding_leg"] == "price"
    # raw and score are both floats on every leg, so a swap is invisible
    # unless the values differ. They do.
    assert got["price"] == {
        "name": "price",
        "raw": 53.69,
        "score": 97.0,
        "band": "CROWDED",
    }
    assert got["series"][0]["flow_aum_pct"] == 26.47
