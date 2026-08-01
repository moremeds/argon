"""Nightly SPX density cone job — settle pass then issue pass (v13 display-only port).

Pass 1 (settle) fills realised_return / inside_band80 for any row whose H-th subsequent
trading day now has a close — pure SQL + arithmetic, so a pass-2 failure never blocks
yesterday's outcomes. Pass 2 (issue) draws today's cone and writes 5 new (as_of, h) rows.
Every degradation is labelled and returned in the summary; nothing is silent.
"""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.config import Settings
from uw_scan.density.constants import PANEL_FIRST_DATE
from uw_scan.density.forecast import (
    PanelMismatchError,
    SeriesTooShortError,
    compute_forecast,
    result_to_db_rows,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.spx_density_repository import SpxDensityRepository

log = logging.getLogger(__name__)


def _settle_pass(sdr: SpxDensityRepository) -> int:
    settled = 0
    for row in sdr.fetch_unsettled():
        closes = sdr.fetch_spx_closes_after(row["as_of"], row["h"])
        if len(closes) < row["h"]:
            continue  # the H-th trading day hasn't closed yet
        target_date, close = closes[row["h"] - 1]
        realised = close / float(row["anchor_close"]) - 1.0
        inside = float(row["q10"]) <= realised <= float(row["q90"])
        sdr.settle(row["as_of"], row["h"], target_date, realised, inside)
        settled += 1
    return settled


def spx_density_forecast_job(repo: Repository, settings: Settings) -> dict[str, Any]:
    sdr = SpxDensityRepository(repo.conn, schema=settings.db_schema)
    settled = _settle_pass(sdr)

    bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
    if not bars:
        log.error("spx_density_forecast: no SPX rows in vol_index_daily")
        return {"settled": settled, "issued": 0, "skipped": "no_data"}
    anchor = bars[-1][0]
    if sdr.latest_as_of() == anchor:
        # vol_index_lake_sync produced no new bar — never re-anchor on a stale close
        return {"settled": settled, "issued": 0, "skipped": "already_issued"}

    try:
        result = compute_forecast(bars)
    except PanelMismatchError as exc:
        log.error("spx_density_forecast: REFUSING to publish — %s", exc)
        return {"settled": settled, "issued": 0, "error": "panel_mismatch"}
    except SeriesTooShortError as exc:
        log.warning("spx_density_forecast: %s", exc)
        return {"settled": settled, "issued": 0, "skipped": "too_short"}

    issued = sdr.upsert_rows(result_to_db_rows(result, origin="prospective"))
    if result.fallback_used:
        log.warning("spx_density_forecast: GJR fit unavailable — EWMA FALLBACK issued")
    return {
        "settled": settled,
        "issued": issued,
        "as_of": str(result.as_of),
        "fallback_used": result.fallback_used,
    }
