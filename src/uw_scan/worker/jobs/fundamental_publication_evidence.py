"""Upgrade statement versions from `capture_bounded` to `true_pit` where SEC allows.

This is the ONLY job in Argon that can write a `true_pit` claim. Everything else
dates a fetch; this dates a publication. Until it runs, every leak-free replay
returns empty at every cutoff, because `true_pit` is zero.

WHAT A RUN REPORTS, AND WHY IT REPORTS REFUSALS BY NAME
------------------------------------------------------
The counters carry one entry per refusal reason, not just a matched total. A run
that says "matched 61%" cannot distinguish a universe of serial restaters from a
stale filing index from a period-key mismatch — three problems with three
different fixes. Naming the refusal makes the next action obvious.

The job writes NOTHING for a refused identity. That is not a degraded outcome:
the observation keeps its `capture_bounded` claim, `CAPTURE_BOUNDED` replays keep
working unchanged, and only `TRUE_PIT_ONLY` sees the difference.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, time

import psycopg

from uw_scan.fundamentals.publication_evidence import (
    CLAIM_KEY_SEC_PUBLICATION,
    REFUSAL_REASONS,
    SOURCE_SEC_EDGAR,
    match_publication,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository

logger = logging.getLogger(__name__)

_BATCH = 2000


def _available_at(filing_date) -> datetime:
    """A filing date becomes an instant at end of day UTC.

    SEC publishes a DATE, not a timestamp. Anchoring at 00:00 would claim the
    content was public before the business day it was filed on; end of day is the
    conservative reading and matches how `available_at <= as_of` is used —
    a same-day cutoff admits the filing, an earlier one does not.
    """
    return datetime.combine(filing_date, time.max, tzinfo=UTC)


def fundamental_publication_evidence(
    *,
    conn: psycopg.Connection,
    schema: str = "uw_scan",
    tickers: Sequence[str] | None = None,
    tier: str = "ranked",
) -> dict[str, int]:
    """Apply the publication rule across the universe. Returns counters."""
    obs = FundamentalObsRepository(conn, schema)
    index = SecFilingIndexRepository(conn, schema)
    avail = FundamentalObsAvailabilityRepository(conn, schema)

    names = [t.upper() for t in (tickers or obs.list_universe(tier))]
    counters: dict[str, int] = {
        "identities": 0,
        "matched": 0,
        "claims_written": 0,
        "no_index": 0,
    }
    for reason in REFUSAL_REASONS:
        counters[reason] = 0
    if not names:
        return counters

    filings_by_ticker = index.filings_by_ticker(names)
    identities = obs.statement_identities(
        names, exclude_claim_key=CLAIM_KEY_SEC_PUBLICATION
    )

    pending: list[dict] = []
    for ident in identities:
        counters["identities"] += 1
        filings = filings_by_ticker.get(ident["ticker"])
        if filings is None:
            # No index row at all for the issuer. Distinct from "no filing near
            # this period": one means run the index refresh, the other means the
            # period genuinely has no periodic filing.
            counters["no_index"] += 1
            continue

        match, reason = match_publication(
            ident["period_end"], filings, version_count=ident["version_count"]
        )
        if match is None:
            counters[reason] += 1
            continue

        counters["matched"] += 1
        for obs_id in ident["obs_ids"]:
            pending.append(
                {
                    "obs_id": obs_id,
                    "claim_key": CLAIM_KEY_SEC_PUBLICATION,
                    "evidence_class": "true_pit",
                    "available_at": _available_at(match.filing_date),
                    "evidence_source": SOURCE_SEC_EDGAR,
                    "evidence_ref": match.accession,
                    "evidence_jsonb": {
                        "period_end": ident["period_end"].isoformat(),
                        "statement": ident["statement"],
                        "filing_date": match.filing_date.isoformat(),
                    },
                }
            )
        if len(pending) >= _BATCH:
            counters["claims_written"] += avail.record_claims(pending)
            pending = []

    if pending:
        counters["claims_written"] += avail.record_claims(pending)

    logger.info("fundamental_publication_evidence: %s", counters)
    return counters
