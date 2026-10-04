"""/regime — GEX, CRI, and VCG (all live).

Aggregate of the sub-routers in ``uw_scan.api.routers.regime_routes``. The
include order below reproduces the pre-split route registration order (and so
the OpenAPI ``paths`` order). Every name the module used to define is
re-exported here.
"""

from __future__ import annotations

from fastapi import APIRouter

from uw_scan.api.routers.regime_routes import (
    backdrop,
    canary,
    cri_vcg,
    gex,
    grg_dealer,
    spx_density,
    vrp_macro,
)
from uw_scan.api.routers.regime_routes._shared import (
    _SPOT_FROM_LAKE,
    _active_ws_source,
    _assemble_history,
    _f,
    _is_market_open_now,
    logger,
)
from uw_scan.api.routers.regime_routes.backdrop import (
    _VOL_BACKDROP_SYMBOLS,
    get_dispersion,
    get_vol_backdrop,
    get_vrp_harvest,
)
from uw_scan.api.routers.regime_routes.canary import (
    _fmt_metric,
    _render_canary_validation_markdown,
    get_canary_history,
    get_canary_latest,
    get_canary_validation,
)
from uw_scan.api.routers.regime_routes.cri_vcg import (
    get_cri_history,
    get_cri_intraday,
    get_cri_live,
    get_regime,
    get_vcg,
    get_vcg_history,
    get_vcg_intraday,
    get_vcg_live,
    trigger_cri_scan,
    trigger_vcg_scan,
)
from uw_scan.api.routers.regime_routes.gex import (
    get_gex,
    get_gex_intraday,
    get_market_tide,
    get_top_net_impact,
    trigger_gex_scan,
)
from uw_scan.api.routers.regime_routes.grg_dealer import (
    get_dealer_regime,
    get_grg,
    get_regime_quotes,
    trigger_grg_scan,
)
from uw_scan.api.routers.regime_routes.spx_density import (
    _SPX_DENSITY_QCOLS,
    _spx_density_forecast_model,
    get_spx_density,
    get_spx_density_issued,
)
from uw_scan.api.routers.regime_routes.vrp_macro import (
    _PREVIEW_LEG_ORDER,
    _leg_mid,
    _live_or_eod_macro_signal,
    _modeled_credit,
    _persisted_preview_legs,
    get_vrp_macro_entry_preview,
    get_vrp_macro_signal,
    get_vrp_macro_signal_live,
    post_vrp_macro_entry_capture,
)

# The prefix is applied per include, not on this router: FastAPI refuses to
# include a sub-router whose route path is "" (GET /regime) without a prefix.
router = APIRouter()
router.include_router(gex.router, prefix="/regime")
router.include_router(backdrop.router, prefix="/regime")
router.include_router(spx_density.router, prefix="/regime")
router.include_router(vrp_macro.router, prefix="/regime")
router.include_router(cri_vcg.router, prefix="/regime")
router.include_router(grg_dealer.router, prefix="/regime")
router.include_router(canary.router, prefix="/regime")

__all__ = [
    "_PREVIEW_LEG_ORDER",
    "_SPOT_FROM_LAKE",
    "_SPX_DENSITY_QCOLS",
    "_VOL_BACKDROP_SYMBOLS",
    "_active_ws_source",
    "_assemble_history",
    "_f",
    "_fmt_metric",
    "_is_market_open_now",
    "_leg_mid",
    "_live_or_eod_macro_signal",
    "_modeled_credit",
    "_persisted_preview_legs",
    "_render_canary_validation_markdown",
    "_spx_density_forecast_model",
    "get_canary_history",
    "get_canary_latest",
    "get_canary_validation",
    "get_cri_history",
    "get_cri_intraday",
    "get_cri_live",
    "get_dealer_regime",
    "get_dispersion",
    "get_gex",
    "get_gex_intraday",
    "get_grg",
    "get_market_tide",
    "get_regime",
    "get_regime_quotes",
    "get_spx_density",
    "get_spx_density_issued",
    "get_top_net_impact",
    "get_vcg",
    "get_vcg_history",
    "get_vcg_intraday",
    "get_vcg_live",
    "get_vol_backdrop",
    "get_vrp_harvest",
    "get_vrp_macro_entry_preview",
    "get_vrp_macro_signal",
    "get_vrp_macro_signal_live",
    "logger",
    "post_vrp_macro_entry_capture",
    "router",
    "trigger_cri_scan",
    "trigger_gex_scan",
    "trigger_grg_scan",
    "trigger_vcg_scan",
]
