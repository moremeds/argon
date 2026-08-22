"""Nightly recompute of the fundamental lane: routing -> subscores -> anchors.

The three stages were built and tested independently and NOTHING RAN THEM. Until
this job existed, `fundamental_scoring` and `fundamental_anchors` had no caller
outside tests — the card rendered whatever a hand-run had last written, and would
have gone quietly stale the first day nobody ran it by hand.

WHY IT IS WORTH A NIGHTLY RUN EVEN WHEN NO FILING LANDED
--------------------------------------------------------
The five anchor levels only move on a filing, but `spot` and `spot_percentile`
move with the price, and `valuation_anchors.as_of` is the SPOT date precisely so
that daily record accumulates. A weekly cadence would leave the card telling the
reader where price sat inside its own band up to six days ago.

`as_of` is the date of the CLOSE the row was priced at, not the date this job
ran; the two coincide only when the lake is current, and it is an EOD store that
lands a session around midnight New York — after this job's 18:20 ET slot. A
healthy Monday run therefore writes `as_of` = Friday. This paragraph said
"COMPUTE date" until 2026-08-19 and cost a debugging session that read the
resulting date spread as a broken job. The full argument, including why keying
on the clock would be actively wrong, is in `fundamental_anchors.py`.

COST
----
Zero external calls. Every stage reads Postgres plus the local parquet mirror, so
this belongs on massive-0 next to the other warm-store compute rather than
anywhere near the UW budget.

WHAT THIS DOES *NOT* DO
-----------------------
It does not ingest statements. `scripts/backfill/fundamental_ingest_backfill.py`
is still the only path that pulls new filings from UW, and it is still manual.
So this job keeps the derived layers fresh against whatever panel exists; a
quarter that was never ingested stays absent, and the card's staleness reason
("latest filing is N days old") is what surfaces it.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.worker.jobs.fundamental_anchors import (
    fundamental_anchors,
    seed_company_types,
)
from uw_scan.worker.jobs.fundamental_scoring import fundamental_scoring

log = logging.getLogger(__name__)


def fundamental_refresh(
    *, conn: psycopg.Connection, settings: Settings
) -> dict[str, Any]:
    """Route, score, then band. Returns each stage's counters.

    Ordered, and the order is load-bearing: anchors read `company_type`, so a
    name routed in this run must be routed BEFORE the band pass or it waits a
    day for no reason. Scoring sits between them because both later stages key
    off the same active `engine_version`.
    """
    routing = seed_company_types(conn, schema=settings.db_schema)
    scoring = fundamental_scoring(conn=conn, schema=settings.db_schema)
    anchors = fundamental_anchors(
        conn=conn,
        lake_root=settings.lake_credit_etf_root,
        # Sibling of the bronze root the other lake readers use. No separate env
        # var: the mini already sets MARKET_WAREHOUSE_LAKE=/lake and mounts the
        # whole tree read-only, so silver is reachable there the moment this ships.
        silver_root=settings.market_warehouse_lake_root / "silver/asset_class=equity",
        fx_root=settings.lake_fx_root,
        schema=settings.db_schema,
    )
    summary = {"routing": routing, "scoring": scoring, "anchors": anchors}
    log.info("fundamental_refresh %s", summary)
    return summary
