#!/usr/bin/env python
"""Seed the versioned research taxonomy, its alias rules, and derived exposures.

    uv run python scripts/backfill/research_taxonomy_seed.py
    uv run python scripts/backfill/research_taxonomy_seed.py --measure

Zero provider budget — every input is already in Postgres.

THE ALIAS PACK IS SMALL ON PURPOSE
----------------------------------
Measured on the local store: the dominant XBRL segment tag is the GENERIC
`ReportableSegmentMember` (47 of ~400 tickers), and the chain-relevant names
below appear on one or two filers each. A large speculative pattern list would
manufacture apparent coverage by matching loosely; these patterns are literal
business names taken from tags actually present, and the yield they produce is
reported rather than tuned.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_taxonomy_seed import (
    TAXONOMY_V1,
    assert_membership_exposure,
    derive_disclosed_exposure,
    mirror_watchlist_chain,
    seed_aliases,
)

APPROVER = "argon-research"

#: chain -> literal segment-name substrings observed in real filings.
#: Every pattern here was verified present in `revenue_breakdown_obs`; none is
#: aspirational. `role` says what participating in the chain MEANS for that
#: segment, and `beneficiary` is the honest default — a company selling into a
#: chain benefits from it, which is weaker than claiming it supplies a named
#: counterparty.
ALIASES: list[dict[str, str]] = [
    # --- AI infrastructure (the content pack M5.1 asks for first) ---
    {"chain": "AI-Cloud/NeoCloud", "pattern": "datacenter", "role": "beneficiary"},
    {"chain": "AI-Cloud/NeoCloud", "pattern": "cloudai", "role": "beneficiary"},
    {"chain": "AI-Cloud/NeoCloud", "pattern": "googlecloud", "role": "beneficiary"},
    {"chain": "AI-Cloud/NeoCloud", "pattern": "hybridcloud", "role": "beneficiary"},
    {"chain": "AI-Cloud/NeoCloud", "pattern": "cloudservices", "role": "beneficiary"},
    {"chain": "Semi-Logic/ASIC", "pattern": "semiconductor", "role": "manufacturer"},
    {"chain": "Software/SaaS", "pattern": "infrastructuresoftware", "role": "integrator"},
    {"chain": "Software/SaaS", "pattern": "applicationsoftware", "role": "integrator"},
    {"chain": "Power/Electrical", "pattern": "electricpower", "role": "supplier"},
    {"chain": "Power/Electrical", "pattern": "energyinfrastructure", "role": "supplier"},
    # --- Optical communication: M5.5's extensibility proof. ---
    # Added as ROWS, not as code. If this chain had needed a schema change, a new
    # job, or a scoring fork, the proof would have failed here.
    {"chain": "Optical-Communication", "pattern": "datacenternetworking", "role": "component"},
    {"chain": "Optical-Communication", "pattern": "communicationssolutions", "role": "component"},
    {"chain": "Optical-Communication", "pattern": "datacenterandcommunications", "role": "component"},
    {"chain": "Optical-Communication", "pattern": "blueplanetautomation", "role": "integrator"},
    {"chain": "Optical-Communication", "pattern": "opticalcommunication", "role": "component"},
    {"chain": "Optical-Communication", "pattern": "photonic", "role": "component"},
]

#: The optical chain's layers. Upstream -> downstream is a READING order.
OPTICAL_LAYERS = [
    ("Upstream-Components", 10, "lasers, photonic ICs, passive optics"),
    ("Semi-DSP-Switch", 20, "DSP and switch silicon"),
    ("Module-Transceiver", 30, "pluggable optical modules"),
    ("Systems-Networking", 40, "switches, routers, line systems"),
    ("Customer-Cloud", 70, "hyperscale buyers of optical capacity"),
]

#: Seeded optical membership. `analyst` evidence class — these are asserted
#: placements, and the class is what stops them reading as disclosures later.
#: Restricted to names already in the universe so nothing here widens coverage
#: by inventing tickers.
OPTICAL_MEMBERS = [
    ("Upstream-Components", ["COHR", "LITE", "AAOI", "POET"]),
    ("Semi-DSP-Switch", ["AVGO", "MRVL", "CRDO", "SMTC"]),
    ("Module-Transceiver", ["COHR", "LITE", "AAOI", "FN"]),
    ("Systems-Networking", ["ANET", "CIEN", "NTAP", "JNPR", "INFN"]),
    ("Customer-Cloud", ["MSFT", "AMZN", "GOOGL", "META", "ORCL"]),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--measure", action="store_true", help="print coverage only")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    settings = Settings.from_env()
    out: dict[str, object] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        repo = ResearchTaxonomyRepository(conn, schema=schema)

        if not args.measure:
            out["mirror"] = mirror_watchlist_chain(conn, schema=schema)

            # Optical layers + membership through the SAME general calls the
            # mirrored chains use. That symmetry is the extensibility proof.
            repo.define_chains(
                TAXONOMY_V1,
                [
                    {
                        "domain": "optical_communication",
                        "chain": "Optical-Communication",
                        "layer": layer,
                        "layer_rank": rank,
                        "description": desc,
                    }
                    for layer, rank, desc in OPTICAL_LAYERS
                ],
            )
            universe = set()
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT ticker FROM {schema}.fundamental_universe "
                    f"WHERE removed_at IS NULL"
                )
                universe = {r[0].upper() for r in cur.fetchall()}
            opened = skipped = 0
            for layer, tickers in OPTICAL_MEMBERS:
                for t in tickers:
                    if t not in universe:
                        # Recorded as a gap, not silently dropped: a chain whose
                        # members are absent from the universe cannot be
                        # aggregated, and that is a finding.
                        skipped += 1
                        continue
                    opened += repo.add_membership(
                        TAXONOMY_V1,
                        chain="Optical-Communication",
                        layer=layer,
                        ticker=t,
                        evidence_class="analyst",
                        approved_by=APPROVER,
                        note="asserted placement; not a disclosure",
                    )
            out["optical"] = {"opened": opened, "not_in_universe": skipped}

            out["aliases"] = seed_aliases(
                conn,
                [{**a, "approved_by": APPROVER} for a in ALIASES],
                schema=schema,
            )
            out["disclosed"] = derive_disclosed_exposure(conn, schema=schema)
            out["asserted"] = assert_membership_exposure(conn, schema=schema)

        out["coverage"] = repo.exposure_coverage(TAXONOMY_V1)

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
