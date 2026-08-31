"""Classify what Argon can honestly say about every stored statement version.

Operator backfill, not a scheduled job. It reads no provider, spends no UW or IB
budget, and touches only rows Argon already holds — so it is deliberately absent
from the nightly budget and from the scheduler. `scripts/backfill/
fundamental_observation_availability.py` is the entry point; it holds no logic of
its own so a manual run and any future scheduled run cannot drift apart.

WHAT IT MAY DERIVE, AND WHAT IT MAY NOT
---------------------------------------
Two claims per observation, both derivable from the row itself:

- `current_vintage` — this content can serve today's page. Every legacy row gets
  one, which is what makes "no claim at all" mean "never classified" rather than
  "classified as useless".
- `capture_bounded` at the row's own `first_observed_at` — Argon holds this exact
  content and first saw it then, so admitting it at or after that instant cannot
  leak. Conservative on purpose: the world may well have known earlier, and this
  claim never says otherwise.

It may NOT issue `true_pit`. The temptation is `filing_published_at`, which is
populated on most rows and would lift true-PIT coverage from nothing to nearly
everything in one run. It describes when the ORIGINAL filing for the period was
published; a later content hash for the same period is a different artifact and
inherits none of that authority. Promoting on it would reintroduce the exact
look-ahead this work removes while LOOKING like a coverage win. True-PIT arrives
only from a source that can point at the version's own publication artifact.

WHY IT IS RESUMABLE WITHOUT A PROGRESS TABLE
--------------------------------------------
Both claims are written under deterministic `claim_key`s with `ON CONFLICT DO
NOTHING`, so re-running is a no-op over ground already covered. The walk is
keyset over `obs_id`, never `OFFSET`: forward ingest keeps appending rows while a
backfill runs, and an offset walk over a growing table skips rows silently.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import psycopg

from uw_scan.fundamentals.observation_time import EvidenceClass
from uw_scan.storage.fundamental_observation_availability import (
    PAGE,
    FundamentalObsAvailabilityRepository,
)

log = logging.getLogger(__name__)


def fundamental_observation_availability(
    *,
    conn: psycopg.Connection,
    schema: str = "uw_scan",
    tickers: Sequence[str] | None = None,
    batch_size: int = PAGE,
    max_batches: int | None = None,
) -> dict[str, int]:
    """Classify stored observations. Returns counters; safe to re-run.

    `max_batches` bounds one invocation so an operator can take a slice, inspect
    it, and resume — the bound changes how MUCH is classified, never HOW, which
    is why no counter distinguishes a bounded run from a complete one.
    """
    repo = FundamentalObsAvailabilityRepository(conn, schema=schema)
    before = repo.claim_counts()

    totals = {
        "scanned": 0,
        "current_vintage_inserted": 0,
        "capture_inserted": 0,
        "already_present": 0,
        "batches": 0,
    }

    cursor = 0
    while max_batches is None or totals["batches"] < max_batches:
        vintage, next_cursor = repo.seed_claims(
            EvidenceClass.CURRENT_VINTAGE,
            tickers=tickers,
            after_obs_id=cursor,
            limit=batch_size,
        )
        if next_cursor is None:
            break
        capture, _ = repo.seed_claims(
            EvidenceClass.CAPTURE_BOUNDED,
            tickers=tickers,
            after_obs_id=cursor,
            limit=batch_size,
        )
        # The page is the unit of work; both classes walk the SAME page, so one
        # scanned count covers both and a mismatch between them is real news.
        scanned = _page_size(conn, schema, cursor, next_cursor, tickers)
        totals["scanned"] += scanned
        totals["current_vintage_inserted"] += vintage
        totals["capture_inserted"] += capture
        totals["already_present"] += scanned - vintage
        totals["batches"] += 1
        cursor = next_cursor

    after = repo.claim_counts()
    log.info(
        "fundamental_observation_availability: %s (claims %s -> %s)",
        totals,
        {k.value: v for k, v in before.items()},
        {k.value: v for k, v in after.items()},
    )
    return totals


def _page_size(
    conn: psycopg.Connection,
    schema: str,
    after: int,
    through: int,
    tickers: Sequence[str] | None,
) -> int:
    """Observations in the page just walked — the denominator for `already_present`."""
    where = ["obs_id > %(after)s", "obs_id <= %(through)s"]
    params: dict[str, object] = {"after": after, "through": through}
    if tickers is not None:
        where.append("ticker = ANY(%(tickers)s)")
        params["tickers"] = list(tickers)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {schema}.fundamental_statement_obs "
            f"WHERE {' AND '.join(where)}",
            params,
        )
        return int(cur.fetchone()[0])
