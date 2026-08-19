"""Nightly SPX density cone job — settle then issue (v13 display-only port).

Pass 1 (settle) fills realised_return / inside_band80 for any row whose H-th subsequent
trading day now has a close — pure SQL + arithmetic, so a pass-2 failure never blocks
yesterday's outcomes. Pass 2 (issue) draws today's cone and writes 5 new (as_of, h) rows.
Every degradation is labelled and returned in the summary; nothing is silent.

Holes the issue pass can never reach are filled by :func:`reconstruct_recent_gaps`, which
the nightly data gap healer drives — see its docstring for why they cannot be the same
pass, and ``reports/data_gap_healer`` for the registry entry that wires it up.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta
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


def reconstruct_recent_gaps(
    conn: Any,
    schema: str,
    *,
    lookback_days: int,
) -> dict[str, int]:
    """Fill cone holes the issue pass can never reach, as origin='reconstructed'.

    Driven by the nightly data gap healer (adapter ``spx_density_reconstruct``), not by
    the cone's own job, and deliberately so: the issue pass anchors only the FRESHEST bar
    and self-gates on ``latest_as_of() == anchor``, so once a later cone lands the skipped
    session is unreachable from that pass forever. That is how 2026-08-14 went missing
    while 08-13 and 08-17 were both present — the stack was down, and the job's tue-sat
    cron puts the only chance to issue Friday's anchor on a Saturday.

    Zero provider cost: every input is already in ``vol_index_daily``. Mirrors the shape
    of ``scanners.cri.recover_recent_gaps`` so the healer drives all three identically.

    Two bounds keep this a gap-filler rather than a seeder:
    - the freshest bar is excluded; that one belongs to the issue pass, prospectively.
    - nothing older than the earliest cone already on record is touched. An empty log
      means history has not been seeded yet, which is the backfill script's job, not a
      side effect of a nightly heal.
    """
    sdr = SpxDensityRepository(conn, schema=schema)
    bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
    if len(bars) < 2:
        return {"checked": 0, "filled": 0}
    prospective = sdr.fetch_as_ofs_with_origin("prospective")
    existing = prospective | sdr.fetch_as_ofs_with_origin("reconstructed")
    if not existing:
        # unseeded log — scripts/backfill/spx_density_backfill.py owns seeding
        return {"checked": 0, "filled": 0}
    floor = max(min(existing), bars[-1][0] - timedelta(days=max(1, lookback_days)))
    candidates = [d for d, _ in bars[:-1] if d >= floor]
    writable = select_sessions(candidates, existing=existing, prospective=prospective)
    written = _reconstruct(sdr, bars, writable)
    return {"checked": len(candidates), "filled": len(written)}


def _reconstruct(
    sdr: SpxDensityRepository,
    bars: list[tuple[date, float]],
    writable: list[date],
) -> list[date]:
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
    anchor = bars[-1][0]
    if sdr.latest_as_of() == anchor:
        # vol_index_lake_sync produced no new bar — never re-anchor on a stale close.
        # Holes BELOW the anchor are not this pass's job; the healer's
        # spx_density_reconstruct adapter fills those.
        return {"settled": settled, "issued": 0, "skipped": "already_issued"}

    try:
        result = compute_forecast(bars)
    except PanelMismatchError as exc:
        log.error("spx_density_forecast: REFUSING to publish — %s", repr(exc))
        return {"settled": settled, "issued": 0, "error": "panel_mismatch"}
    except SeriesTooShortError as exc:
        log.warning("spx_density_forecast: %s", repr(exc))
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
