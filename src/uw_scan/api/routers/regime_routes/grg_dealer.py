"""/regime GRG, live regime quotes and per-ticker dealer regime."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings, get_uw_client
from uw_scan.api.routers.regime_routes._shared import (
    _active_ws_source,
)
from uw_scan.cards.dealer_regime import compute_dealer_regime, gather_inputs
from uw_scan.config import Settings
from uw_scan.models.regime_cri_vcg import RegimeLiveQuote, RegimeQuotesResponse
from uw_scan.models.regime_dealer import (
    EMPTY_DEALER_REGIME_RESPONSE,
    ClosestLevel,
    DealerRegimeResponse,
    DealerRegimeSignal,
    GammaDecayBucket,
)
from uw_scan.models.regime_grg import (
    EMPTY_GRG_RESPONSE,
    GrgResponse,
    GrgScanResponse,
)
from uw_scan.scanners import grg as grg_scanner
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/grg", response_model=GrgResponse)
def get_grg(
    repo: Annotated[Repository, Depends(get_repo)],
) -> GrgResponse:
    """Latest GRG snapshot (self-contained: embeds 90-session history).

    GRG is EOD/periodic-rescan — the worker owns UW fetches; this read is
    cheap (one snapshot row). No per-request UW spend."""
    snap_repo = GrgSnapshotRepository(repo.conn, schema=repo.schema)
    latest = snap_repo.fetch_latest()
    if latest is None:
        return EMPTY_GRG_RESPONSE.model_copy(deep=True)
    return GrgResponse.model_validate({"status": "ok", **latest})


@router.post("/grg/scan", response_model=GrgScanResponse)
def trigger_grg_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    uw_client: Annotated[UwClient, Depends(get_uw_client)],
) -> GrgScanResponse:
    """Run a GRG scan synchronously against UW and persist a snapshot.

    200, not 202: the scan has finished and been written when this returns.
    """
    row_id = grg_scanner.run(uw_client, repo, schema=repo.schema)
    if row_id is None:
        return GrgScanResponse(status="skipped", reason="thin_data")
    return GrgScanResponse(status="ok", row_id=row_id)


@router.get("/quotes", response_model=RegimeQuotesResponse)
def get_regime_quotes(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegimeQuotesResponse:
    rows = repo.get_intraday_quotes([s.upper() for s in settings.regime_ws_symbols])
    quotes = {
        r.ticker: RegimeLiveQuote(
            price=float(r.price), quoted_at=r.quoted_at, source=r.source
        )
        for r in rows
    }
    as_of = max((r.quoted_at for r in rows), default=None)
    return RegimeQuotesResponse(
        quotes=quotes,
        active_source=_active_ws_source(repo),
        as_of=as_of,
        fresh_within_seconds=settings.regime_live_quote_max_age_seconds,
    )


# ─── Dealer regime (per-ticker, live) ─────────────────────────────


@router.get("/dealer", response_model=DealerRegimeResponse)
def get_dealer_regime(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query(..., min_length=1, max_length=10),
) -> DealerRegimeResponse:
    """Per-ticker dealer Greek regime — feeds the Magnet/Gamma summary bar
    and the Volatility tab regime panel. Uses the same `gather_inputs`
    helper the report assembler uses so both paths see the same upstream.
    """
    t = ticker.upper()
    inputs = gather_inputs(repo, ticker=t)
    if inputs["run_id"] == 0:
        empty = EMPTY_DEALER_REGIME_RESPONSE.model_copy(deep=True)
        empty.ticker = t
        return empty

    out = compute_dealer_regime(
        ticker=t,
        spot=inputs["spot"],
        net_gex=inputs["net_gex"],
        prev_close_net_gex=inputs["prev_close_net_gex"],
        per_expiry_vanna=inputs["per_expiry_vanna"],
        per_expiry_charm=inputs["per_expiry_charm"],
        strike_gex_curve=inputs["strike_gex_curve"],
        levels=inputs["levels"],
        today=inputs["today"],
    )

    return DealerRegimeResponse(
        status="ok",
        ticker=t,
        scan_time="",
        spot=out.spot,
        net_gex=out.net_gex,
        prev_close_net_gex=out.prev_close_net_gex,
        signal=DealerRegimeSignal(
            label=out.signal.label,
            score=out.signal.score,
            gamma_score=out.signal.gamma_score,
            vanna_score=out.signal.vanna_score,
            charm_score=out.signal.charm_score,
            headline=out.signal.headline,
            subtitle=out.signal.subtitle,
        ),
        closest_levels=[
            ClosestLevel(
                label=lv.label,
                direction=lv.direction,
                role=lv.role,
                strike=lv.strike,
                distance_pct=lv.distance_pct,
                gamma=lv.gamma,
                rank_kind=lv.rank_kind,
            )
            for lv in out.closest_levels
        ],
        odte_gex=out.odte_gex,
        odte_share_pct=out.odte_share_pct,
        gamma_decay=[
            GammaDecayBucket(
                dte=b.dte,
                expiry=b.expiry,
                net_gex=b.net_gex,
                share_pct=b.share_pct,
                gross_abs_gex=b.gross_abs_gex,
                gross_share_pct=b.gross_share_pct,
            )
            for b in out.gamma_decay
        ],
    )
