"""Nightly SPX density cone job — settle, issue, then reconstruct (v13 display-only port).

Pass 1 (settle) fills realised_return / inside_band80 for any row whose H-th subsequent
trading day now has a close — pure SQL + arithmetic, so a later failure never blocks
yesterday's outcomes. Pass 2 (issue) draws today's cone and writes 5 new (as_of, h) rows.
Pass 3 (reconstruct) fills sessions the issue pass can never reach — see
``_reconstruct_pass``. Every degradation is labelled and returned in the summary;
nothing is silent.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import AbstractSet, Any

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


# How far back the reconstruct pass looks for holes. Ten sessions covers a two-week
# stack outage; a longer hole is a seeding job, which is what the backfill script is for.
_RECONSTRUCT_LOOKBACK_SESSIONS = 10


def select_sessions(
    candidates: Sequence[date],
    *,
    existing: AbstractSet[date],
    prospective: AbstractSet[date],
) -> list[date]:
    """Which candidate sessions a reconstruct may write.

    `existing` is empty under the backfill script's --force, which is the point of that
    flag: recompute rows we already have. `prospective` is NOT, ever. upsert_rows updates
    `origin` on conflict, so recomputing a session the nightly job issued forward would
    rewrite it to 'reconstructed' and move a genuinely out-of-sample cone into the
    in-sample tally — quietly inflating the only honest hit-rate number on the page. A row
    the model published forward is not something a backfill may relabel.
    """
    return [d for d in candidates if d not in existing and d not in prospective]


def _reconstruct_pass(
    sdr: SpxDensityRepository,
    bars: list[tuple[date, float]],
    *,
    lookback: int = _RECONSTRUCT_LOOKBACK_SESSIONS,
) -> list[date]:
    """Fill holes the issue pass can never reach, as origin='reconstructed'.

    The issue pass only ever anchors the FRESHEST bar and self-gates on
    ``latest_as_of() == anchor``. So a session whose 03:30 run never fired — the stack was
    down, or the cron's tue-sat window put the only chance to issue Friday's anchor on a
    Saturday that never ran — is skipped forever once a later cone lands. That is how
    2026-08-14 went missing while 08-13 and 08-17 were both present.

    Two bounds keep this a gap-filler rather than a seeder:
    - the freshest bar is excluded; that one belongs to the issue pass, prospectively.
    - nothing older than the earliest cone already on record is touched. An empty log
      means history has not been seeded yet, which is the backfill script's job, not a
      side effect of a nightly run.
    """
    if len(bars) < 2:
        return []
    existing = set(sdr.fetch_recent_as_ofs(lookback + 10))
    if not existing:
        return []  # unseeded log — scripts/backfill/spx_density_backfill.py owns seeding
    floor = min(existing)
    candidates = [d for d, _ in bars[-(lookback + 1) : -1] if d > floor]
    writable = select_sessions(
        candidates,
        existing=existing,
        prospective=sdr.fetch_as_ofs_with_origin("prospective"),
    )
    written: list[date] = []
    for as_of in writable:
        try:
            result = compute_forecast(bars, as_of=as_of)
        except PanelMismatchError as exc:
            # The panel is shared by every as_of, so a mismatch invalidates the whole
            # pass, not just this one date. Stop rather than write seeds we cannot trust.
            log.error("spx_density_reconstruct: REFUSING — %s", repr(exc))
            break
        except SeriesTooShortError as exc:
            log.warning("spx_density_reconstruct: skipping %s — %s", as_of, repr(exc))
            continue
        sdr.upsert_rows(result_to_db_rows(result, origin="reconstructed"))
        written.append(as_of)
        log.info(
            "spx_density_reconstruct: filled %s seed=%d fallback=%s",
            as_of,
            result.seed,
            result.fallback_used,
        )
    return written


def spx_density_forecast_job(repo: Repository, settings: Settings) -> dict[str, Any]:
    sdr = SpxDensityRepository(repo.conn, schema=settings.db_schema)
    settled = _settle_pass(sdr)

    bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
    if not bars:
        log.error("spx_density_forecast: no SPX rows in vol_index_daily")
        return {"settled": settled, "issued": 0, "skipped": "no_data"}
    out: dict[str, Any] = {"settled": settled, "issued": 0}
    anchor = bars[-1][0]
    if sdr.latest_as_of() == anchor:
        # vol_index_lake_sync produced no new bar — never re-anchor on a stale close
        out["skipped"] = "already_issued"
    else:
        try:
            result = compute_forecast(bars)
        except PanelMismatchError as exc:
            log.error("spx_density_forecast: REFUSING to publish — %s", repr(exc))
            # The panel is shared, so reconstruction cannot be trusted either.
            return {**out, "error": "panel_mismatch"}
        except SeriesTooShortError as exc:
            log.warning("spx_density_forecast: %s", repr(exc))
            out["skipped"] = "too_short"
        else:
            out["issued"] = sdr.upsert_rows(
                result_to_db_rows(result, origin="prospective")
            )
            out["as_of"] = str(result.as_of)
            out["fallback_used"] = result.fallback_used
            if result.fallback_used:
                log.warning(
                    "spx_density_forecast: GJR fit unavailable — EWMA FALLBACK issued"
                )

    out["reconstructed"] = len(_reconstruct_pass(sdr, bars))
    return out
