"""GET /api/stock/{ticker}/skew — Skew First-Principles tab."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from uw_scan.api.deps import get_repo
from uw_scan.models import SkewAnalysisResponse
from uw_scan.reports.skew_analytics import assemble_skew_analysis
from uw_scan.storage.repository import Repository

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/stock/{ticker}/skew", response_model=SkewAnalysisResponse)
def get_skew_analysis(
    ticker: str, repo: Repository = Depends(get_repo)
) -> SkewAnalysisResponse:
    return assemble_skew_analysis(ticker=ticker.upper(), repo=repo)
