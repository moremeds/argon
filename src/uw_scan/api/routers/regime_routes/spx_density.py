"""/regime SPX density forecast."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.routers.regime_routes._shared import (
    _f,
)
from uw_scan.models.spx_density import (
    SpxDensityBins,
    SpxDensityForecast,
    SpxDensityHitRate,
    SpxDensityHorizon,
    SpxDensityIssuedResponse,
    SpxDensityLatestResponse,
    SpxDensityPathPoint,
    SpxGammaLevels,
)
from uw_scan.reports.gamma_levels import LEVELS_MAX_AGE_DAYS, resolve_levels
from uw_scan.storage.repository import Repository
from uw_scan.storage.spx_density_repository import SpxDensityRepository

router = APIRouter()


_SPX_DENSITY_QCOLS = (
    "q05",
    "q10",
    "q25",
    "q50",
    "q75",
    "q90",
    "q95",
    "baseline_q05",
    "baseline_q10",
    "baseline_q25",
    "baseline_q50",
    "baseline_q75",
    "baseline_q90",
    "baseline_q95",
)


def _spx_density_forecast_model(as_of, rows) -> SpxDensityForecast:
    head = rows[0]
    return SpxDensityForecast(
        as_of=as_of,
        anchor_close=float(head["anchor_close"]),
        origin=head["origin"],
        fallback_used=head["fallback_used"],
        params=head["params_jsonb"],
        rows=[
            SpxDensityHorizon(
                h=r["h"],
                target_date=r["target_date"],
                scored_horizon=r["scored_horizon"],
                band80_width=float(r["band80_width"]),
                baseline_band80_width=float(r["baseline_band80_width"]),
                width_ratio=float(r["width_ratio"]),
                realised_return=(
                    None
                    if r["realised_return"] is None
                    else float(r["realised_return"])
                ),
                inside_band80=r["inside_band80"],
                density=(
                    SpxDensityBins(**r["density_bins_jsonb"])
                    if r.get("density_bins_jsonb")
                    else None
                ),
                **{c: float(r[c]) for c in _SPX_DENSITY_QCOLS},
            )
            for r in rows
        ],
    )


@router.get("/spx-density", response_model=SpxDensityLatestResponse)
def get_spx_density(
    repo: Annotated[Repository, Depends(get_repo)],
) -> SpxDensityLatestResponse:
    """Latest issued SPX density cone (display-only, v13 PASS). Renders the most recent
    row with its as_of — never interpolates a missing day."""
    sdr = SpxDensityRepository(repo.conn, schema=repo.schema)
    as_of = sdr.latest_as_of()
    if as_of is None:
        return SpxDensityLatestResponse()
    rows = sdr.fetch_forecast(as_of)
    recent = sdr.fetch_spx_recent(45)
    # Levels are guarded against the cone's anchor close — the price the chart is drawn
    # at — and only read from a window ending at the same session, so neither a stale
    # capture nor a wrong-side wall can reach the overlay.
    levels = resolve_levels(
        uw_row=sdr.fetch_uw_gamma_levels(as_of, max_age_days=LEVELS_MAX_AGE_DAYS),
        gex_row=sdr.fetch_gex_snapshot_levels(as_of, max_age_days=LEVELS_MAX_AGE_DAYS),
        chart_spot=float(rows[0]["anchor_close"]),
    )
    return SpxDensityLatestResponse(
        forecast=_spx_density_forecast_model(as_of, rows),
        recent_path=[
            SpxDensityPathPoint(
                date=r["trade_date"],
                close=float(r["close"]),
                open=_f(r.get("open")),
                high=_f(r.get("high")),
                low=_f(r.get("low")),
            )
            for r in recent
        ],
        gamma_levels=SpxGammaLevels(**asdict(levels)),
    )


@router.get("/spx-density/issued", response_model=SpxDensityIssuedResponse)
def get_spx_density_issued(
    repo: Annotated[Repository, Depends(get_repo)],
    limit: int = Query(5, ge=1, le=20),
) -> SpxDensityIssuedResponse:
    """The previously-issued cones (strip) + the cumulative 80%-band hit-rate tally,
    split prospective vs reconstructed (the latter is in-sample by construction)."""
    sdr = SpxDensityRepository(repo.conn, schema=repo.schema)
    as_ofs = sdr.fetch_recent_as_ofs(limit + 1)[1:]  # skip the latest — headline panel
    return SpxDensityIssuedResponse(
        forecasts=[
            _spx_density_forecast_model(a, sdr.fetch_forecast(a)) for a in as_ofs
        ],
        hit_rates=[SpxDensityHitRate(**t) for t in sdr.hit_rate_tally()],
    )
