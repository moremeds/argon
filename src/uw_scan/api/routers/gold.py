"""Gold cockpit API surface (Phase A1).

Endpoints (all read-only):
  GET /api/gold/state
  GET /api/gold/gauge
  GET /api/gold/inputs/{series_id}
  GET /api/gold/lenses/{lens_id}
  GET /api/gold/replay?as_of=YYYY-MM-DD
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.cards.regime_gauge import compute_correlation_gauge
from uw_scan.models import (
    GoldCorrelationBand,
    GoldCorrelationHistory,
    GoldCorrelationPoint,
    GoldCyclicalPostureModel,
    GoldDataFreshnessSource,
    GoldDecompositionRow,
    GoldGaugeResponse,
    GoldGaugeState,
    GoldGaugeTimeSeriesPoint,
    GoldHistoryPoint,
    GoldInputProvenance,
    GoldInputSeriesPoint,
    GoldInputSeriesResponse,
    GoldLensResponse,
    GoldSpotTile,
    GoldStateResponse,
    GoldStructuralPostureModel,
    GoldTwoForceText,
    GoldValuationPostureModel,
)
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

# Mounted under `/api` by create_app(); final path is `/api/gold/*`.
router = APIRouter(prefix="/gold", tags=["gold"])


# --------------------------------------------------------------------------
# helpers — map persisted gold_posture_daily row → GoldStateResponse
# --------------------------------------------------------------------------


def _spot_from_jsonb(blob: Any) -> GoldSpotTile:
    """Build the Tier 1 spot tile from the persisted spot_jsonb or fall back."""
    if isinstance(blob, dict) and blob.get("last") is not None:
        return GoldSpotTile(
            last=Decimal(str(blob["last"])),
            delta_abs=Decimal(str(blob.get("delta_abs", "0"))),
            delta_pct=Decimal(str(blob.get("delta_pct", "0"))),
            high=Decimal(str(blob.get("high", blob["last"]))),
            low=Decimal(str(blob.get("low", blob["last"]))),
            open=Decimal(str(blob.get("open", blob["last"]))),
        )
    zero = Decimal("0")
    return GoldSpotTile(
        last=zero,
        delta_abs=zero,
        delta_pct=zero,
        high=zero,
        low=zero,
        open=zero,
    )


def _history_points(blob: Any) -> list[GoldHistoryPoint]:
    if not isinstance(blob, list):
        return []
    out: list[GoldHistoryPoint] = []
    for row in blob:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                GoldHistoryPoint(
                    obs_date=date.fromisoformat(row["obs_date"]),
                    value=Decimal(str(row["value"])),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.debug("history point parse skipped: %s", repr(exc))
            continue
    return out


def _correlation_points(blob: Any) -> list[GoldCorrelationPoint]:
    if not isinstance(blob, list):
        return []
    out: list[GoldCorrelationPoint] = []
    for row in blob:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                GoldCorrelationPoint(
                    obs_date=date.fromisoformat(row["obs_date"]),
                    value=Decimal(str(row["value"])),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.debug("correlation point parse skipped: %s", repr(exc))
            continue
    return out


def _correlation_history(blob: Any) -> GoldCorrelationHistory:
    if not isinstance(blob, dict):
        return GoldCorrelationHistory()
    band = None
    band_blob = blob.get("pre_2022_band")
    if isinstance(band_blob, dict):
        try:
            band = GoldCorrelationBand(
                mean=Decimal(str(band_blob["mean"])),
                std=Decimal(str(band_blob["std"])),
            )
        except (KeyError, ValueError) as exc:
            logger.debug("correlation band parse skipped: %s", repr(exc))
            band = None
    return GoldCorrelationHistory(
        gold_dfii10=_correlation_points(blob.get("gold_dfii10")),
        gold_dxy=_correlation_points(blob.get("gold_dxy")),
        gold_gpr=_correlation_points(blob.get("gold_gpr")),
        pre_2022_band=band,
    )


def _decomposition_rows(blob: Any) -> list[GoldDecompositionRow]:
    if not isinstance(blob, list):
        return []
    out: list[GoldDecompositionRow] = []
    for row in blob:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                GoldDecompositionRow(
                    lens=row["lens"],
                    factor=row["factor"],
                    contribution=Decimal(str(row["contribution"])),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.debug("decomposition row parse skipped: %s", repr(exc))
            continue
    return out


def _data_freshness(blob: Any) -> list[GoldDataFreshnessSource]:
    if not isinstance(blob, list):
        return []
    out: list[GoldDataFreshnessSource] = []
    for row in blob:
        if not isinstance(row, dict):
            continue
        try:
            ts_raw = row["last_as_of"]
            ts = (
                ts_raw
                if isinstance(ts_raw, datetime)
                else datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            )
            out.append(
                GoldDataFreshnessSource(
                    id=row["id"],
                    last_as_of=ts,
                    stale_seconds=int(row.get("stale_seconds", 0)),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.debug("data freshness row parse skipped: %s", repr(exc))
            continue
    return out


def _state_from_row(row: dict) -> GoldStateResponse:
    inputs_used: dict[str, GoldInputProvenance] = {}
    for sid, meta in (row.get("inputs_jsonb") or {}).items():
        if not isinstance(meta, dict):
            continue
        obs_date_raw = meta.get("obs_date") or meta.get("obs_month")
        as_of_raw = meta.get("as_of")
        if obs_date_raw is None or as_of_raw is None:
            continue
        try:
            inputs_used[sid] = GoldInputProvenance(
                obs_date=date.fromisoformat(obs_date_raw),
                as_of=as_of_raw,
            )
        except ValueError as exc:
            logger.debug("input provenance parse skipped: %s", repr(exc))
            continue

    return GoldStateResponse(
        obs_date=row["obs_date"],
        computed_at=row["computed_at"],
        gauge=GoldGaugeState(
            corr_60d=row.get("gauge_corr_60d"),
            corr_126d=row.get("gauge_corr_126d"),
            corr_252d=row.get("gauge_corr_252d"),
            corr_504d=row.get("gauge_corr_504d"),
            corr_252d_returns=row.get("gauge_corr_252d_returns"),
            state=row["gauge_state"],
        ),
        spot=_spot_from_jsonb(row.get("spot_jsonb")),
        structural=GoldStructuralPostureModel(
            state_label=row.get("structural_state_label"),
            posture_chip=row.get("structural_posture_chip") or "NEUTRAL",
            cb_strategic_12m_sum_t=row.get("cb_strategic_12m_sum_t"),
            cb_tactical_12m_sum_t=row.get("cb_tactical_12m_sum_t"),
            cb_diversifier_12m_sum_t=row.get("cb_diversifier_12m_sum_t"),
            cb_52w_pct=row.get("cb_52w_pct"),
            gld_holdings_t=row.get("gld_holdings_t"),
            gld_30d_net_flow_t=row.get("gld_30d_net_flow_t"),
            comex_registered_oz=row.get("comex_registered_oz"),
            comex_20d_roc_pct=row.get("comex_20d_roc_pct"),
            lbma_30d_momentum_t=row.get("lbma_30d_momentum_t"),
            cot_mm_net_pct=row.get("cot_mm_net_pct"),
            cot_mm_4w_change_sigma=row.get("cot_mm_4w_change_sigma"),
            uw_25d_skew_sigma=row.get("uw_25d_skew_sigma"),
            fx_basket_dxy_z=row.get("fx_basket_dxy_z"),
            xau_cny_premium_pct=row.get("xau_cny_premium_pct"),
            gld_history=_history_points(row.get("gld_history_jsonb")),
            gold_history=_history_points(row.get("gold_history_jsonb")),
            narrative_text=row.get("structural_posture_text") or "",
        ),
        cyclical=GoldCyclicalPostureModel(
            zone_label=row.get("cyclical_zone_label"),
            posture_chip=row.get("cyclical_posture_chip") or "NEUTRAL",
            cpi_yoy=row.get("cpi_yoy"),
            t5yifr=row.get("t5yifr"),
            t5yifr_pct_52w=row.get("t5yifr_pct_52w"),
            dfii10=row.get("dfii10"),
            dfii10_60d_change_bps=row.get("dfii10_60d_change_bps"),
            dxy=row.get("dxy"),
            dxy_60d_sigma=row.get("dxy_60d_sigma"),
            gpr_value=row.get("gpr_value"),
            gpr_pct_52w=row.get("gpr_pct_52w"),
            factors=row.get("factors_jsonb") or {},
            two_force_text=GoldTwoForceText(
                discount_rate="—",
                hedge_demand="—",
            ),
            narrative_text=row.get("cyclical_posture_text") or "",
        ),
        valuation=GoldValuationPostureModel(
            flag=row.get("valuation_flag") or "Low",
            posture_chip=row.get("valuation_posture_chip") or "NEUTRAL",
            real_price_percentile=row.get("real_price_percentile"),
            gold_m2_ratio_percentile=row.get("gold_m2_ratio_percentile"),
            gold_spx_ratio_percentile=row.get("gold_spx_ratio_percentile"),
            narrative_text=row.get("valuation_posture_text") or "",
        ),
        inputs_used=inputs_used,
        data_freshness=_data_freshness(row.get("data_freshness_jsonb")),
        decomposition_rows=_decomposition_rows(row.get("decomposition_jsonb")),
        correlation_history=_correlation_history(row.get("correlation_history_jsonb")),
    )


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------


@router.get("/gauge", response_model=GoldGaugeResponse)
def get_gauge(repo: Repository = Depends(get_repo)) -> GoldGaugeResponse:
    today = date.today()
    gold_rows = repo.fetch_macro_series_daily("GLD_CLOSE", to_date=today)
    dfii10_rows = repo.fetch_macro_series_daily("DFII10", to_date=today)
    gold_series = [(r["obs_date"], r["value"]) for r in gold_rows]
    dfii10_series = [(r["obs_date"], r["value"]) for r in dfii10_rows]
    current = compute_correlation_gauge(gold_series, dfii10_series, as_of=today)

    history: list[GoldGaugeTimeSeriesPoint] = []
    cursor = today - timedelta(days=5 * 365)
    while cursor <= today:
        snapshot = compute_correlation_gauge(gold_series, dfii10_series, as_of=cursor)
        history.append(
            GoldGaugeTimeSeriesPoint(
                obs_date=cursor, corr_252d=snapshot.corr_252d_level
            )
        )
        cursor += timedelta(days=7)

    return GoldGaugeResponse(
        current=GoldGaugeState(
            corr_60d=current.corr_60d_level,
            corr_126d=current.corr_126d_level,
            corr_252d=current.corr_252d_level,
            corr_504d=current.corr_504d_level,
            corr_252d_returns=current.corr_252d_returns,
            state=current.state,
        ),
        history_252d=history,
    )


@router.get("/inputs/{series_id}", response_model=GoldInputSeriesResponse)
def get_input_series(
    series_id: str,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    repo: Repository = Depends(get_repo),
) -> GoldInputSeriesResponse:
    rows = repo.fetch_macro_series_daily(
        series_id, from_date=from_date, to_date=to_date
    )
    points = [
        GoldInputSeriesPoint(
            obs_date=r["obs_date"],
            value=r["value"],
            as_of=r["as_of"],
            release_date=r.get("release_date"),
        )
        for r in rows
    ]
    return GoldInputSeriesResponse(series_id=series_id, points=points)


@router.get("/state", response_model=GoldStateResponse)
def get_state(repo: Repository = Depends(get_repo)) -> GoldStateResponse:
    row = repo.fetch_gold_posture_latest()
    if row is None:
        raise HTTPException(404, "no gold posture computed yet")
    return _state_from_row(row)


@router.get("/lenses/{lens_id}", response_model=GoldLensResponse)
def get_lens(
    lens_id: Literal["structural", "cyclical", "valuation"],
    repo: Repository = Depends(get_repo),
) -> GoldLensResponse:
    row = repo.fetch_gold_posture_latest()
    if row is None:
        raise HTTPException(404, "no gold posture computed yet")
    state_resp = _state_from_row(row)

    detail: dict[str, list[GoldInputSeriesPoint]] = {}
    if lens_id == "structural":
        for ticker in ("GLD", "IAU", "GLDM"):
            etf_rows = repo.fetch_etf_holdings_daily(
                ticker, from_date=row["obs_date"] - timedelta(days=180)
            )
            detail[f"{ticker}_holdings_oz"] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_date"],
                    value=(r.get("holdings_oz") or Decimal("0")),
                    as_of=r["as_of"],
                    release_date=None,
                )
                for r in etf_rows
                if r.get("holdings_oz") is not None
            ]
        posture = state_resp.structural
    elif lens_id == "cyclical":
        for series in ("DFII10", "T5YIFR", "T10YIE", "DTWEXBGS"):
            srows = repo.fetch_macro_series_daily(
                series, from_date=row["obs_date"] - timedelta(days=365)
            )
            detail[series] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_date"],
                    value=r["value"],
                    as_of=r["as_of"],
                    release_date=r.get("release_date"),
                )
                for r in srows
            ]
        posture = state_resp.cyclical
    else:
        for series in ("CPIAUCSL", "M2SL"):
            mrows = repo.fetch_macro_series_monthly(series)
            detail[series] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_month"],
                    value=r["value"],
                    as_of=r["as_of"],
                    release_date=r.get("release_date"),
                )
                for r in mrows
            ]
        posture = state_resp.valuation

    return GoldLensResponse(lens_id=lens_id, posture=posture, detail=detail)


@router.get("/replay", response_model=GoldStateResponse)
def get_replay(
    as_of: date = Query(..., description="Reconstruct posture for this obs_date"),
    repo: Repository = Depends(get_repo),
) -> GoldStateResponse:
    row = repo.fetch_gold_posture_for_obs_date(as_of)
    if row is None:
        raise HTTPException(404, f"no posture row for {as_of}")
    return _state_from_row(row)
