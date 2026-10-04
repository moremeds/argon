"""/regime 5% Canary (latest, history, validation)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.models.canary import (
    CanaryHistoryResponse,
    CanaryHistoryRow,
    CanaryLatestResponse,
    CanaryValidationResponse,
)
from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION as CANARY_COMPOSITE_VERSION,
)
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get("/canary", response_model=CanaryLatestResponse)
def get_canary_latest(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CanaryLatestResponse:
    snap_repo = CanarySnapshotRepository(repo.conn, schema=repo.schema)
    row = snap_repo.fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="no canary snapshot at current composite_version",
        )
    return CanaryLatestResponse(
        data_date=row["data_date"],
        composite_version=CANARY_COMPOSITE_VERSION,
        score_form=row["score_form"],
        score=float(row["score"]),
        raw_score=float(row["raw_score"]),
        band=row["band"],
        tactical_score=float(row["tactical_score"]),
        structural_score=float(row["structural_score"]),
        speed_score=int(row["speed_score"]),
        warning_state=row["warning_state"],
        payload=row["payload"],
    )


@router.get("/canary/history", response_model=CanaryHistoryResponse)
def get_canary_history(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(30, ge=1, le=365),
) -> CanaryHistoryResponse:
    snap_repo = CanarySnapshotRepository(repo.conn, schema=repo.schema)
    rows = snap_repo.fetch_history(
        composite_version=CANARY_COMPOSITE_VERSION, days=days
    )
    return CanaryHistoryResponse(
        rows=[
            CanaryHistoryRow(
                data_date=r["data_date"],
                score=float(r["score"]),
                band=r["band"],
                tactical_score=float(r["tactical_score"]),
                structural_score=float(r["structural_score"]),
                speed_score=int(r["speed_score"]),
                warning_state=r["warning_state"],
                spx_close=(
                    float(r["spx_close"]) if r.get("spx_close") is not None else None
                ),
            )
            for r in rows
        ]
    )


def _fmt_metric(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError) as exc:
        _ = repr(exc)
        return str(value)


def _render_canary_validation_markdown(summary: dict) -> str:
    daily = summary.get("daily_aucs", {})
    events = summary.get("events", {})
    bands = summary.get("band_distribution", {})
    btd = events.get("buy_the_dip", {})
    cc = events.get("confirmed_canary", {})
    lines = [
        "# 5% Canary validation",
        "",
        f"Score form: `{summary.get('score_form', 'unknown')}`",
        "",
        "## Daily AUCs",
        f"- up5d_2pct: {_fmt_metric(daily.get('up5d_2pct'))}",
        f"- up20d_5pct: {_fmt_metric(daily.get('up20d_5pct'))}",
        f"- up60d_10pct: {_fmt_metric(daily.get('up60d_10pct'))}",
        "",
        "## Band distribution",
        f"- NONE: {bands.get('NONE', 0)}",
        f"- WATCH: {bands.get('WATCH', 0)}",
        f"- BUY: {bands.get('BUY', 0)}",
        f"- STRONG_BUY: {bands.get('STRONG_BUY', 0)}",
        "",
        "## Event validation",
        f"- Buy The Dip events: {btd.get('n_events', 0)}, "
        f"median 42d drawup: {_fmt_metric(btd.get('median_fwd_42d_drawup'))}",
        f"- Confirmed Canary events: {cc.get('n_events', 0)}, "
        f"median 42d drawdown: {_fmt_metric(cc.get('median_fwd_42d_drawdown'))}",
    ]
    return "\n".join(lines)


@router.get("/canary/validation", response_model=CanaryValidationResponse)
def get_canary_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CanaryValidationResponse:
    """v0.4 patch I4 + C6: use the existing `find_latest_run` (which already
    filters on `completed_at IS NOT NULL`) and post-filter for the winning
    form in summary JSON. composite_version is stringified at the DB boundary.
    """
    bt_repo = RegimeBacktestRepository(repo.conn, schema=repo.schema)
    row = bt_repo.find_latest_run(
        indicator="canary",
        composite_version=str(CANARY_COMPOSITE_VERSION),
    )
    if row is None or not row.get("summary", {}).get("is_winning_form"):
        raise HTTPException(
            status_code=503,
            detail=(
                "no completed canary backtest at current composite_version "
                "(or row missing is_winning_form)"
            ),
        )
    summary = row["summary"]
    return CanaryValidationResponse(
        run_id=row["id"],
        composite_version=int(row["composite_version"]),
        score_form=summary.get("score_form", "linear"),
        summary=summary,
        rendered_markdown=_render_canary_validation_markdown(summary),
    )
