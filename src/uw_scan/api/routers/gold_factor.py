"""Read-only routes over the gold factor model's stored results.

GET /api/gold/factor — daily points from `from` (default five years back) plus per-year sums
over the whole history. Historical description, not a forecast.
GET /api/gold/flows — stored flow/holdings history the desk charts (China reserves, CFTC
managed-money net % of open interest, London vault tonnes). Description, not a cause.
GET /api/macro/dxy — the synthetic dollar index and its daily move split by currency.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import groupby

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.macro.gold_factor import E_HI, E_LO
from uw_scan.models import (
    DxyPoint,
    DxyResponse,
    GoldFactorPoint,
    GoldFactorResponse,
    GoldFactorYear,
    GoldFlowPoint,
    GoldFlowsResponse,
)
from uw_scan.storage.gold_factor import fetch_dxy_rows, fetch_rows
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/gold", tags=["gold"])
dxy_router = APIRouter(prefix="/macro", tags=["macro"])
TROY_OZ_PER_TONNE = 32150.7466
_PARTS = ("own_trailing_drift", "real_yield_part", "dollar_part", "haven_part", "unexplained_1")


def _years(rows: list[dict]) -> list[GoldFactorYear]:
    last_year = rows[-1]["obs_date"].year
    out = []
    for year, grp in groupby(rows, key=lambda r: r["obs_date"].year):
        grp = list(grp)
        ok = [r for r in grp if all(r[p] is not None for p in _PARTS)]
        if not ok:
            continue
        s = {p: sum(r[p] for r in ok) for p in (*_PARTS, "gold_change")}
        out.append(
            GoldFactorYear(
                year=year,
                rows=len(ok),
                partial_year=len(ok) < len(grp) or year == last_year,
                gold_change=s["gold_change"],
                own_trailing_drift=s["own_trailing_drift"],
                real_yield_part=s["real_yield_part"],
                dollar_part=s["dollar_part"],
                haven_part=s["haven_part"],
                unexplained=s["unexplained_1"],
                explained_share=1
                - sum(r["unexplained_1"] ** 2 for r in ok) / sum(r["gold_change"] ** 2 for r in ok),
            )
        )
    return out


@router.get("/factor", response_model=GoldFactorResponse)
def get_gold_factor(
    from_date: date | None = Query(None, alias="from"),
    repo: Repository = Depends(get_repo),
) -> GoldFactorResponse:
    rows = fetch_rows(repo.conn)
    if not rows:
        raise HTTPException(404, "gold factor model not computed yet")
    start = from_date or rows[-1]["obs_date"] - timedelta(days=5 * 365)
    return GoldFactorResponse(
        computed_at=max(r["computed_at"] for r in rows),
        last_date=rows[-1]["obs_date"],
        explained_low=E_LO,
        explained_high=E_HI,
        points=[GoldFactorPoint.model_validate(r) for r in rows if r["obs_date"] >= start],
        years=_years(rows),
    )


@router.get("/flows", response_model=GoldFlowsResponse)
def get_gold_flows(repo: Repository = Depends(get_repo)) -> GoldFlowsResponse:
    china = repo.fetch_cb_gold_reserves_history(country_iso3="CHN")
    cot = repo.fetch_cot_gold_weekly()
    lbma = repo.fetch_exchange_inventory_daily("LBMA")
    return GoldFlowsResponse(
        china_reserves_t=sorted(
            (
                GoldFlowPoint(obs_date=r["obs_month"], value=float(r["reserves_t"]))
                for r in china
                if r.get("reserves_t") is not None
            ),
            key=lambda p: p.obs_date,
        ),
        cftc_mm_net_pct_oi=sorted(
            (
                GoldFlowPoint(
                    obs_date=r["obs_date"],
                    value=100 * float(r["mm_net"]) / float(r["open_interest"]),
                )
                for r in cot
                if r.get("mm_net") is not None and r.get("open_interest")
            ),
            key=lambda p: p.obs_date,
        ),
        lbma_vault_t=sorted(
            (
                GoldFlowPoint(
                    obs_date=r["obs_date"],
                    value=float(r["vault_oz"]) / TROY_OZ_PER_TONNE,
                )
                for r in lbma
                if r.get("vault_oz") is not None
            ),
            key=lambda p: p.obs_date,
        ),
    )


@dxy_router.get("/dxy", response_model=DxyResponse)
def get_dxy(
    from_date: date | None = Query(None, alias="from"),
    repo: Repository = Depends(get_repo),
) -> DxyResponse:
    rows = fetch_dxy_rows(repo.conn)
    if not rows:
        raise HTTPException(404, "synthetic dollar index not computed yet")
    start = from_date or rows[-1]["obs_date"] - timedelta(days=5 * 365)
    return DxyResponse(
        computed_at=max(r["computed_at"] for r in rows),
        last_date=rows[-1]["obs_date"],
        points=[DxyPoint.model_validate(r) for r in rows if r["obs_date"] >= start],
    )
