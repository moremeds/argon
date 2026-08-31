#!/usr/bin/env python
"""Operator entry point for SEC publication evidence.

Two stages, deliberately separate:

  --index     mirror SEC's filing index (network-bound, ~0.2s/issuer)
  --evidence  apply the publication rule and write true_pit claims (pure DB)

Running them separately means a slow network stage can be re-run without
re-deciding settled claims, and the rule can be re-applied instantly after an
index top-up.

  uv run python scripts/backfill/sec_publication_evidence.py --index --only-missing
  uv run python scripts/backfill/sec_publication_evidence.py --evidence
  uv run python scripts/backfill/sec_publication_evidence.py --measure
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs.fundamental_publication_evidence import (
    fundamental_publication_evidence,
)
from uw_scan.worker.jobs.sec_filing_index_refresh import sec_filing_index_refresh


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickers", help="comma-separated; default is the whole tier")
    p.add_argument("--tier", default="ranked")
    p.add_argument("--index", action="store_true", help="refresh the SEC filing index")
    p.add_argument("--only-missing", action="store_true", help="skip indexed issuers")
    p.add_argument("--evidence", action="store_true", help="apply the rule")
    p.add_argument("--measure", action="store_true", help="print counts only")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else None
    )

    settings = Settings.from_env()
    out: dict[str, object] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        if args.index:
            out["index"] = sec_filing_index_refresh(
                conn=conn,
                schema=schema,
                tickers=tickers,
                tier=args.tier,
                only_missing=args.only_missing,
            )
        if args.evidence:
            out["evidence"] = fundamental_publication_evidence(
                conn=conn, schema=schema, tickers=tickers, tier=args.tier
            )
        if args.measure or not (args.index or args.evidence):
            out["index_counts"] = SecFilingIndexRepository(conn, schema).index_counts()
            counts = FundamentalObsAvailabilityRepository(conn, schema).claim_counts()
            out["claim_counts"] = {k.value: v for k, v in counts.items()}

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
